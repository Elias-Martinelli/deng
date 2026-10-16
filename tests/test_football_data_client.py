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


def test_offline_samples_cannot_be_relabelled_as_a_different_league():
    from deng.sources.football_data import read_sample_endpoints

    with pytest.raises(ValueError, match="CL only"):
        list(read_sample_endpoints("PL"))


def test_configured_leagues_cache_history_and_deduplicate_team_details(monkeypatch):
    from deng.config import Settings
    from deng.sources.football_data import ApiResponse, IngestResult, _configured_responses

    sleeps = []
    monkeypatch.setattr("deng.sources.football_data.time.sleep", sleeps.append)
    client = MagicMock()

    def answer(path, params):
        payload = {"teams": [{"id": 1}, {"id": 2}]} if path.endswith("/teams") else {}
        return ApiResponse(url=path, status_code=200, payload=payload)

    client.get.side_effect = answer
    settings = Settings(
        _env_file=None,
        football_data_competitions="CL,PL",
        football_data_seasons="2023",
        football_data_team_details=True,
    )
    result = IngestResult()
    cached = {("competitions/CL/matches", "2023"), ("competitions/CL/teams", "2023")}
    responses = list(_configured_responses(client, settings, cached, result))
    paths = [(endpoint.path, endpoint.params) for endpoint, _ in responses]
    assert len(paths) == 12  # 8 daily + 2 uncached PL history + 2 unique current teams
    assert ("competitions/CL/matches", {"season": "2023"}) not in paths
    assert ("competitions/PL/matches", {"season": "2023"}) in paths
    assert paths[-2:] == [("teams/1", {}), ("teams/2", {})]
    assert len(sleeps) == len(paths) - 1  # includes competition and detail batch boundaries
    assert result.cached == 2


def test_sample_ingest_refuses_plural_leagues_before_any_database_write():
    import uuid
    from datetime import date

    from deng.config import Settings
    from deng.sources.football_data import ingest

    connection = MagicMock()
    with pytest.raises(ValueError, match="CL only"):
        ingest(
            connection,
            date(2026, 10, 2),
            uuid.uuid4(),
            Settings(_env_file=None, football_data_competitions="CL,PL"),
            from_samples=True,
        )
    connection.cursor.assert_not_called()


@pytest.mark.postgres
def test_completed_history_cache_requires_older_season_and_never_accepts_samples(
    connection, run_id
):
    from datetime import date

    from deng.database.raw_loader import RawLoader
    from deng.sources.football_data import SAMPLE_SOURCE, _cached_season_endpoints

    today = date(2026, 10, 2)
    loader = RawLoader(connection)
    for endpoint, params, payload in [
        ("competitions/PL", {}, {"currentSeason": {"startDate": "2026-08-01"}}),
        (
            "competitions/PL/matches",
            {"season": "2023"},
            {"matches": [{"season": {"endDate": "2024-05-30"}}]},
        ),
        (
            "competitions/PL/teams",
            {"season": "2023"},
            {"season": {"endDate": "2024-05-30"}, "teams": []},
        ),
        (
            "competitions/PL/matches",
            {"season": "2026"},
            {"matches": [{"season": {"endDate": "2026-09-01"}}]},
        ),
    ]:
        loader.load(
            run_id=run_id,
            endpoint=endpoint,
            request_params=params,
            request_url="https://example.test",
            payload=payload,
            ingestion_date=today,
        )
    RawLoader(connection, source=SAMPLE_SOURCE).load(
        run_id=run_id,
        endpoint="competitions/PL/matches",
        request_params={"season": "2022"},
        request_url="file://sample",
        payload={"matches": [{"season": {"endDate": "2023-05-30"}}]},
        ingestion_date=today,
    )
    assert _cached_season_endpoints(connection, today) == {
        ("competitions/PL/matches", "2023"),
        ("competitions/PL/teams", "2023"),
    }
    # A backfill date cannot read snapshots that were collected afterwards.
    assert _cached_season_endpoints(connection, date(2026, 10, 1)) == set()
