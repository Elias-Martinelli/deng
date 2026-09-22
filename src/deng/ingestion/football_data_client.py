"""Thin HTTP client for the football-data.org v4 API.

Design notes (relevant for the oral defence):
    * The client only knows *how to talk* to the API (auth header, error
      mapping, rate-limit bookkeeping). *What* to fetch lives in the
      extraction layer. Keeping these apart makes the client trivially
      mockable in tests and reusable for every endpoint.
    * Errors are mapped to two categories so retry policies can react
      correctly: `RetryableApiError` (429, 5xx, network problems) and
      `ApiError` (400/403/404 – repeating the same request will not help).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import requests

logger = logging.getLogger(__name__)

# Upper bound for one request. The largest payload (the season's fixture list,
# ~212 KB) arrives in well under a second; 30 s only matters when the API hangs,
# and then a timeout that surfaces as a retryable error beats a run that waits
# forever and never records a failure.
DEFAULT_TIMEOUT_SECONDS = 30


class ApiError(Exception):
    """Non-retryable API error (client-side mistake, missing permission, not found)."""

    def __init__(self, status_code: int, message: str) -> None:
        """Store status code and message for structured logging."""
        super().__init__(f"HTTP {status_code}: {message}")
        self.status_code = status_code
        self.message = message


class RetryableApiError(ApiError):
    """Transient API error (rate limit, server error, network) – safe to retry.

    A subclass, not a sibling: code that only cares "did the API fail?" catches
    `ApiError` and gets both; code that retries catches this narrower class.
    Callers must therefore check `RetryableApiError` *before* `ApiError`.
    """


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
