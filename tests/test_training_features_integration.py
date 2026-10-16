"""Exercise the wide training product against real PostgreSQL."""

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from psycopg.rows import dict_row

pytestmark = pytest.mark.postgres
SQL_DIR = Path(__file__).resolve().parents[1] / "sql"
DAY = date(2024, 1, 1)
START = datetime(2024, 1, 1, 15, tzinfo=timezone.utc)


def _execute(connection, filename):
    with connection.cursor() as cursor:
        cursor.execute(
            (SQL_DIR / "transform" / filename).read_text(),
            {"logical_date": DAY},
        )
    connection.commit()


def _seed(connection, rows):
    """Rows: id, day offset, home, away, goals, goals, status, league, season."""
    with connection.cursor() as cursor:
        for team_id in (1, 2, 3, 4):
            cursor.execute(
                "INSERT INTO curated.dim_team(team_id,name,has_domestic_coverage) "
                "VALUES (%s,%s,true) ON CONFLICT DO NOTHING",
                (team_id, f"Team {team_id}"),
            )
        for match_id, days, home, away, hg, ag, status, league, season in rows:
            kickoff = START + timedelta(days=days)
            cursor.execute(
                """
                INSERT INTO staging.matches(
                    match_id,season_id,competition_code,utc_kickoff,status,stage,
                    home_team_id,away_team_id,home_goals,away_goals,
                    home_goals_90min,away_goals_90min,duration,ingestion_date
                ) VALUES (%s,%s,%s,%s,%s,'REGULAR_SEASON',%s,%s,%s,%s,%s,%s,'REGULAR',%s)
                """,
                (match_id, season, league, kickoff, status, home, away, hg, ag, hg, ag, DAY),
            )
    connection.commit()
    _execute(connection, "220_fact_match.sql")
    _execute(connection, "500_match_training_features.sql")


def _team(connection, match_id, team_id=1):
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            "SELECT * FROM curated.team_match_features WHERE match_id=%s AND team_id=%s",
            (match_id, team_id),
        )
        result = dict(cursor.fetchone())
        result.pop("computed_at")
        return result


def _product(connection, match_id):
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            "SELECT * FROM curated.match_training_features WHERE match_id=%s", (match_id,)
        )
        return dict(cursor.fetchone())


def test_multiple_windows_are_bounded_and_have_independent_expected_values(connection):
    rows = [
        (i + 1, i * 4, 1, 2 if i % 2 else 3, i % 4, (i + 1) % 3, "FINISHED", "PL", 10)
        for i in range(12)
    ]
    rows.append((100, 49, 1, 2, None, None, "TIMED", "PL", 10))
    _seed(connection, rows)
    result = _team(connection, 100)
    for n in (3, 5, 10):
        previous = rows[-1 - n : -1]
        wins = sum(row[4] > row[5] for row in previous)
        draws = sum(row[4] == row[5] for row in previous)
        losses = sum(row[4] < row[5] for row in previous)
        assert result[f"matches_last_{n}"] == n
        assert result[f"wins_last_{n}"] == wins
        assert result[f"draws_last_{n}"] == draws
        assert result[f"losses_last_{n}"] == losses
        assert result[f"points_last_{n}"] == 3 * wins + draws
        assert result[f"goals_for_last_{n}"] == sum(row[4] for row in previous)
        assert result[f"goals_against_last_{n}"] == sum(row[5] for row in previous)
    assert result["history_matches"] == 12
    assert result["season_matches"] == 12
    assert float(result["rest_days"]) == 5.0
    assert result["played_last_7_days"] == 1
    assert result["played_last_14_days"] == 3
    assert result["played_last_30_days"] == 7


def test_current_future_simultaneous_and_unfinished_results_cannot_change_features(connection):
    _seed(
        connection,
        [
            (1, 0, 1, 2, 2, 0, "FINISHED", "PL", 10),
            (2, 4, 1, 3, 1, 1, "FINISHED", "PL", 10),
            (3, 10, 1, 2, 0, 4, "FINISHED", "PL", 10),
            (4, 10, 1, 3, 12, 0, "FINISHED", "PL", 10),
            (5, 11, 1, 4, 20, 0, "FINISHED", "PL", 10),
            (6, 9, 1, 4, 9, 0, "POSTPONED", "PL", 10),
            (7, 9.95, 1, 4, 9, 0, "FINISHED", "PL", 10),
        ],
    )
    before = _team(connection, 3)
    assert before["matches_last_10"] == 2
    assert before["points_last_10"] == 4
    assert before["season_matches"] == 2
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE staging.matches SET home_goals=99,home_goals_90min=99 "
            "WHERE match_id IN (3,4,5,6,7)"
        )
    connection.commit()
    _execute(connection, "500_match_training_features.sql")
    assert _team(connection, 3) == before


