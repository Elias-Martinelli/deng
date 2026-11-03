"""Failure behaviour for scaled auxiliary-source collection."""

from unittest.mock import Mock

import pytest

from deng.sources.http import ApiError, RetryableApiError, retry_transient


def test_transient_retry_preserves_success_and_uses_backoff(monkeypatch):
    sleep = Mock()
    monkeypatch.setattr("deng.sources.http.time.sleep", sleep)
    fetch = Mock(side_effect=[RetryableApiError(503, "test"), RetryableApiError(0, "test"), "ok"])
    assert retry_transient(fetch) == "ok"
    assert [call.args[0] for call in sleep.call_args_list] == [1, 2]


def test_permanent_failure_is_not_retried():
    fetch = Mock(side_effect=ApiError(403, "test"))
    with pytest.raises(ApiError):
        retry_transient(fetch)
    assert fetch.call_count == 1


def test_transient_retries_are_bounded(monkeypatch):
    monkeypatch.setattr("deng.sources.http.time.sleep", lambda _: None)
    fetch = Mock(side_effect=RetryableApiError(429, "test"))
    with pytest.raises(RetryableApiError):
        retry_transient(fetch)
    assert fetch.call_count == 3


@pytest.mark.postgres
def test_venue_failure_preserves_completed_lookups(connection, run_id, monkeypatch):
    from datetime import date

    from deng.sources import openstreetmap

    requests = [
        openstreetmap.VenueRequest(9001, "Test A", "Ground A", "de", "Europe/Berlin", ""),
        openstreetmap.VenueRequest(9002, "Test B", "Ground B", "de", "Europe/Berlin", ""),
    ]
    monkeypatch.setattr(openstreetmap, "plan", lambda _: requests)

    def fetch(session, request):
        if request.team_id == 9002:
            raise ApiError(403, "test permanent failure")
        return "https://example.test", {"lat": "48", "lon": "11", "type": "stadium"}

    monkeypatch.setattr(openstreetmap, "fetch", fetch)
    with pytest.raises(ApiError):
        openstreetmap.ingest(connection, date(2026, 10, 3), run_id, pause_seconds=0)
    connection.rollback()
    assert connection.execute("SELECT team_id FROM raw.osm_venues").fetchall() == [(9001,)]
