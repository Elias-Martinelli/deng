"""Capture public FootballDatabase world rankings with conservative team matching.

Source: https://footballdatabase.com/ranking/world/1 (CC BY-SA 4.0).
The displayed games-through date is not a publication timestamp. First capture
is retained separately; current rankings are never backdated into past matches.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser

import requests
from psycopg.types.json import Jsonb

from deng.clock import pipeline_today
from deng.files import project_file
from deng.sources.http import ApiError, RetryableApiError, retry_transient

BASE_URL = "https://footballdatabase.com/ranking/world"


class RankingParser(HTMLParser):
    """Read the provider's table without depending on a rendering browser."""

    def __init__(self):
        """Initialize independent page parsing state."""
        super().__init__(convert_charrefs=True)
        self.rows = []
        self.date_text = ""
        self.in_date = False
        self.cells = None
        self.cell = None
        self.link_kind = None
        self.club = ""
        self.country = ""
        self.slug = ""
        self.last_page = 1

    def handle_starttag(self, tag, attrs):
        """Track date, table cells and club/country links."""
        attrs = dict(attrs)
        if tag == "span" and attrs.get("itemprop") == "dateModified":
            self.in_date = True
        if tag == "tr":
            self.cells, self.club, self.country, self.slug = [], "", "", ""
        if tag == "td" and self.cells is not None:
            self.cell = ""
        if tag == "a":
            href = attrs.get("href", "")
            page = re.fullmatch(r"/ranking/world/(\d+)", href)
            if page:
                self.last_page = max(self.last_page, int(page.group(1)))
            if self.cell is not None and href.startswith("/clubs-ranking/"):
                self.slug = href.removeprefix("/clubs-ranking/")
                self.link_kind = "club"
            elif self.cell is not None and href.startswith("/ranking/"):
                self.link_kind = "country"

    def handle_data(self, text):
        """Accumulate visible table text, excluding icons and attributes."""
        if self.in_date:
            self.date_text += text
        if self.cell is not None:
            self.cell += text
            if self.link_kind == "club":
                self.club += text
            elif self.link_kind == "country":
                self.country += text

    def handle_endtag(self, tag):
        """Finish cells and reject structurally invalid ranking rows."""
        if tag == "span":
            self.in_date = False
        if tag == "a":
            self.link_kind = None
        if tag == "td" and self.cell is not None:
            self.cells.append(self.cell.strip())
            self.cell = None
        if tag == "tr" and self.cells is not None:
            if self.slug:
                if len(self.cells) < 3 or not self.club.strip() or not self.country.strip():
                    raise ValueError("incomplete ranking row")
                self.rows.append(
                    {
                        "club_slug": self.slug,
                        "club_name": self.club.strip(),
                        "country": self.country.strip(),
                        "world_rank": int(self.cells[0].replace(",", "")),
                        "rating_points": int(self.cells[2].replace(",", "")),
                    }
                )
            self.cells = None


def parse_page(html: str, page: int):
    """Validate the snapshot date, page range, positive points and unique clubs."""
    parser = RankingParser()
    parser.feed(html)
    ranking_date = datetime.strptime(parser.date_text.strip(), "%d %B %Y").date()
    rows = parser.rows
    if not rows or len(rows) > 50:
        raise ValueError("expected 1-50 ranking rows; provider layout may have changed")
    expected = list(range((page - 1) * 50 + 1, (page - 1) * 50 + len(rows) + 1))
    if [r["world_rank"] for r in rows] != expected:
        raise ValueError("ranking page range is inconsistent")
    if len({r["club_slug"] for r in rows}) != len(rows):
        raise ValueError("duplicate club in ranking page")
    if any(r["rating_points"] <= 0 for r in rows):
        raise ValueError("rating points must be positive")
    return ranking_date, rows, parser.last_page


def normalise(value):
    """Conservative exact normalized token sets; no fuzzy/substring matching."""
    value = value.lower().translate(str.maketrans({"ø": "o", "ß": "ss", "ł": "l"}))
    value = unicodedata.normalize("NFKD", value)
    value = "".join(c for c in value if not unicodedata.combining(c))
    tokens = re.findall(r"[a-z0-9]+", value)
    ignored = {"fc", "cf", "ac", "afc", "sc", "ssc", "sv", "club", "clube", "de"}
    return frozenset(t for t in tokens if t not in ignored)


def resolve_teams(clubs, rankings, reviewed, aliases):
    """Return only reviewed identities or unique exact names within one country."""
    by_slug = {r["club_slug"]: r for r in rankings}
    by_team = {int(c["team_id"]): c for c in clubs}
    if len(set(reviewed.values())) != len(reviewed):
        raise ValueError("reviewed club slug must map to one team only")
    mappings = {}
    claimed = set()
    for team_id, slug in reviewed.items():
        if team_id not in by_team or slug not in by_slug:
            continue
        mappings[team_id] = (slug, "REVIEWED")
        claimed.add(slug)
    candidates = {}
    for club in clubs:
        team_id = int(club["team_id"])
        if team_id in mappings:
            continue
        names = [club["name"], club.get("short_name")] + aliases.get(team_id, [])
        names = {normalise(n) for n in names if n}
        country = normalise(club.get("country") or "")
        matches = [
            r["club_slug"]
            for r in rankings
            if country
            and normalise(r["country"]) == country
            and normalise(r["club_name"]) in names
            and r["club_slug"] not in claimed
        ]
        if len(matches) == 1:
            candidates[team_id] = matches[0]
    for team_id, slug in candidates.items():
        if list(candidates.values()).count(slug) == 1:
            mappings[team_id] = (slug, "EXACT_COUNTRY")
    return mappings


