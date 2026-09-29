"""Source: stadium coordinates from OpenStreetMap (Nominatim).

Why this source exists: the football API delivers no coordinates, and the
weather API needs them. Its venue names are also partly outdated, so searching
blindly puts clubs in the wrong city - the first run put Napoli in Novara,
Barcelona in a village near Girona and Roma in Turin. The corrected search
terms and the human verdicts from that review live in this file, next to the
code that uses them, and the answer is stored unchanged in the raw zone.

Like every source in this package, the module answers two questions:

    plan(connection)   what should I fetch?
    fetch(request)     how do I fetch one of them?

Cadence: once per club, not daily. Stadiums do not move, so plan() returns only
clubs that have no stored answer yet - on a normal day it returns nothing.

Nominatim's usage policy: at most one request per second and an identifying
User-Agent. Both are respected below; 36 clubs once a season is far inside it.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import psycopg
import requests
from psycopg.types.json import Jsonb

from deng.database.raw_loader import hash_payload
from deng.files import project_file
from deng.ingestion import raw_reads
from deng.sources.http import ApiError, RetryableApiError

logger = logging.getLogger(__name__)

SOURCE = "openstreetmap.org"
ENDPOINT = "search"
BASE_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "deng-hslu-student-project/0.1 (elias.martinelli@stud.hslu.ch)"
PAUSE_SECONDS = 1.1  # Nominatim policy: at most one request per second
SAMPLE_DIR = Path("data") / "sample" / "openstreetmap"

# Country (as football-data.org names it) -> ISO code for the search filter.
# Every country here has a single time zone for its clubs.
COUNTRIES: dict[str, tuple[str, str]] = {
    "Austria": ("at", "Europe/Vienna"),
    "Azerbaijan": ("az", "Asia/Baku"),
    "Belgium": ("be", "Europe/Brussels"),
    "Czech Republic": ("cz", "Europe/Prague"),
    "England": ("gb", "Europe/London"),
    "France": ("fr", "Europe/Paris"),
    "Germany": ("de", "Europe/Berlin"),
    "Greece": ("gr", "Europe/Athens"),
    "Italy": ("it", "Europe/Rome"),
    "Netherlands": ("nl", "Europe/Amsterdam"),
    "Norway": ("no", "Europe/Oslo"),
    "Portugal": ("pt", "Europe/Lisbon"),
    "Slovakia": ("sk", "Europe/Bratislava"),
    "Spain": ("es", "Europe/Madrid"),
    "Turkey": ("tr", "Europe/Istanbul"),
    "Ukraine": ("ua", "Europe/Kyiv"),
}

# Clubs whose home venue cannot be taken from the source at all. They get no
# coordinates, and their matches get the weather status VENUE_UNKNOWN.
UNRESOLVABLE: dict[int, str] = {
    1887: (
        "Shakhtar have played their home matches outside Ukraine since 2022; the API "
        "still lists the Metalist stadium in Kharkiv and names no 2026/27 venue"
    ),
    10233: "the API delivers no venue for Sabah FK",
}

# Search terms that replace the API's venue name, each with the reason found in
# the first run. Only the question changes - the answer is stored as received.
QUERY_OVERRIDES: dict[int, tuple[str, str]] = {
    78: ("Estadio Metropolitano Madrid", "API name 'Wanda Metropolitano' is outdated, no hit"),
    81: ("Spotify Camp Nou", "API name 'Camp Nou' matched a village pitch near Girona"),
    100: (
        "Stadio Olimpico, Roma",
        "'Stadio Olimpico' matched the one in Turin; Nominatim returns only the junction "
        "next to Rome's stadium, 0.6 km away - irrelevant at weather-model resolution",
    ),
    113: ("Stadio Diego Armando Maradona", "API name 'San Paolo' matched a stadium in Novara"),
    610: ("RAMS Park", "API name is outdated; 'Ali Sami Yen' matched the demolished old ground"),
    613: ("Şükrü Saracoğlu", "the API name is a long complex name, no hit"),
    1899: ("OPAP Arena", "AEK moved from the Olympic stadium to OPAP Arena in 2022"),
    5720: ("Viking Stadion Stavanger", "API name 'SR-Bank Arena' is a former sponsor name"),
}

# Rows the plausibility check flagged and a person then verified on the map.
MANUALLY_REVIEWED: dict[int, str] = {
    94: "OSM spells the town Vila-real (Valencian); correct stadium",
    113: "the API address is the Castel Volturno training centre; the stadium is in Naples",
    546: "the API address is in neighbouring Avion; the stadium is in Lens",
    1899: "OSM address in Greek script: Nea Filadelfeia, Athens",
    2016: "the API address is the Pasching training ground; the stadium is in Linz",
}


@dataclass(frozen=True)
class VenueRequest:
    """One stadium to look up."""

    team_id: int
    team_name: str
    query: str
    country_code: str
    timezone: str
    note: str

    def params(self) -> dict[str, Any]:
        """Query parameters exactly as sent to Nominatim."""
        return {
            "q": self.query,
            "format": "jsonv2",
            "limit": 5,
            "countrycodes": self.country_code,
        }


def plan(connection: psycopg.Connection) -> list[VenueRequest]:
    """Clubs whose stadium is not stored yet (usually none after the first run)."""
    stored = _stored_team_ids(connection)
    requests_: list[VenueRequest] = []
    for club in raw_reads.clubs(connection):
        if club.team_id in stored:
            continue
        country_code, timezone = COUNTRIES.get(club.country or "", ("", ""))
        query, note = QUERY_OVERRIDES.get(club.team_id, (club.venue or "", ""))
        requests_.append(
            VenueRequest(
                team_id=club.team_id,
                team_name=club.name,
                query=query,
                country_code=country_code,
                timezone=timezone,
                note=note,
            )
        )
    return requests_


def fetch(session: requests.Session, request: VenueRequest, base_url: str = BASE_URL):
    """Look up one stadium and return (url, best answer or None).

    Prefers an object tagged as a stadium over any other hit.

    Raises:
        RetryableApiError: network trouble or HTTP 429/5xx - worth retrying.
        ApiError: any other HTTP error.
    """
    try:
        response = session.get(
            base_url,
            params=request.params(),
            headers={"User-Agent": USER_AGENT},
            timeout=20,
        )
    except requests.RequestException as exc:
        raise RetryableApiError(0, f"network error: {exc}") from exc
    if response.status_code == 429 or response.status_code >= 500:
        raise RetryableApiError(response.status_code, response.text[:200])
    if response.status_code != 200:
        raise ApiError(response.status_code, response.text[:200])
    results = response.json()
    stadiums = [r for r in results if r.get("type") == "stadium"]
    best = (stadiums or results or [None])[0]
    return response.url, best


def read_sample(request: VenueRequest) -> tuple[str, dict[str, Any] | None] | None:
    """The committed answer for this club, for runs without network access."""
    path = project_file(SAMPLE_DIR / f"venue_{request.team_id}.json")
    if not path.exists():
        return None
    payload = json.loads(path.read_text())
    return f"file://{path}", (payload or None)


def store(
    connection: psycopg.Connection,
    request: VenueRequest,
    url: str,
    payload: dict[str, Any] | None,
    ingestion_date: date,
    run_id,
    review_status: str,
    review_note: str,
) -> None:
    """Write one answer into the raw zone; a rerun on the same day overwrites it."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO raw.osm_venues
                (endpoint, team_id, request_params, request_url, ingestion_date, run_id,
                 payload, payload_hash, review_status, review_note, timezone)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (source, team_id, ingestion_date) DO UPDATE SET
                request_params = EXCLUDED.request_params,
                request_url = EXCLUDED.request_url,
                ingested_at = now(),
                run_id = EXCLUDED.run_id,
                payload = EXCLUDED.payload,
                payload_hash = EXCLUDED.payload_hash,
                review_status = EXCLUDED.review_status,
                review_note = EXCLUDED.review_note,
                timezone = EXCLUDED.timezone
            """,
            (
                ENDPOINT,
                request.team_id,
                Jsonb(request.params()),
                url,
                ingestion_date,
                run_id,
                Jsonb(payload or {}),
                hash_payload(payload or {}),
                review_status,
                review_note,
                request.timezone or None,
            ),
        )


def ingest(
    connection: psycopg.Connection,
    ingestion_date: date,
    run_id,
    from_samples: bool = False,
    session: requests.Session | None = None,
    pause_seconds: float = PAUSE_SECONDS,
) -> int:
    """Fetch and store every stadium that is missing. Returns how many were stored."""
    session = session or requests.Session()
    stored = 0
    for index, request in enumerate(plan(connection)):
        status, note, payload, url = _resolve(request, session, from_samples, index, pause_seconds)
        store(connection, request, url, payload, ingestion_date, run_id, status, note)
        stored += 1
        logger.info("venue %s (%s): %s", request.team_id, request.team_name, status)
    connection.commit()
    return stored


def _resolve(
    request: VenueRequest,
    session: requests.Session,
    from_samples: bool,
    index: int,
    pause_seconds: float,
) -> tuple[str, str, dict[str, Any] | None, str]:
    """Decide what to store for one club: the answer, or the reason there is none."""
    if request.team_id in UNRESOLVABLE:
        return "NOT_AVAILABLE", UNRESOLVABLE[request.team_id], None, "not-asked"
    if not request.query or not request.country_code:
        return (
            "NOT_AVAILABLE",
            "no venue name or unknown country in the football payload",
            None,
            ("not-asked"),
        )

    if from_samples:
        sample = read_sample(request)
        if sample is None:
            return "NOT_AVAILABLE", "no committed sample for this club", None, "no-sample"
        url, payload = sample
    else:
        if index:
            time.sleep(pause_seconds)
        url, payload = fetch(session, request)

    if payload is None:
        return "NOT_AVAILABLE", f"no OpenStreetMap result for {request.query!r}", None, url
    note = "; ".join(filter(None, [request.note, MANUALLY_REVIEWED.get(request.team_id, "")]))
    return "RESOLVED", note, payload, url


def _stored_team_ids(connection: psycopg.Connection) -> set[int]:
    with connection.cursor() as cursor:
        cursor.execute("SELECT DISTINCT team_id FROM raw.osm_venues")
        return {int(row[0]) for row in cursor.fetchall()}
