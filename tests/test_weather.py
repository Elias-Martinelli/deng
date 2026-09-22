"""Weather ingestion: request shape and the contract of the real sample."""

import json
from datetime import date
from pathlib import Path

import pytest

from deng.ingestion.football_data_client import ApiError, RetryableApiError
from deng.ingestion.weather import HOURLY_VARIABLES, ForecastRequest, fetch_forecast

SAMPLE = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "sample"
    / "open-meteo"
    / "forecast_team546_2026-09-21.json"
)


def test_request_asks_for_utc_and_exactly_the_needed_days():
    params = ForecastRequest(546, 50.43, 2.81, date(2026, 10, 13), date(2026, 10, 14)).params()
    assert params["timezone"] == "GMT"
    assert (params["start_date"], params["end_date"]) == ("2026-10-13", "2026-10-14")
    assert params["hourly"].split(",") == list(HOURLY_VARIABLES)


def test_real_sample_is_columnar_utc_and_aligned():
    """What the staging SQL relies on, checked against a real answer (21 Sep 2026)."""
    payload = json.loads(SAMPLE.read_text())
    hourly = payload["hourly"]
    assert payload["timezone"] == "GMT"
    assert set(HOURLY_VARIABLES) <= set(hourly)
    lengths = {len(values) for values in hourly.values()}
    assert lengths == {16 * 24}, "every variable must align with `time`, 16 days hourly"
    assert hourly["time"][0].endswith("T00:00")


def test_real_sample_snaps_to_the_model_grid():
    # Requested 50.43282, 2.81499 - the API answers for its grid cell. Metre
    # precision of the stadium coordinates is therefore irrelevant.
    payload = json.loads(SAMPLE.read_text())
    assert abs(payload["latitude"] - 50.43282) < 0.1
    assert payload["latitude"] != 50.43282


class _Response:
    def __init__(self, status, body):
        self.status_code, self._body, self.url, self.text = status, body, "u", str(body)

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


class _Session:
    def __init__(self, response):
        self.response = response

    def get(self, url, params, timeout):
        return self.response


REQUEST = ForecastRequest(546, 50.43, 2.81, date(2026, 10, 13), date(2026, 10, 14))


def test_a_200_that_is_not_json_is_a_permanent_error():
    with pytest.raises(ApiError) as caught:
        fetch_forecast(_Session(_Response(200, ValueError("no json"))), "u", REQUEST)
    assert type(caught.value) is ApiError


def test_rate_limit_and_server_errors_are_retryable():
    for status in (429, 503):
        with pytest.raises(RetryableApiError):
            fetch_forecast(_Session(_Response(status, {})), "u", REQUEST)