def fetch_page(session, page):
    """Fetch one public page with bounded transient retries; no access bypass."""
    url = f"{BASE_URL}/{page}"
    try:
        response = session.get(url, timeout=30)
    except requests.RequestException as exc:
        raise RetryableApiError(0, f"ranking network error: {type(exc).__name__}") from exc
    if response.status_code == 429 or response.status_code >= 500:
        raise RetryableApiError(response.status_code, "ranking source temporarily unavailable")
    if response.status_code != 200:
        raise ApiError(response.status_code, "ranking page unavailable")
    return response.text


@dataclass
class RankingResult:
    """Counts for the source log, including unmatched project teams."""

    pages: int = 0
    rows: int = 0
    matched: int = 0
    teams: int = 0
    reason: str = ""

    @property
    def summary(self):
        """Describe source capture and identity coverage."""
        if self.reason:
            return self.reason
        return (
            f"{self.pages} pages, {self.rows} ranked clubs, "
            f"{self.matched}/{self.teams} project teams mapped"
        )


def ingest(connection, logical_date, run_id, settings, from_samples=False, session=None):
    """Capture daily pages and map clubs from raw identities; cached same-day reruns."""
    if from_samples or not settings.footballdatabase_enabled:
        return RankingResult(reason="ranking skipped: offline sample mode or disabled")
    if logical_date != pipeline_today():
        return RankingResult(reason="ranking skipped: current page cannot backfill a past date")
    session = session or requests.Session()
    today = pipeline_today()
    all_rows = []
    current_date = None
    last_page = settings.footballdatabase_max_pages
    pages = 0
    for page in range(1, settings.footballdatabase_max_pages + 1):
        if page > last_page:
            break
        cached = connection.execute(
            "SELECT html FROM raw.footballdatabase_pages WHERE page=%s AND last_checked_date=%s "
            "ORDER BY observed_at DESC, raw_id DESC LIMIT 1",
            (page, logical_date),
        ).fetchone()
        if cached:
            html = cached[0]
        else:
            if page > 1:
                time.sleep(1)
            html = retry_transient(lambda page=page: fetch_page(session, page))
        try:
            ranking_date, rows, last_page = parse_page(html, page)
            if ranking_date > today:
                raise ValueError("ranking date is in the future")
            if current_date is not None and ranking_date != current_date:
                raise ValueError("ranking updated during pagination; retry next day")
        except ValueError as exc:
            raise ApiError(200, f"ranking validation failed: {exc}") from exc
        current_date = ranking_date
        digest = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()
        connection.execute(
            "INSERT INTO raw.footballdatabase_pages "
            "(page, ranking_date, ingestion_date, last_checked_date, request_url, "
            "payload_hash, html, payload, run_id) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (source,page,ranking_date,payload_hash) DO UPDATE "
            "SET last_checked_date=EXCLUDED.ingestion_date",
            (
                page,
                ranking_date,
                logical_date,
                logical_date,
                f"{BASE_URL}/{page}",
                digest,
                html,
                Jsonb(rows),
                run_id,
            ),
        )
        # Each validated page is preserved. A failed later page can resume safely.
        connection.commit()
        all_rows.extend(rows)
        pages += 1
    from psycopg.rows import dict_row

    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute("SELECT team_id,name,short_name,country FROM raw.team_catalog")
        clubs = cursor.fetchall()
    with project_file("data/reference/footballdatabase_team_ids.csv").open() as handle:
        entries = list(csv.DictReader(handle))
        reviewed = {int(r["team_id"]): r["club_slug"].strip() for r in entries}
        if len(reviewed) != len(entries):
            raise ApiError(0, "duplicate team ID in ranking crosswalk")
    aliases = {}
    with project_file("data/reference/bookmaker_team_aliases.csv").open() as handle:
        for row in csv.DictReader(handle):
            aliases.setdefault(int(row["team_id"]), []).append(row["alias"])
    try:
        mappings = resolve_teams(clubs, all_rows, reviewed, aliases)
    except ValueError as exc:
        raise ApiError(0, f"ranking mapping validation failed: {exc}") from exc
    for team_id, (slug, method) in mappings.items():
        connection.execute(
            "INSERT INTO raw.footballdatabase_team_map(team_id,club_slug,method) VALUES (%s,%s,%s) "
            "ON CONFLICT(team_id) DO UPDATE SET club_slug=EXCLUDED.club_slug, "
            "method=EXCLUDED.method, updated_at=clock_timestamp()",
            (team_id, slug, method),
        )
    connection.commit()
    return RankingResult(pages, len(all_rows), len(mappings), len(clubs))
