"""The questions the ingestion is allowed to ask - all answered by the raw zone.

Some sources need to know something before they can ask their API:

* the weather source needs the matches of the next 16 days and their stadiums,
* the crest source needs the clubs and their crest URLs,
* the odds source needs the kick-off times it is watching,
* the stadium source needs the club and venue names.

All of that is already in the raw zone, because the football answer of the same
run was stored there first. So the ingestion looks it up here instead of in the
tables the transformation builds - see tests/test_layering.py for the rule.

Each function is one SELECT against a view from sql/schema/009_raw_planning_views.sql.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

import psycopg


@dataclass(frozen=True)
class Match:
    """One match, as the ingestion needs to see it."""

    match_id: int
    utc_kickoff: datetime
    match_date: date
    home_team_id: int


@dataclass(frozen=True)
class Club:
    """One club, as the ingestion needs to see it."""

    team_id: int
    name: str
    venue: str | None
    country: str | None
    crest_url: str | None


def upcoming_matches(
    connection: psycopg.Connection, first_day: date, last_day: date
) -> list[Match]:
    """Matches that have not been played yet and start between the two days."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT match_id, utc_kickoff, match_date, home_team_id
              FROM raw.match_calendar
             WHERE NOT is_finished
               AND match_date BETWEEN %s AND %s
             ORDER BY utc_kickoff
            """,
            (first_day, last_day),
        )
        return [Match(int(m), k, d, int(h)) for m, k, d, h in cursor.fetchall()]


def kickoffs_of_unplayed_matches(connection: psycopg.Connection) -> list[datetime]:
    """Kick-off times of every match that has not been played yet."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT utc_kickoff FROM raw.match_calendar WHERE NOT is_finished ORDER BY utc_kickoff"
        )
        return [row[0] for row in cursor.fetchall()]


def kickoffs_of_matches(connection: psycopg.Connection, match_ids: set[int]) -> list[datetime]:
    """Kick-off times of the given matches (used when only some are watched)."""
    if not match_ids:
        return []
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT utc_kickoff FROM raw.match_calendar "
            "WHERE match_id = ANY(%s) ORDER BY utc_kickoff",
            (list(match_ids),),
        )
        return [row[0] for row in cursor.fetchall()]


def clubs(connection: psycopg.Connection) -> list[Club]:
    """Every club of the competition, with its venue name and crest URL."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT team_id, name, venue, country, crest_url
              FROM raw.team_catalog
             ORDER BY team_id
            """
        )
        return [Club(int(t), n, v, c, u) for t, n, v, c, u in cursor.fetchall()]
