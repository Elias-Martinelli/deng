"""Unit tests for the football-data.org client – no network access needed."""

import json
from unittest.mock import MagicMock

import pytest
import requests

from deng.sources.football_data import (
    ApiError,
    FootballDataClient,
    RateLimitInfo,
    RetryableApiError,
)


def _fake_response(status: int, body, headers: dict | None = None) -> MagicMock:
    response = MagicMock(spec=requests.Response)
    response.status_code = status
    response.headers = headers or {}
    response.url = "https://api.football-data.org/v4/competitions/CL/matches"
    response.text = json.dumps(body) if not isinstance(body, str) else body
    if isinstance(body, str):
        response.json.side_effect = ValueError("not json")
    else:
        response.json.return_value = body
    return response


def _client_with(response_or_exc) -> FootballDataClient:
    session = MagicMock(spec=requests.Session)
    session.headers = {}
    if isinstance(response_or_exc, Exception):
        session.get.side_effect = response_or_exc
    else:
        session.get.return_value = response_or_exc
    return FootballDataClient(api_key="dummy", session=session)


def test_successful_get_returns_payload_and_rate_limit():
    body = {"matches": [{"id": 1}], "count": 1}
    headers = {"X-Requests-Available-Minute": "7", "X-RequestCounter-Reset": "42"}
    client = _client_with(_fake_response(200, body, headers))

    result = client.get("competitions/CL/matches", params={"status": "SCHEDULED"})

    assert result.payload == body
    assert result.rate_limit == RateLimitInfo(requests_available_minute=7, counter_reset_seconds=42)


def test_auth_header_is_set_on_session():
    session = MagicMock(spec=requests.Session)
    session.headers = {}
    FootballDataClient(api_key="abc123", session=session)
    assert session.headers["X-Auth-Token"] == "abc123"


@pytest.mark.parametrize("status", [429, 500, 503])
def test_transient_errors_are_retryable(status):
    client = _client_with(_fake_response(status, {"message": "slow down"}))
    with pytest.raises(RetryableApiError) as exc_info:
        client.get("competitions/CL/matches")
    assert exc_info.value.status_code == status
    assert "slow down" in str(exc_info.value)


@pytest.mark.parametrize("status", [400, 403, 404])
def test_client_errors_are_not_retryable(status):
    client = _client_with(_fake_response(status, {"message": "restricted resource"}))
    with pytest.raises(ApiError) as exc_info:
        client.get("competitions/CL/matches?season=2019")
    assert not isinstance(exc_info.value, RetryableApiError)
    assert exc_info.value.status_code == status


def test_network_failure_is_retryable():
    client = _client_with(requests.ConnectionError("boom"))
    with pytest.raises(RetryableApiError):
        client.get("competitions/CL")


def test_invalid_json_is_an_api_error():
    client = _client_with(_fake_response(200, "<html>maintenance</html>"))
    with pytest.raises(ApiError, match="invalid JSON"):
        client.get("competitions/CL")


def test_rate_limit_headers_tolerate_garbage():
    info = RateLimitInfo.from_headers({"X-Requests-Available-Minute": "n/a"})
    assert info.requests_available_minute is None
    assert info.counter_reset_seconds is None
