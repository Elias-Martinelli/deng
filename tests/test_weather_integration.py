"""Weather against PostgreSQL: statuses, kick-off hour, leakage guard, idempotency.

No network: a fake session answers with a payload built exactly like the real
Open-Meteo answer (see data/sample/open-meteo/), for whatever dates are asked.
"""

from datetime import date, datetime, timedelta

import pytest

from deng.database import RawLoader
from deng.sources import openstreetmap
from deng.sources.football_data import ApiError
from deng.sources.open_meteo import ingest_weather
from deng.transformation import (
    WEATHER_COUNTED_TABLES,
    WEATHER_TRANSFORMATION_ORDER,
    run_transformations,
)

pytestmark = pytest.mark.postgres

FOOTBALL_DATE = date(2026, 9, 20)
# Matchday 2 is on 13/14 October: inside the horizon of 1 October (+15 days).
WEATHER_DATE = date(2026, 10, 1)


def fake_payload(start: str, end: str) -> dict:
    """Same shape as the real answer; temperature encodes the hour for checking."""
    first = datetime.fromisoformat(start)
    hours = int((datetime.fromisoformat(end) - first).total_seconds() // 3600) + 24
    times = [(first + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M") for h in range(hours)]
    return {
        "latitude": 50.44,
        "longitude": 2.813,
        "timezone": "GMT",
        "hourly": {
            "time": times,
            "temperature_2m": [float(int(t[11:13])) for t in times],  # = hour of day
            "precipitation": [0.2] * hours,
            "precipitation_probability": [40] * hours,
            "wind_speed_10m": [12.5] * hours,
            "weather_code": [3] * hours,
        },
    }


class FakeResponse:
    def __init__(self, status, payload, url):
        self.status_code, self._payload, self.url, self.text = status, payload, url, str(payload)

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, status=200):
        self.status = status
        self.calls = 0

    def get(self, url, params, timeout):
        self.calls += 1
        if self.status != 200:
            return FakeResponse(self.status, {"error": True, "reason": "out of range"}, url)
        return FakeResponse(200, fake_payload(params["start_date"], params["end_date"]), url)


@pytest.fixture
def football(connection, run_id, all_samples):
    loader = RawLoader(connection)
    for endpoint, payload in all_samples.items():
        loader.load(
            run_id=run_id,
            endpoint=endpoint,
            request_params={},
            request_url=f"https://api.football-data.org/v4/{endpoint}",
            payload=payload,
            ingestion_date=FOOTBALL_DATE,
        )
    connection.commit()
    run_transformations(connection, FOOTBALL_DATE)
    # The stadium coordinates come from the OpenStreetMap source, which stores
    # the committed answers in the raw zone - the weather plan reads them there.
    openstreetmap.ingest(connection, FOOTBALL_DATE, run_id, from_samples=True)
    with connection.cursor() as cursor:
        cursor.execute(
            "TRUNCATE raw.open_meteo, staging.weather_forecast, curated.fact_match_weather"
        )
    connection.commit()


def weather_run(connection, run_id, session, logical_date=WEATHER_DATE):
    result = ingest_weather(
        connection,
        logical_date,
        run_id,
        "https://api.example/v1/forecast",
        session=session,
        today=logical_date,
    )
    run_transformations(
        connection,
        logical_date,
        order=WEATHER_TRANSFORMATION_ORDER,
        counted=WEATHER_COUNTED_TABLES,
    )
    return result


def rows(connection, sql, params=()):
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchall()


def test_every_match_gets_exactly_one_status(connection, run_id, football):
    weather_run(connection, run_id, FakeSession())
    statuses = dict(
        rows(
            connection, "SELECT weather_status, count(*) FROM curated.fact_match_weather GROUP BY 1"
        )
    )
    assert sum(statuses.values()) == 144
    # matchday 2 at resolved venues; Shakhtar/Sabah home games have no venue
    assert statuses["AVAILABLE"] > 0
    assert statuses["NOT_CAPTURED"] == 18  # matchday 1, played before we fetched
    assert statuses["NOT_YET_AVAILABLE"] > 0
    assert "MISSING" not in statuses


def test_the_value_is_the_kickoff_hour_in_utc(connection, run_id, football):
    weather_run(connection, run_id, FakeSession())
    mismatches = rows(
        connection,
        """
        SELECT w.match_id FROM curated.fact_match_weather w
          JOIN curated.fact_match m USING (match_id)
         WHERE w.weather_status = 'AVAILABLE'
           AND w.temperature_c <> extract(hour FROM m.utc_kickoff AT TIME ZONE 'UTC')
        """,
    )
    assert mismatches == []


def test_one_request_per_venue_not_per_match(connection, run_id, football):
    session = FakeSession()
    result = weather_run(connection, run_id, session)
    venues = rows(
        connection,
        "SELECT count(DISTINCT venue_team_id) FROM curated.fact_match_weather "
        "WHERE weather_status = 'AVAILABLE'",
    )[0][0]
    assert session.calls == result.planned == venues


def test_a_forecast_fetched_after_kickoff_is_never_used(connection, run_id, football):
    weather_run(connection, run_id, FakeSession())
    with connection.cursor() as cursor:
        # Pretend every forecast was fetched long after the matches.
        cursor.execute("UPDATE raw.open_meteo SET ingested_at = '2027-06-01'")
        cursor.execute("TRUNCATE staging.weather_forecast, curated.fact_match_weather")
    connection.commit()
    run_transformations(
        connection,
        WEATHER_DATE,
        order=WEATHER_TRANSFORMATION_ORDER,
        counted=WEATHER_COUNTED_TABLES,
    )
    available = rows(
        connection,
        "SELECT count(*) FROM curated.fact_match_weather WHERE weather_status = 'AVAILABLE'",
    )[0][0]
    missing = rows(
        connection,
        "SELECT count(*) FROM curated.fact_match_weather WHERE weather_status = 'MISSING'",
    )[0][0]
    assert available == 0
    assert missing > 0, "inside the horizon without a usable forecast is a visible gap"


def test_rerun_same_day_does_not_duplicate(connection, run_id, football):
    weather_run(connection, run_id, FakeSession())
    first = rows(connection, "SELECT count(*) FROM raw.open_meteo")[0][0]
    weather_run(connection, run_id, FakeSession())
    assert rows(connection, "SELECT count(*) FROM raw.open_meteo")[0][0] == first


def test_out_of_range_is_a_permanent_error(connection, run_id, football):
    with pytest.raises(ApiError) as caught:
        weather_run(connection, run_id, FakeSession(status=400))
    assert caught.value.status_code == 400
    assert type(caught.value) is ApiError, "400 must not be retryable"


def test_no_forecast_for_a_past_logical_date(connection, run_id, football):
    session = FakeSession()
    result = ingest_weather(
        connection,
        WEATHER_DATE,
        run_id,
        "https://api.example/v1/forecast",
        session=session,
        today=WEATHER_DATE + timedelta(days=1),
    )
    assert session.calls == 0
    assert "not today" in result.skipped_reason
