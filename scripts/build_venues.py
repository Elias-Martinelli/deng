"""Build data/reference/venues.csv: stadium coordinates for the league-phase clubs.

Run by hand when the set of clubs changes (once per season), not by the
pipeline:  `make venues`. The output is committed and reviewed like code.

Why not take the location from the football API:
    football-data.org delivers no coordinates, and its `venue` and `address`
    fields are unreliable for this purpose - several names are outdated
    ("Estadio Wanda Metropolitano", "Stadio San Paolo"), and several addresses
    are the club office or training ground rather than the stadium (Bayern:
    Säbener Straße; Roma: Trigoria; Napoli: Castel Volturno, ~40 km from the
    stadium). See docs/evidence/weather.md.

Why OpenStreetMap (Nominatim) and not coordinates typed in from memory:
    every row carries the OSM object it came from, so a reviewer can open
    https://www.openstreetmap.org/<osm_type>/<osm_id> and check it. Nothing is
    invented; what cannot be resolved stays empty with a reason.

Nominatim usage policy: at most one request per second and an identifying
User-Agent - both respected below. 36 requests per season is far inside it.
"""

from __future__ import annotations

import csv
import json
import sys
import time
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
TEAMS_SAMPLE = REPO_ROOT / "data" / "sample" / "football-data" / "teams.json"
OUTPUT = REPO_ROOT / "data" / "reference" / "venues.csv"

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "deng-hslu-student-project/0.1 (elias.martinelli@stud.hslu.ch)"

# Country (as named by football-data.org) -> ISO code for the search filter and
# IANA time zone. Every country here has a single time zone for its clubs.
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
# coordinates, and their matches get weather status VENUE_UNKNOWN.
UNRESOLVABLE: dict[int, str] = {
    1887: (
        "Shakhtar have played their home matches outside Ukraine since 2022; the API "
        "still lists the Metalist stadium in Kharkiv and names no 2026/27 venue"
    ),
    10233: "the API delivers no venue for Sabah FK",
}

# Search terms where the API's venue name does not find the right stadium.
# Only the *query* changes; the API's name stays in the CSV next to OSM's, so the
# discrepancy remains visible. Each entry says why - found in the first run.
QUERY_OVERRIDES: dict[int, tuple[str, str]] = {
    78: ("Estadio Metropolitano Madrid", "API name 'Wanda Metropolitano' is outdated, no OSM hit"),
    81: (
        "Spotify Camp Nou",
        "API name 'Camp Nou' matched a village pitch in Palau-saverdera, ~130 km away",
    ),
    100: (
        "Stadio Olimpico, Roma",
        "'Stadio Olimpico' matched the one in Turin; Nominatim does not return Rome's "
        "stadium object, only the junction named after it ~0.6 km away - irrelevant at "
        "weather-model resolution (1-11 km)",
    ),
    113: (
        "Stadio Diego Armando Maradona",
        "API name 'San Paolo' (renamed 2020) matched Stadio Silvio Piola in Novara",
    ),
    610: (
        "RAMS Park",
        "API name 'Türk Telekom Arena' is outdated; 'Ali Sami Yen' matched the old, "
        "demolished stadium in Zincirlikuyu",
    ),
    613: ("Şükrü Saracoğlu", "API name is a long complex name, no OSM hit"),
    1899: (
        "OPAP Arena",
        "AEK moved from the Olympic stadium to OPAP Arena in 2022; both are in Athens",
    ),
    5720: ("Viking Stadion Stavanger", "API name 'SR-Bank Arena' is a former sponsor name"),
}


# Rows the plausibility check flagged and a person then verified on the map.
MANUALLY_REVIEWED: dict[int, str] = {
    94: "OSM spells the town Vila-real (Valencian); correct stadium",
    113: "API address is the Castel Volturno training centre; stadium is in Naples",
    546: "API address is in neighbouring Avion; stadium is in Lens",
    1899: "OSM address in Greek script: Nea Filadelfeia, Athens",
    2016: "API address is the Pasching training ground; stadium is in Linz",
}


