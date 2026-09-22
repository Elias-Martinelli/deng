"""Weather ingestion: request shape and the contract of the real sample."""

import json
from datetime import date
from pathlib import Path

from deng.ingestion.weather import HOURLY_VARIABLES, ForecastRequest

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
