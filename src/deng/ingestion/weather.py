"""Weather forecasts from Open-Meteo for upcoming matches.

What is fetched, and why this way:

* **Only matches inside the forecast horizon.** Open-Meteo forecasts 16 days
  (today + 15). A request beyond that is answered with HTTP 400 "out of allowed
  range" (measured 21 Sep 2026) - so we never ask; those matches get the state
  NOT_YET_AVAILABLE in the curated layer instead.
* **One request per venue, not per match.** A venue's matches inside the
  horizon are covered by one date range; with 18 matches per matchday that is at
  most ~18 requests a day against a limit of 10 000.
* **UTC throughout** (`timezone=GMT`). The kick-off is stored in UTC, so the
  forecast hour is found by truncating it - no time-zone conversion that could
  be off by an hour twice a year.
* **Only for today.** A forecast is only a forecast if it was fetched before the
  match. For a past logical date the API would answer with analysis data - what
  the weather turned out to be, not what was predicted - so a backfill does not
  fetch weather at all. That is stated in the output, not silently skipped.

Venue coordinates come from `data/reference/venues.csv`, loaded into
`staging.venues` at the start of every weather run.
"""

from __future__ import annotations

import csv
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import psycopg
import requests
from psycopg.types.json import Jsonb

from deng.database.raw_loader import hash_payload
from deng.ingestion.football_data_client import ApiError, RetryableApiError

logger = logging.getLogger(__name__)

ENDPOINT = "v1/forecast"
HORIZON_DAYS = 16  # today plus 15 days, as the API allows
HOURLY_VARIABLES = (
    "temperature_2m",
    "precipitation",
    "precipitation_probability",
    "wind_speed_10m",
    "weather_code",
)
# The pipeline's "today" is the schedule's calendar day, not the container's UTC day.
PIPELINE_TZ = ZoneInfo("Europe/Zurich")

REPO_ROOT = Path(__file__).resolve().parents[3]
VENUES_FILE = Path("data") / "reference" / "venues.csv"
SAMPLE_DIR = Path("data") / "sample" / "open-meteo"


@dataclass(frozen=True)
class ForecastRequest:
    """One forecast request: one venue, the date range its matches need."""

    venue_team_id: int
    latitude: float
    longitude: float
    start_date: date
    end_date: date

    def params(self) -> dict[str, Any]:
        """Query parameters exactly as sent to the API."""
        return {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "hourly": ",".join(HOURLY_VARIABLES),
            "timezone": "GMT",
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
        }


@dataclass
class WeatherResult:
    """What one weather ingestion did."""

    planned: int = 0
    stored: list[int] = field(default_factory=list)
    skipped_reason: str | None = None

    @property
    def summary(self) -> str:
        """One line for logs and CLI output."""
        if self.skipped_reason:
            return f"skipped: {self.skipped_reason}"
        return f"{len(self.stored)}/{self.planned} venue forecast(s) stored"


def pipeline_today() -> date:
    """The calendar day the pipeline considers 'today'."""
    return datetime.now(PIPELINE_TZ).date()


def _find(relative: Path) -> Path:
    candidate = Path.cwd() / relative
    return candidate if candidate.exists() else REPO_ROOT / relative


def load_venues(connection: psycopg.Connection, path: Path | None = None) -> int:
    """Upsert data/reference/venues.csv into staging.venues. Returns the row count."""
    path = path or _find(VENUES_FILE)
    with path.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    def number(value: str) -> float | None:
        return float(value) if value else None

    with connection.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO staging.venues AS v
                (team_id, team_name, api_venue, osm_name, latitude, longitude, timezone,
                 osm_type, osm_id, status, note)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (team_id) DO UPDATE SET
                team_name = EXCLUDED.team_name, api_venue = EXCLUDED.api_venue,
                osm_name = EXCLUDED.osm_name, latitude = EXCLUDED.latitude,
                longitude = EXCLUDED.longitude, timezone = EXCLUDED.timezone,
                osm_type = EXCLUDED.osm_type, osm_id = EXCLUDED.osm_id,
                status = EXCLUDED.status, note = EXCLUDED.note
            """,
            [
                (
                    int(r["team_id"]),
                    r["team_name"],
                    r["api_venue"] or None,
                    r["osm_name"] or None,
                    number(r["latitude"]),
                    number(r["longitude"]),
                    r["timezone"] or None,
                    r["osm_type"] or None,
                    int(r["osm_id"]) if r["osm_id"] else None,
                    r["status"],
                    r["note"] or None,
                )
                for r in rows
            ],
        )
    return len(rows)


def plan_requests(connection: psycopg.Connection, logical_date: date) -> list[ForecastRequest]:
    """One request per venue that hosts an unfinished match inside the horizon."""
    last_day = logical_date + timedelta(days=HORIZON_DAYS - 1)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT m.home_team_id, v.latitude, v.longitude,
                   min(m.match_date), max(m.match_date)
              FROM curated.fact_match m
              JOIN staging.venues v ON v.team_id = m.home_team_id AND v.status = 'RESOLVED'
             WHERE NOT m.is_finished
               AND m.match_date BETWEEN %s AND %s
             GROUP BY m.home_team_id, v.latitude, v.longitude
             ORDER BY m.home_team_id
            """,
            (logical_date, last_day),
        )
        return [
            ForecastRequest(int(team), float(lat), float(lon), start, end)
            for team, lat, lon, start, end in cursor.fetchall()
        ]