def geocode(query: str, country_code: str) -> dict | None:
    """Return the best Nominatim match, preferring objects tagged as a stadium.

    Network errors and timeouts are retried with back-off (5, 10, 20, 40, 80 s):
    a 36-request run should not be lost to a short connectivity drop.
    """
    attempts = 6
    for attempt in range(attempts):
        try:
            response = requests.get(
                NOMINATIM_URL,
                params={"q": query, "format": "jsonv2", "limit": 5, "countrycodes": country_code},
                headers={"User-Agent": USER_AGENT},
                timeout=20,
            )
            response.raise_for_status()
            break
        except (requests.ConnectionError, requests.Timeout) as exc:
            if attempt == attempts - 1:
                raise
            print(f"  network error ({type(exc).__name__}), retrying", file=sys.stderr)
            time.sleep(5 * 2**attempt)
    results = response.json()
    stadiums = [r for r in results if r.get("type") == "stadium"]
    return (stadiums or results or [None])[0]


def address_matches(api_address: str | None, osm_address: str) -> bool:
    """Plausibility check: does any place word of the API address occur in OSM's?

    Catches a stadium of the same name in another city (Camp Nou in Girona,
    Stadio Olimpico in Turin). It cannot catch a wrong object in the right city,
    and it flags clubs whose API address is a training ground - hence REVIEW,
    not an error: flagged rows are checked by hand.
    """
    if not api_address:
        return False
    words = {w.strip(",.").lower() for w in api_address.split() if len(w.strip(",.")) >= 4}
    return any(word in osm_address.lower() for word in words if not word.isdigit())


def main() -> int:
    """Geocode every club in the teams payload and write the CSV."""
    teams = json.loads(TEAMS_SAMPLE.read_text())["teams"]
    rows = []
    unresolved = 0
    for team in sorted(teams, key=lambda t: t["id"]):
        team_id = team["id"]
        country = team.get("area", {}).get("name")
        code, tz = COUNTRIES.get(country, ("", ""))
        row = {
            "team_id": team_id,
            "team_name": team["name"],
            "api_venue": team.get("venue") or "",
            "osm_name": "",
            "latitude": "",
            "longitude": "",
            "timezone": tz,
            "osm_type": "",
            "osm_id": "",
            "osm_address": "",
            "address_check": "",
            "status": "NOT_AVAILABLE",
            "note": "",
        }
        if team_id in UNRESOLVABLE:
            row["note"] = UNRESOLVABLE[team_id]
        elif not code:
            row["note"] = f"country {country!r} not in COUNTRIES"
        else:
            query, reason = QUERY_OVERRIDES.get(team_id, (team.get("venue") or "", ""))
            hit = geocode(query, code) if query else None
            time.sleep(1.1)  # Nominatim policy: max. 1 request per second
            if hit is None:
                row["note"] = f"no OSM result for {query!r}"
            else:
                row.update(
                    osm_name=hit.get("name") or "",
                    latitude=f"{float(hit['lat']):.5f}",
                    longitude=f"{float(hit['lon']):.5f}",
                    osm_type=hit.get("osm_type", ""),
                    osm_id=hit.get("osm_id", ""),
                    osm_address=hit.get("display_name", ""),
                    address_check=(
                        "OK"
                        if address_matches(team.get("address"), hit.get("display_name", ""))
                        else f"REVIEWED: {MANUALLY_REVIEWED[team_id]}"
                        if team_id in MANUALLY_REVIEWED
                        else "REVIEW"
                    ),
                    status="RESOLVED",
                    note="; ".join(
                        filter(None, [f"query {query!r}", reason, f"OSM type {hit.get('type')}"])
                    ),
                )
        if row["status"] != "RESOLVED":
            unresolved += 1
        where = f"{row['osm_name']} | {row['latitude']},{row['longitude']} | {row['osm_address']}"
        detail = where if row["osm_name"] else row["note"]
        print(f"{row['status']:<13} {team['shortName']:<14} {detail}")
        rows.append(row)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nwrote {OUTPUT.relative_to(REPO_ROOT)}: {len(rows)} clubs, {unresolved} unresolved")
    review = [r for r in rows if r["address_check"] == "REVIEW"]
    for r in review:
        print(f"  REVIEW {r['team_name']}: {r['osm_address'][:90]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