def test_competition_season_and_venue_features_use_their_own_scope(connection):
    _seed(
        connection,
        [
            (1, 0, 1, 2, 3, 0, "FINISHED", "PL", 9),
            (2, 4, 1, 2, 1, 1, "FINISHED", "CL", 20),
            (3, 8, 3, 1, 0, 2, "FINISHED", "PL", 10),
            (4, 12, 1, 2, None, None, "TIMED", "PL", 10),
        ],
    )
    result = _team(connection, 4)
    assert result["matches_last_5"] == 3
    assert result["season_matches"] == 1
    assert result["season_points"] == 3
    assert result["competition_matches_last_5"] == 2
    assert result["competition_points_last_5"] == 6
    assert result["venue_matches_last_5"] == 2
    assert result["venue_points_last_5"] == 4
    assert result["h2h_matches_last_5"] == 2
    assert result["h2h_goals_for_last_5"] == 4
    away = _team(connection, 4, 2)
    assert away["h2h_goals_against_last_5"] == 4


def test_first_fixture_has_explicit_empty_coverage_and_null_rates(connection):
    _seed(connection, [(1, 0, 1, 2, None, None, "TIMED", "PL", 10)])
    result = _team(connection, 1)
    assert result["matches_last_10"] == 0
    assert result["history_matches"] == 0
    assert result["points_last_10"] == 0
    assert result["points_per_match_last_10"] is None
    assert result["rest_days"] is None
    assert result["history_last_available_at"] is None
    product = _product(connection, 1)
    assert product["label_outcome_90min"] is None
    assert product["label_available"] is False


def test_extra_time_without_regular_time_score_counts_for_load_but_not_form(connection):
    _seed(
        connection,
        [
            (1, 0, 1, 2, 3, 2, "FINISHED", "CL", 20),
            (2, 5, 1, 3, None, None, "TIMED", "CL", 20),
        ],
    )
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE staging.matches SET duration='EXTRA_TIME',"
            "home_goals_90min=NULL,away_goals_90min=NULL WHERE match_id=1"
        )
    connection.commit()
    _execute(connection, "500_match_training_features.sql")
    result = _team(connection, 2)
    assert result["played_last_7_days"] == 1
    assert result["history_matches"] == 1
    assert result["matches_last_5"] == 0
    assert result["season_matches"] == 0
    product = _product(connection, 1)
    assert product["label_available"] is False
    assert product["label_outcome_90min"] is None


def test_regular_time_draw_is_label_even_when_fulltime_has_extra_time_winner(connection):
    _seed(connection, [(1, 0, 1, 2, 3, 2, "FINISHED", "CL", 20)])
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE staging.matches SET duration='EXTRA_TIME',"
            "home_goals_90min=2,away_goals_90min=2 WHERE match_id=1"
        )
    connection.commit()
    product = _product(connection, 1)
    assert product["label_available"] is True
    assert product["label_outcome_90min"] == "DRAW"
    assert product["label_home_goals_90min"] == 2


def test_feature_rebuild_is_idempotent_and_corrections_propagate(connection):
    _seed(
        connection,
        [
            (1, 0, 1, 2, 2, 0, "FINISHED", "PL", 10),
            (2, 7, 1, 2, None, None, "TIMED", "PL", 10),
        ],
    )
    before = _team(connection, 2)
    _execute(connection, "500_match_training_features.sql")
    assert _team(connection, 2) == before
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE staging.matches SET home_goals_90min=0,away_goals_90min=1 WHERE match_id=1"
        )
    connection.commit()
    _execute(connection, "500_match_training_features.sql")
    assert _team(connection, 2)["points_last_5"] == 0
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*),count(DISTINCT match_id) FROM curated.match_training_features"
        )
        assert cursor.fetchone() == (2, 2)
