"""What to fetch from football-data.org, and with which load strategy.

The client (`football_data_client.py`) knows *how* to call the API. This module
knows *what* the pipeline needs and why - kept apart so that adding an endpoint
is a one-line change in a list rather than a change to HTTP code.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from deng.ingestion.football_data_client import (
    ApiResponse,
    FootballDataClient,
    RetryableApiError,
)

logger = logging.getLogger(__name__)

# Free tier: 10 requests/minute. We pace ourselves rather than waiting for the
# HTTP 429, and additionally react to the remaining-budget header (see `_pace`).
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
    for index, endpoint in enumerate(endpoints):
        if index:
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
            delay *= 2
    raise AssertionError("unreachable")  # pragma: no cover


def _pace(response: ApiResponse, pace_seconds: float) -> None:
    """Sleep longer when the API says the remaining minute budget is nearly spent."""
    remaining = response.rate_limit.requests_available_minute
    reset = response.rate_limit.counter_reset_seconds
    if remaining is not None and remaining <= 1 and reset:
        logger.info("rate-limit budget exhausted, waiting %ss for the counter to reset", reset)
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
