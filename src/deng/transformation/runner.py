"""Execute the SQL transformations in order.

The logic lives in `.sql` files, not in Python strings. Three reasons: the
files are readable and reviewable on their own, they can be run by hand in psql
while debugging, and the BigQuery versions in the final architecture will be
the same statements with a different dialect - a Python-generated query would
have to be rewritten from scratch.

The whole chain runs inside ONE transaction. Either every curated table is
consistent with the same staging state, or nothing changed and the previous
data product is still there. A half-transformed warehouse is worse than a
slightly stale one.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import psycopg

from deng.database.connection import _find_sql_dir

logger = logging.getLogger(__name__)

# Order matters: staging before curated, dimensions before the facts that
# reference them, fact_match before the form table built on top of it.
TRANSFORMATION_ORDER: tuple[str, ...] = (
    "transform/110_staging_matches.sql",
    "transform/111_staging_teams.sql",
    "transform/112_staging_standings.sql",
    "transform/210_dim_team.sql",
    "transform/220_fact_match.sql",
    "transform/230_fact_team_match_form.sql",
    "transform/240_fact_match_prediction.sql",
)

# The weather chain runs as a second, separate transaction: its input (the
# forecasts) can only be fetched once fact_match says which matches are inside
# the horizon, i.e. after the football chain has committed.
WEATHER_TRANSFORMATION_ORDER: tuple[str, ...] = (
    "transform/310_staging_weather_forecast.sql",
    "transform/320_dim_venue.sql",
    "transform/330_fact_match_weather.sql",
)

WEATHER_COUNTED_TABLES: tuple[str, ...] = (
    "staging.weather_forecast",
    "curated.dim_venue",
    "curated.fact_match_weather",
)

# The odds chain runs in two transactions with the event matcher (Python, see
# deng.ingestion.odds.match_events) in between: staging unpacks the fetches,
# the matcher resolves bookmaker events to fixtures, and only then can the
# curated change history be built per match.
ODDS_STAGING_ORDER: tuple[str, ...] = ("transform/410_staging_bookmaker_odds.sql",)
ODDS_CURATED_ORDER: tuple[str, ...] = ("transform/420_fact_bookmaker_odds.sql",)

ODDS_COUNTED_TABLES: tuple[str, ...] = (
    "staging.bookmaker_odds",
    "staging.odds_event_match",
    "curated.fact_bookmaker_odds",
)

# Tables whose row counts are reported after a run.
COUNTED_TABLES: tuple[str, ...] = (
    "staging.matches",
    "staging.teams",
    "staging.standings",
    "curated.dim_team",
    "curated.fact_match",
    "curated.fact_team_match_form",
    "curated.fact_match_prediction",
)


@dataclass
class TransformResult:
    """What one transformation run did."""

    logical_date: date
    statements: list[tuple[str, int]] = field(default_factory=list)
    row_counts: dict[str, int] = field(default_factory=dict)

    @property
    def total_rows_written(self) -> int:
        """Rows inserted or updated across all statements."""
        return sum(count for _, count in self.statements)


def run_transformations(
    connection: psycopg.Connection,
    logical_date: date,
    order: tuple[str, ...] = TRANSFORMATION_ORDER,
    counted: tuple[str, ...] = COUNTED_TABLES,
) -> TransformResult:
    """Run every transformation for one logical date in a single transaction.

    Args:
        connection: Open connection. The caller must not have an open
            transaction with uncommitted work it wants to keep separate.
        logical_date: Which ingestion date to transform. Passed into the SQL as
            `%(logical_date)s`, so a rerun for a past date reproduces that
            date's result rather than today's.
        order: The SQL files to execute, in order.
        counted: Tables whose row counts are reported afterwards.

    Returns:
        A `TransformResult` with per-statement row counts and final table sizes.

    Raises:
        psycopg.Error: on any SQL failure - the whole transaction is rolled
            back, leaving the previous curated state intact.
    """
    sql_dir = _find_sql_dir()
    result = TransformResult(logical_date=logical_date)

    try:
        with connection.cursor() as cursor:
            for relative in order:
                path = sql_dir / relative
                statement = path.read_text()
                # The date is a bound parameter (%(logical_date)s in the SQL),
                # never pasted into the text: no quoting bugs, no SQL injection,
                # and PostgreSQL types it as a date. That is also why literal %
                # signs in the SQL files are written as %% (e.g. LIKE '%%/teams').
                cursor.execute(statement, {"logical_date": logical_date})
                # rows inserted or updated by this statement (upserts count both)
                affected = cursor.rowcount if cursor.rowcount is not None else 0
                result.statements.append((relative, affected))
                logger.info("%s -> %s rows", relative, affected)

            # Counted inside the same transaction, so the numbers describe exactly
            # the state that is about to be committed.
            for table in counted:
                cursor.execute(f"SELECT count(*) FROM {table}")  # noqa: S608 - fixed literals
                row = cursor.fetchone()
                result.row_counts[table] = int(row[0]) if row else 0
        # The single commit is the "all or nothing" point: until here no other
        # connection (the app, a report) sees any of the new rows.
        connection.commit()
    except psycopg.Error:
        connection.rollback()
        logger.exception("transformation failed for %s - rolled back", logical_date)
        raise

    return result


def sql_files_present(sql_dir: Path | None = None, order: tuple[str, ...] = TRANSFORMATION_ORDER):
    """Return the transformation files that are missing, for a setup self-check."""
    base = sql_dir or _find_sql_dir()
    return [name for name in order if not (base / name).exists()]
