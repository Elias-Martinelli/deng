"""Data-quality checks on the curated layer.

Each check is one SQL query returning a single row with two columns:
`observed` (what we measured) and `passed` (boolean). Results are written to
`meta.dq_results`, so "was the data good on 18 September?" is answerable with a
query rather than by reading old logs.

Severity decides what a failure means:

* CRITICAL - the data product is wrong. The run fails, and the previous
  curated state stays in place (the transformation is transactional).
* WARNING  - worth knowing, not worth discarding the run for. Early in the
  season most teams genuinely have little form data; failing the pipeline over
  that would train us to ignore it.

Constraints in the DDL and checks here do different jobs. A constraint makes a
bad row impossible to write; a check measures something a constraint cannot
express, such as "does the curated match count still equal staging's".
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

import psycopg

logger = logging.getLogger(__name__)

CRITICAL = "CRITICAL"
WARNING = "WARNING"


@dataclass(frozen=True)
class Check:
    """One data-quality check."""

    name: str
    target: str
    severity: str
    sql: str
    description: str


@dataclass
class CheckResult:
    """Outcome of one check."""

    check: Check
    passed: bool
    observed: str

    @property
    def is_blocking(self) -> bool:
        """True when this failure must fail the pipeline run."""
        return not self.passed and self.check.severity == CRITICAL


CHECKS: tuple[Check, ...] = (
    Check(
        name="fact_match_not_empty",
        target="curated.fact_match",
        severity=CRITICAL,
        description="A run that produces no matches has silently failed upstream.",
        sql="SELECT count(*)::text AS observed, count(*) > 0 AS passed FROM curated.fact_match",
    ),
    Check(
        name="match_id_unique",
        target="curated.fact_match",
        severity=CRITICAL,
        description="The business key must identify exactly one row.",
        sql="""
            SELECT count(*)::text AS observed, count(*) = 0 AS passed
              FROM (SELECT match_id FROM curated.fact_match
                     GROUP BY match_id HAVING count(*) > 1) AS d
        """,
    ),
    Check(
        name="no_match_lost_in_transformation",
        target="staging.matches -> curated.fact_match",
        severity=CRITICAL,
        description=(
            "Every staged match must reach the curated layer. A gap means a team is "
            "missing from dim_team and the match was filtered out."
        ),
        sql="""
            SELECT (SELECT count(*) FROM staging.matches)::text || ' staged / '
                   || (SELECT count(*) FROM curated.fact_match)::text || ' curated' AS observed,
                   (SELECT count(*) FROM staging.matches)
                   = (SELECT count(*) FROM curated.fact_match) AS passed
        """,
    ),
    Check(
        name="teams_differ",
        target="curated.fact_match",
        severity=CRITICAL,
        description="A team cannot play itself.",
        sql="""
            SELECT count(*)::text AS observed, count(*) = 0 AS passed
              FROM curated.fact_match WHERE home_team_id = away_team_id
        """,
    ),
    Check(
        name="finished_matches_have_an_outcome",
        target="curated.fact_match",
        severity=CRITICAL,
        description="A finished match without a result would break the ML target label.",
        sql="""
            SELECT count(*)::text AS observed, count(*) = 0 AS passed
              FROM curated.fact_match WHERE is_finished AND outcome IS NULL
        """,
    ),
    Check(
        name="outcome_matches_the_goals",
        target="curated.fact_match",
        severity=CRITICAL,
        description="The label must agree with the numbers in the same row.",
        sql="""
            SELECT count(*)::text AS observed, count(*) = 0 AS passed
              FROM curated.fact_match
             WHERE outcome IS NOT NULL
               AND outcome <> CASE WHEN home_goals > away_goals THEN 'HOME_WIN'
                                   WHEN home_goals < away_goals THEN 'AWAY_WIN'
                                   ELSE 'DRAW' END
        """,
    ),
    Check(
        name="goals_are_plausible",
        target="curated.fact_match",
        severity=WARNING,
        description="Above 15 goals for one side is almost certainly a parsing error, not a game.",
        sql="""
            SELECT count(*)::text AS observed, count(*) = 0 AS passed
              FROM curated.fact_match
             WHERE home_goals > 15 OR away_goals > 15 OR home_goals < 0 OR away_goals < 0
        """,
    ),
    Check(
        name="every_match_has_two_form_rows",
        target="curated.fact_team_match_form",
        severity=CRITICAL,
        description="The form table's grain is one row per team per match - exactly two per match.",
        sql="""
            SELECT count(*)::text AS observed, count(*) = 0 AS passed
              FROM (SELECT match_id FROM curated.fact_team_match_form
                     GROUP BY match_id HAVING count(*) <> 2) AS d
        """,
    ),
    Check(
        name="form_counts_add_up",
        target="curated.fact_team_match_form",
        severity=CRITICAL,
        description=(
            "wins + draws + losses must equal matches_considered. The source API's own "
            "aggregates fail exactly this check, which is why we compute ours."
        ),
        sql="""
            SELECT count(*)::text AS observed, count(*) = 0 AS passed
              FROM curated.fact_team_match_form
             WHERE wins_last_5 + draws_last_5 + losses_last_5 <> matches_considered
        """,
    ),
    Check(
        name="form_uses_no_future_matches",
        target="curated.fact_team_match_form",
        severity=CRITICAL,
        description=(
            "Leakage guard: a team's form may not be based on more matches than it had "
            "actually completed before kick-off."
        ),
        sql="""
            SELECT count(*)::text AS observed, count(*) = 0 AS passed
              FROM curated.fact_team_match_form f
              JOIN curated.fact_match m USING (match_id)
             WHERE f.matches_considered > (
                     SELECT count(*) FROM curated.fact_match p
                      WHERE p.is_finished AND p.utc_kickoff < m.utc_kickoff
                        AND (p.home_team_id = f.team_id OR p.away_team_id = f.team_id)
                   )
        """,
    ),
    Check(
        name="form_window_is_well_populated",
        target="curated.fact_team_match_form",
        severity=WARNING,
        description=(
            "Early in a season most teams have fewer than 5 completed matches. Informational: "
            "it tells an analyst how much the form features can be trusted right now."
        ),
        sql="""
            SELECT round(100.0 * count(*) FILTER (WHERE matches_considered >= 3)
                         / NULLIF(count(*), 0), 1)::text || '% with >= 3 matches' AS observed,
                   coalesce(avg(matches_considered) >= 3, false) AS passed
              FROM curated.fact_team_match_form
        """,
    ),
    Check(
        name="dim_team_complete",
        target="curated.dim_team",
        severity=CRITICAL,
        description="Every team referenced by a match must exist in the dimension.",
        sql="""
            SELECT count(*)::text AS observed, count(*) = 0 AS passed
              FROM (
                SELECT home_team_id AS team_id FROM curated.fact_match
                UNION
                SELECT away_team_id FROM curated.fact_match
              ) AS referenced
             WHERE NOT EXISTS (
                SELECT 1 FROM curated.dim_team d WHERE d.team_id = referenced.team_id)
        """,
    ),
    Check(
        name="every_match_has_a_weather_row",
        target="curated.fact_match_weather",
        severity=CRITICAL,
        description=(
            "Every match has a weather row - with values or with the reason there are none. "
            "A match without a row would be indistinguishable from one we forgot."
        ),
        sql="""
            SELECT count(*)::text || ' match(es) without a weather row' AS observed,
                   count(*) = 0 AS passed
              FROM curated.fact_match m
             WHERE NOT EXISTS (
                SELECT 1 FROM curated.fact_match_weather w WHERE w.match_id = m.match_id)
        """,
    ),
    Check(
        name="weather_fetched_before_kickoff",
        target="curated.fact_match_weather",
        severity=CRITICAL,
        description=(
            "Leakage guard, recomputed independently of the SQL that builds the table: no "
            "forecast used for a match may have been fetched at or after its kick-off."
        ),
        sql="""
            SELECT count(*)::text AS observed, count(*) = 0 AS passed
              FROM curated.fact_match_weather w
              JOIN curated.fact_match m USING (match_id)
             WHERE w.weather_status = 'AVAILABLE'
               AND w.forecast_fetched_at >= m.utc_kickoff
        """,
    ),
    Check(
        name="weather_values_plausible",
        target="curated.fact_match_weather",
        severity=CRITICAL,
        description=(
            "Temperature -40..50 °C, precipitation >= 0 mm, probability 0..100 %, wind "
            "0..250 km/h. Outside that the unpacking is wrong, not the weather."
        ),
        sql="""
            SELECT count(*)::text AS observed, count(*) = 0 AS passed
              FROM curated.fact_match_weather
             WHERE weather_status = 'AVAILABLE'
               AND (temperature_c NOT BETWEEN -40 AND 50
                    OR precipitation_mm < 0
                    OR precipitation_probability NOT BETWEEN 0 AND 100
                    OR wind_speed_kmh NOT BETWEEN 0 AND 250)
        """,
    ),
    Check(
        name="no_forecast_missing_inside_horizon",
        target="curated.fact_match_weather",
        severity=WARNING,
        description=(
            "Upcoming matches inside the 16-day horizon have a forecast. WARNING: a gap here "
            "means a failed or skipped weather run; the football data is still valid."
        ),
        sql="""
            SELECT count(*)::text || ' match(es) MISSING' AS observed, count(*) = 0 AS passed
              FROM curated.fact_match_weather
             WHERE weather_status = 'MISSING'
        """,
    ),
    Check(
        name="every_team_has_a_venue_row",
        target="curated.dim_venue",
        severity=WARNING,
        description=(
            "Every club appears in data/reference/venues.csv (resolved or with a reason). A new "
            "club after the knockout draw needs `make venues`."
        ),
        sql="""
            SELECT count(*)::text || ' team(s) without a venue row' AS observed,
                   count(*) = 0 AS passed
              FROM curated.dim_team d
             WHERE NOT EXISTS (SELECT 1 FROM curated.dim_venue v WHERE v.team_id = d.team_id)
        """,
    ),
    Check(
        name="every_team_has_a_crest",
        target="curated.team_crest",
        severity=WARNING,
        description=(
            "Every team's current crest is stored. WARNING: without it the viewer shows the "
            "three-letter code instead - cosmetic, and a download can fail for reasons outside "
            "our control."
        ),
        sql="""
            SELECT count(*)::text || ' team(s) without a crest' AS observed, count(*) = 0 AS passed
              FROM curated.dim_team d
             WHERE NOT EXISTS (SELECT 1 FROM curated.team_crest c WHERE c.team_id = d.team_id)
        """,
    ),
)


def run_checks(
    connection: psycopg.Connection,
    run_id: uuid.UUID | None = None,
    checks: tuple[Check, ...] = CHECKS,
) -> list[CheckResult]:
    """Execute every check, persist the results and return them.

    Args:
        connection: Open connection.
        run_id: Run to attribute the results to; may be None for an ad-hoc run.
        checks: Checks to execute.

    Returns:
        One `CheckResult` per check, in order.
    """
    results: list[CheckResult] = []
    with connection.cursor() as cursor:
        for check in checks:
            cursor.execute(check.sql)
            row = cursor.fetchone()
            observed = "" if row is None else str(row[0])
            passed = bool(row[1]) if row is not None else False
            result = CheckResult(check=check, passed=passed, observed=observed)
            results.append(result)

            cursor.execute(
                """
                INSERT INTO meta.dq_results
                    (run_id, check_name, target, severity, passed, observed, details)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    run_id,
                    check.name,
                    check.target,
                    check.severity,
                    passed,
                    observed,
                    check.description,
                ),
            )
            log = logger.info if passed else logger.warning
            log(
                "dq %s [%s] %s: %s",
                check.name,
                check.severity,
                "PASS" if passed else "FAIL",
                observed,
            )
    connection.commit()
    return results


class DataQualityError(RuntimeError):
    """Raised when at least one CRITICAL check failed."""
