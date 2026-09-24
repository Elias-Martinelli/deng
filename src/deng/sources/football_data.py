"""What to fetch from football-data.org, and with which load strategy.

The client (`football_data_client.py`) knows *how* to call the API. This module
knows *what* the pipeline needs and why - kept apart so that adding an endpoint
is a one-line change in a list rather than a change to HTTP code.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import psycopg
import requests

from deng.config import Settings
from deng.database.raw_loader import RawLoader
from deng.sources.http import ApiError, RetryableApiError

logger = logging.getLogger(__name__)

SOURCE = "football-data.org"
SAMPLE_SOURCE = "football-data.org (sample)"

# Free tier: 10 requests/minute. We pace ourselves rather than waiting for the
# HTTP 429, and additionally react to the remaining-budget header (see `_pace`).
# 60 s / 10 = 6 s per request; the extra 0.5 s absorbs clock differences between
# us and the API's counter, so a full minute of requests never hits the limit.
MIN_SECONDS_BETWEEN_REQUESTS = 6.5


@dataclass(frozen=True)
class Endpoint:
    """One endpoint the daily batch fetches.

    Attributes:
        name: Short identifier used in logs and evidence output.
        path: Path template; `{code}` is replaced with the competition code.
        params: Query parameters.
        load_strategy: FULL or INCREMENTAL - documented per endpoint below.
        rationale: Why this endpoint is fetched and at this frequency. Kept in
            code so the justification cannot drift away from the implementation.
    """

    name: str
    path: str
    params: dict[str, Any] = field(default_factory=dict)
    load_strategy: str = "FULL"
    rationale: str = ""


# Why FULL for everything at this stage:
#
# The complete season fixture list is ~210 KB and one request. An incremental
# strategy based on `lastUpdated` would need a second request to discover what
# changed, and would still miss matches that the API *adds* mid-season (the
# knockout draw in December - see docs/evidence/api-exploration.md §6). Full
# reload of a small, bounded payload is simpler, self-healing after any missed
# day, and costs one request. It stops being right when we ingest many seasons
# at once: there, INCREMENTAL by season is the plan (backlog 1.9).
DAILY_ENDPOINTS: tuple[Endpoint, ...] = (
    Endpoint(
        name="competition",
        path="competitions/{code}",
        load_strategy="FULL",
        rationale="Season metadata and the list of available seasons; 9 KB, changes rarely.",
    ),
    Endpoint(
        name="teams",
        path="competitions/{code}/teams",
        load_strategy="FULL",
        rationale="Feeds dim_team. 36 rows, stable within a season, one request.",
    ),
    Endpoint(
        name="standings",
        path="competitions/{code}/standings",
        load_strategy="FULL",
        rationale="Changes after every matchday; the whole table is one request.",
    ),
    Endpoint(
        name="matches",
        path="competitions/{code}/matches",
        load_strategy="FULL",
        rationale=(
            "Fixtures and results. Full reload because matches are added mid-season "
            "and kick-off times change in place; 212 KB in one request."
        ),
    ),
)


def fetch_endpoints(
    client: FootballDataClient,
    competition_code: str,
    endpoints: tuple[Endpoint, ...] = DAILY_ENDPOINTS,
    pace_seconds: float = MIN_SECONDS_BETWEEN_REQUESTS,
    max_attempts: int = 3,
) -> Iterator[tuple[Endpoint, ApiResponse]]:
    """Fetch each endpoint in turn, pacing requests and retrying transient errors.

    Args:
        client: The API client.
        competition_code: Competition to substitute into the path templates.
        endpoints: Endpoints to fetch.
        pace_seconds: Minimum delay between two requests.
        max_attempts: Attempts per endpoint before the error is raised.

    Yields:
        `(endpoint, response)` pairs in order.

    Raises:
        ApiError: on a non-retryable error - the run must fail visibly.
        RetryableApiError: if the transient error persists after `max_attempts`.
    """
    # A generator, not a list: each payload is handed to the loader as soon as it
    # arrives, and an error on the third endpoint surfaces before a fourth
    # request is spent. The caller's transaction still decides what is kept.
    for index, endpoint in enumerate(endpoints):
        if index:  # no pause before the first request
            time.sleep(pace_seconds)
        path = endpoint.path.format(code=competition_code)
        response = _get_with_retry(client, path, endpoint.params, max_attempts, pace_seconds)
        _pace(response, pace_seconds)
        yield endpoint, response


def _get_with_retry(
    client: FootballDataClient,
    path: str,
    params: dict[str, Any],
    max_attempts: int,
    pace_seconds: float,
) -> ApiResponse:
    """GET with exponential back-off, but only for errors that can succeed later.

    A 403 or 400 is raised immediately: repeating it would burn our request
    budget without any chance of a different answer.
    """
    delay = pace_seconds
    for attempt in range(1, max_attempts + 1):
        try:
            return client.get(path, params=params)
        except RetryableApiError as exc:
            if attempt == max_attempts:
                logger.error("giving up on %s after %s attempts: %s", path, attempt, exc)
                raise
            logger.warning(
                "transient error on %s (attempt %s/%s): %s - retrying in %.1fs",
                path,
                attempt,
                max_attempts,
                exc,
                delay,
            )
            time.sleep(delay)
            # Exponential back-off (6.5 s, 13 s, ...): a server that is struggling
            # gets more room with every attempt instead of a burst of retries.
            delay *= 2
    raise AssertionError("unreachable")  # pragma: no cover


def _pace(response: ApiResponse, pace_seconds: float) -> None:
    """Sleep longer when the API says the remaining minute budget is nearly spent."""
    remaining = response.rate_limit.requests_available_minute
    reset = response.rate_limit.counter_reset_seconds
    if remaining is not None and remaining <= 1 and reset:
        logger.info("rate-limit budget exhausted, waiting %ss for the counter to reset", reset)
        # +1 s so we arrive after the reset, not on it; capped at 65 s so a
        # nonsensical header value cannot stall the run for hours.
        time.sleep(min(reset + 1, 65))


# --- Offline source ---------------------------------------------------------
#
# The committed sample payloads (docs/evidence/api-exploration.md) can stand in
# for the API. This is a reproducibility feature, not a test hack: a peer
# reviewer can run the complete local pipeline - ingestion, raw zone,
# verification, reruns - before registering an API key, and our own idempotency
# evidence is reproducible byte for byte because the input never changes.
#
# It is deliberately NOT a fallback: nothing falls back to samples silently. The
# caller has to ask for it, and the stored payload records which source it came
# from.

SAMPLE_DIR_NAME = Path("data") / "sample" / "football-data"

# Maps each daily endpoint to the sample file captured for it.
SAMPLE_FILES: dict[str, str] = {
    "competition": "competition.json",
    "teams": "teams.json",
    "standings": "standings.json",
    "matches": "matches_all.json",
}


def sample_dir() -> Path:
    """Locate the committed sample payloads (repo root or container workdir)."""
    candidate = Path.cwd() / SAMPLE_DIR_NAME
    if candidate.is_dir():
        return candidate
    return Path(__file__).resolve().parents[3] / SAMPLE_DIR_NAME


def read_sample_endpoints(
    competition_code: str,
    endpoints: tuple[Endpoint, ...] = DAILY_ENDPOINTS,
) -> Iterator[tuple[Endpoint, ApiResponse]]:
    """Yield the same `(endpoint, response)` pairs as `fetch_endpoints`, from disk.

    Raises:
        FileNotFoundError: if a sample file is missing, so the run fails visibly
            instead of quietly ingesting less than expected.
    """
    directory = sample_dir()
    for endpoint in endpoints:
        filename = SAMPLE_FILES.get(endpoint.name)
        if filename is None:
            continue
        path = directory / filename
        if not path.exists():
            raise FileNotFoundError(
                f"sample payload {path} is missing - run `make explore` with an API key "
                "or use the API instead of --from-samples"
            )
        payload = json.loads(path.read_text())
        url = f"file://{path}"
        logger.info("reading sample payload for %s from %s", endpoint.name, path.name)
        yield endpoint, ApiResponse(url=url, status_code=200, payload=payload)


# ---------------------------------------------------------------------------
# Talking to the API: the client half of this source
# ---------------------------------------------------------------------------

# Upper bound for one request. The largest payload (the season's fixture list,
# ~212 KB) arrives in well under a second; 30 s only matters when the API hangs,
# and then a timeout that surfaces as a retryable error beats a run that waits
# forever and never records a failure.
DEFAULT_TIMEOUT_SECONDS = 30


@dataclass
class RateLimitInfo:
    """Rate-limit bookkeeping returned by football-data.org in response headers."""

    requests_available_minute: int | None = None
    counter_reset_seconds: int | None = None

    @classmethod
    def from_headers(cls, headers: Any) -> RateLimitInfo:
        """Parse the `X-Requests-Available-Minute` / `X-RequestCounter-Reset` headers."""
        return cls(
            requests_available_minute=_to_int(headers.get("X-Requests-Available-Minute")),
            counter_reset_seconds=_to_int(headers.get("X-RequestCounter-Reset")),
        )


@dataclass
class ApiResponse:
    """A parsed JSON payload plus the metadata we want to persist with raw data."""

    url: str
    status_code: int
    payload: dict[str, Any]
    rate_limit: RateLimitInfo = field(default_factory=RateLimitInfo)


class FootballDataClient:
    """Minimal client for `https://api.football-data.org/v4`."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.football-data.org/v4",
        session: requests.Session | None = None,
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        """Create a client; a custom `session` allows injecting a mock in tests."""
        # rstrip/lstrip below make "…/v4" + "competitions/CL" and "…/v4/" +
        # "/competitions/CL" produce the same URL - a typo in .env must not
        # silently turn into a 404.
        self._base_url = base_url.rstrip("/")
        # One Session re-uses the TCP/TLS connection across the daily requests
        # and carries the auth header, so it is set once, not per call.
        self._session = session or requests.Session()
        self._session.headers.update({"X-Auth-Token": api_key, "Accept": "application/json"})
        self._timeout = timeout

    def get(self, path: str, params: dict[str, Any] | None = None) -> ApiResponse:
        """Perform a GET request and return the parsed JSON payload.

        Args:
            path: Endpoint path relative to the base URL, e.g. `competitions/CL/matches`.
            params: Optional query parameters (filters such as `status`, `dateFrom`).

        Raises:
            RetryableApiError: on HTTP 429, HTTP 5xx or network-level failures.
            ApiError: on other non-2xx responses or invalid JSON.
        """
        url = f"{self._base_url}/{path.lstrip('/')}"
        try:
            response = self._session.get(url, params=params, timeout=self._timeout)
        except requests.RequestException as exc:  # timeouts, DNS, connection resets
            # No HTTP answer at all, hence status 0. Network trouble is the
            # textbook transient error, so it is classified as retryable.
            raise RetryableApiError(0, f"network error calling {url}: {exc}") from exc

        rate_limit = RateLimitInfo.from_headers(response.headers)
        logger.debug(
            "GET %s -> %s (requests left this minute: %s)",
            response.url,
            response.status_code,
            rate_limit.requests_available_minute,
        )

        # 429 (rate limit) and 5xx (their server) can succeed later - retry.
        # Every other 4xx is about *our* request (bad path, missing plan, wrong
        # key): the same request will fail the same way, so fail fast.
        if response.status_code == 429 or response.status_code >= 500:
            raise RetryableApiError(response.status_code, _error_message(response))
        if response.status_code >= 400:
            raise ApiError(response.status_code, _error_message(response))

        # A 200 with a body that is not JSON is treated as permanent on purpose:
        # it points at a changed API or a proxy page, which a human must look at.
        # Retrying would hide it for three attempts and then fail anyway.
        try:
            payload = response.json()
        except ValueError as exc:
            raise ApiError(response.status_code, f"invalid JSON from {url}") from exc
        # Every v4 endpoint we use answers with a JSON object; a list or a bare
        # value would break the raw loader's assumptions, so it stops here.
        if not isinstance(payload, dict):
            raise ApiError(response.status_code, f"unexpected payload type from {url}")

        return ApiResponse(
            url=response.url,
            status_code=response.status_code,
            payload=payload,
            rate_limit=rate_limit,
        )