def fetch_forecast(session: requests.Session, base_url: str, request: ForecastRequest):
    """GET one forecast. Classifies errors like the football client does.

    Raises:
        RetryableApiError: HTTP 429, 5xx or a network failure - worth retrying.
        ApiError: any other error, e.g. 400 for a date outside the horizon.
    """
    try:
        response = session.get(base_url, params=request.params(), timeout=30)
    except requests.RequestException as exc:
        raise RetryableApiError(0, f"network error: {exc}") from exc
    if response.status_code == 429 or response.status_code >= 500:
        raise RetryableApiError(response.status_code, response.text[:200])
    if response.status_code != 200:
        raise ApiError(response.status_code, response.text[:200])
    payload = response.json()
    if payload.get("error") or "hourly" not in payload:
        raise ApiError(response.status_code, f"unexpected payload: {str(payload)[:200]}")
    return response.url, payload


def read_sample(request: ForecastRequest) -> tuple[str, dict[str, Any]] | None:
    """The committed sample for this venue, if there is one (offline mode)."""
    directory = _find(SAMPLE_DIR)
    matches = sorted(directory.glob(f"forecast_team{request.venue_team_id}_*.json"))
    if not matches:
        return None
    path = matches[-1]
    return f"file://{path}", json.loads(path.read_text())


def store(
    connection: psycopg.Connection,
    request: ForecastRequest,
    url: str,
    payload: dict[str, Any],
    ingestion_date: date,
    run_id: uuid.UUID,
) -> None:
    """Idempotent upsert: one row per venue per ingestion date."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO raw.open_meteo AS r
                (endpoint, venue_team_id, request_params, request_url, ingestion_date,
                 run_id, payload, payload_hash)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (source, endpoint, venue_team_id, ingestion_date) DO UPDATE SET
                request_params = EXCLUDED.request_params, request_url = EXCLUDED.request_url,
                ingested_at = now(), run_id = EXCLUDED.run_id,
                payload = EXCLUDED.payload, payload_hash = EXCLUDED.payload_hash
            """,
            (
                ENDPOINT,
                request.venue_team_id,
                Jsonb(request.params()),
                url,
                ingestion_date,
                run_id,
                Jsonb(payload),
                hash_payload(payload),
            ),
        )


def ingest_weather(
    connection: psycopg.Connection,
    logical_date: date,
    run_id: uuid.UUID,
    base_url: str,
    from_samples: bool = False,
    session: requests.Session | None = None,
    today: date | None = None,
) -> WeatherResult:
    """Load the venues, then fetch and store today's forecasts.

    Args:
        connection: Open connection; committed at the end.
        logical_date: The run's date. Must be today unless `from_samples`.
        run_id: Run the raw rows belong to.
        base_url: Open-Meteo forecast endpoint.
        from_samples: Replay committed samples instead of calling the API.
        session: HTTP session (tests pass a fake one).
        today: Override for "today" (tests).
    """
    result = WeatherResult()
    load_venues(connection)
    connection.commit()

    today = today or pipeline_today()
    if not from_samples and logical_date != today:
        result.skipped_reason = (
            f"logical date {logical_date} is not today ({today}); a forecast fetched now "
            "would not be what was known then"
        )
        logger.info("weather %s", result.summary)
        return result

    requests_ = plan_requests(connection, logical_date)
    result.planned = len(requests_)
    session = session or requests.Session()
    for request in requests_:
        if from_samples:
            sample = read_sample(request)
            if sample is None:
                logger.info("no sample forecast for venue %s", request.venue_team_id)
                continue
            url, payload = sample
        else:
            url, payload = fetch_forecast(session, base_url, request)
        store(connection, request, url, payload, logical_date, run_id)
        result.stored.append(request.venue_team_id)
    connection.commit()
    logger.info("weather %s", result.summary)
    return result
