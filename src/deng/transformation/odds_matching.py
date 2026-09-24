"""Resolving bookmaker events to our fixtures.

This is a transformation, not an ingestion step: it reads what the
transformation already built (curated.fact_match, curated.dim_team,
staging.bookmaker_odds) and writes staging.odds_event_match. It lives here so
the ingestion package can keep its rule - ingestion reads the APIs, the files
under data/ and the raw zone, never the transformed layers.

Why name matching at all: The Odds API names its events after the bookmakers'
spellings ("Inter Milan", "Sporting Lisbon"), football-data.org uses the club's
own name ("FC Internazionale Milano"). There is no shared id, so an event is
resolved by kick-off time plus the similarity of both club names, with a small
reviewed alias file for the spellings that are too far apart.
"""

from __future__ import annotations

import csv
import logging
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import psycopg

from deng.files import project_file

logger = logging.getLogger(__name__)

# How far a bookmaker kick-off may differ from ours and still be the same match.
KICKOFF_TOLERANCE = timedelta(hours=3)
# Below this token similarity two names are not considered the same club.
MATCH_THRESHOLD = 0.6

ALIASES_FILE = Path("data") / "reference" / "bookmaker_team_aliases.csv"


# --------------------------------------------------------------------------
# Resolving bookmaker events to our fixtures
# --------------------------------------------------------------------------

# Tokens that carry no identity: legal forms and generic words. "united",
# "city", "real" and the like stay - removing them would make Manchester
# United and Manchester City the same club.
STOPWORDS = frozenset(
    "fc cf sc sk fk kv cp ac as ssc afc bk sv rc osc pae ae club clube de da del di "
    "balompie calcio spor kulubu 1907".split()
)
TRANSLITERATE = str.maketrans({"ø": "o", "æ": "ae", "ß": "ss", "ł": "l", "đ": "d", "ð": "d"})


def normalise(name: str) -> frozenset[str]:
    """A club name as a set of comparable tokens: lower-case, ASCII, no legal forms."""
    text = unicodedata.normalize("NFKD", name.lower().translate(TRANSLITERATE))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    tokens = [t for t in re.split(r"[^a-z0-9]+", text) if t]
    kept = frozenset(t for t in tokens if t not in STOPWORDS)
    return kept or frozenset(tokens)


def similarity(a: frozenset[str], b: frozenset[str]) -> float:
    """Overlap coefficient: shared tokens over the smaller set (1.0 = one contains the other)."""
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def load_aliases(path: Path | None = None) -> dict[int, list[str]]:
    """Bookmaker spellings per team id from the reference CSV."""
    path = path or project_file(ALIASES_FILE)
    aliases: dict[int, list[str]] = {}
    if not path.exists():
        return aliases
    with path.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row.get("alias"):
                aliases.setdefault(int(row["team_id"]), []).append(row["alias"])
    return aliases


@dataclass(frozen=True)
class Fixture:
    """A fixture with every spelling we know for each side."""

    match_id: int
    utc_kickoff: datetime
    home_names: tuple[frozenset[str], ...]
    away_names: tuple[frozenset[str], ...]


@dataclass(frozen=True)
class EventMatch:
    """The resolution of one bookmaker event."""

    match_id: int | None
    confidence: float
    note: str


def resolve_event(
    home: str, away: str, commence_time: datetime, fixtures: list[Fixture]
) -> EventMatch:
    """Pick the fixture for an event: same kick-off (within tolerance), both names similar.

    Pure function: tested without a database. Ambiguity (two fixtures equally
    similar) is an UNMATCHED result with a note, not a guess.
    """
    home_tokens, away_tokens = normalise(home), normalise(away)
    scored = []
    for fixture in fixtures:
        if abs(fixture.utc_kickoff - commence_time) > KICKOFF_TOLERANCE:
            continue
        home_sim = max(similarity(home_tokens, n) for n in fixture.home_names)
        away_sim = max(similarity(away_tokens, n) for n in fixture.away_names)
        if min(home_sim, away_sim) >= MATCH_THRESHOLD:
            scored.append((home_sim + away_sim, fixture.match_id))
    if not scored:
        return EventMatch(None, 0.0, "no fixture within 3 h whose team names are similar enough")
    scored.sort(reverse=True)
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        return EventMatch(None, 0.0, f"ambiguous between matches {scored[0][1]} and {scored[1][1]}")
    score, match_id = scored[0]
    return EventMatch(match_id, round(score / 2, 3), "kick-off time and team names")


def load_fixtures(connection: psycopg.Connection, aliases: dict[int, list[str]]) -> list[Fixture]:
    """Every fixture with its team names, short names, codes and aliases."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT m.match_id, m.utc_kickoff,
                   h.team_id, h.name, h.short_name, h.tla,
                   a.team_id, a.name, a.short_name, a.tla
              FROM curated.fact_match m
              JOIN curated.dim_team h ON h.team_id = m.home_team_id
              JOIN curated.dim_team a ON a.team_id = m.away_team_id
            """
        )
        rows = cursor.fetchall()

    def names(team_id: int, *spellings: str | None) -> tuple[frozenset[str], ...]:
        candidates = [s for s in spellings if s] + aliases.get(team_id, [])
        return tuple(normalise(s) for s in candidates)

    return [
        Fixture(
            int(r[0]), r[1], names(int(r[2]), r[3], r[4], r[5]), names(int(r[6]), r[7], r[8], r[9])
        )
        for r in rows
    ]


def match_events(
    connection: psycopg.Connection, aliases: dict[int, list[str]] | None = None
) -> tuple[int, list[str]]:
    """Resolve every staged event without a match. Returns (matched, unmatched labels).

    Re-evaluates UNMATCHED events every time, so a new alias in the CSV takes
    effect on the next run without any manual repair.
    """
    aliases = load_aliases() if aliases is None else aliases
    fixtures = load_fixtures(connection, aliases)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT DISTINCT s.event_id, s.commence_time, s.home_team_name, s.away_team_name
              FROM staging.bookmaker_odds s
              LEFT JOIN staging.odds_event_match x ON x.event_id = s.event_id
             WHERE x.event_id IS NULL OR x.match_id IS NULL
             ORDER BY s.commence_time, s.event_id
            """
        )
        events = cursor.fetchall()

    matched, unmatched = 0, []
    with connection.cursor() as cursor:
        for event_id, commence_time, home, away in events:
            found = resolve_event(home, away, commence_time, fixtures)
            if found.match_id is None:
                unmatched.append(f"{home} vs {away} ({commence_time:%d %b %H:%M} UTC)")
            else:
                matched += 1
            cursor.execute(
                """
                INSERT INTO staging.odds_event_match AS x
                    (event_id, match_id, commence_time, home_team_name, away_team_name,
                     method, confidence, note, matched_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now())
                ON CONFLICT (event_id) DO UPDATE SET
                    match_id = EXCLUDED.match_id, commence_time = EXCLUDED.commence_time,
                    home_team_name = EXCLUDED.home_team_name,
                    away_team_name = EXCLUDED.away_team_name, method = EXCLUDED.method,
                    confidence = EXCLUDED.confidence, note = EXCLUDED.note, matched_at = now()
                """,
                (
                    event_id,
                    found.match_id,
                    commence_time,
                    home,
                    away,
                    "NAME" if found.match_id is not None else "UNMATCHED",
                    found.confidence,
                    found.note,
                ),
            )
    connection.commit()
    for label in unmatched:
        logger.warning("odds event not resolved to a fixture: %s", label)
    return matched, unmatched