def _error_message(response: requests.Response) -> str:
    """Extract the API's error message if present, otherwise a short body excerpt."""
    try:
        body = response.json()
        if isinstance(body, dict) and "message" in body:
            return str(body["message"])
    except ValueError:
        pass
    return response.text[:200]


def _to_int(value: str | None) -> int | None:
    """Convert a header value to int, tolerating missing or malformed values."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Ingesting: ask the four endpoints and store the answers unchanged
# ---------------------------------------------------------------------------


@dataclass
class IngestResult:
    """What one football ingestion did."""

    stored: int = 0
    records: int = 0
    lines: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        """One line for the CLI and the logs."""
        return f"{self.stored} payload(s), {self.records} records"


def ingest(
    connection: psycopg.Connection,
    logical_date: date,
    run_id: uuid.UUID,
    settings: Settings,
    from_samples: bool = False,
) -> IngestResult:
    """Fetch every daily endpoint and store the payloads in the raw zone.

    Every payload is written with the idempotent upsert, so a second run for the
    same date updates the row in place instead of adding a copy.

    Args:
        connection: Open connection; committed here, once, for the whole day.
        logical_date: The date this run is responsible for.
        run_id: The run the raw rows belong to.
        settings: Runtime configuration (API key, base URL, competition).
        from_samples: Read the committed sample payloads instead of calling the
            API, so a reviewer can run the pipeline without credentials.

    Returns:
        How many payloads were stored and how many records they contained.

    Raises:
        ApiError: on a permanent API error; RetryableApiError on a transient one.
            The day's partial writes are rolled back before the error is re-raised.
    """
    # `source` is part of the raw zone's unique key, so replayed samples live in
    # their own rows and can never overwrite a real API answer for the same day
    # (and vice versa). Staging takes the newest payload of the day.
    source_name = SAMPLE_SOURCE if from_samples else SOURCE
    if from_samples:
        responses = read_sample_endpoints(settings.football_data_competition)
    else:
        client = FootballDataClient(
            api_key=settings.require_football_api_key(),
            base_url=settings.football_data_base_url,
        )
        responses = fetch_endpoints(client, settings.football_data_competition)

    result = IngestResult()
    loader = RawLoader(connection, source=source_name)
    try:
        for endpoint, response in responses:
            stored = loader.load(
                run_id=run_id,
                endpoint=endpoint.path.format(code=settings.football_data_competition),
                request_params=endpoint.params,
                request_url=response.url,
                payload=response.payload,
                ingestion_date=logical_date,
            )
            result.stored += 1
            result.records += stored.record_count or 0
            result.lines.append(
                f"{endpoint.name:<12} {stored.action:<9} "
                f"records={stored.record_count} hash={stored.payload_hash[:12]}"
            )
        # One commit for all endpoints of the day: either the whole day's
        # snapshot is stored or none of it. A half-stored day (teams but no
        # matches) would let the transformation build an inconsistent state.
        connection.commit()
    except ApiError:
        # Covers RetryableApiError too (subclass). Roll back this day's partial
        # writes, then re-raise so the run is recorded as FAILED.
        connection.rollback()
        raise
    logger.info("football-data.org: %s", result.summary)
    return result
