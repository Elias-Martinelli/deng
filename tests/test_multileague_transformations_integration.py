"""Regression checks for multi-league staging and cached history replay."""

from copy import deepcopy
from datetime import date, timedelta

import pytest

from deng.database.raw_loader import RawLoader
from deng.transformation import run_transformations

pytestmark = pytest.mark.postgres
TODAY = date(2026, 10, 2)


def store(connection, run_id, endpoint, payload, params=None, day=TODAY):
    """Store a provider-shaped fixture into the isolated raw zone."""
    RawLoader(connection).load(
        run_id=run_id,
        endpoint=endpoint,
        request_params=params or {},
        request_url="https://example.test",
        payload=payload,
        ingestion_date=day,
    )
    connection.commit()


def test_all_leagues_keep_total_standings_without_home_away_duplicates(connection, run_id):
    for code, season_id in [("CL", 100), ("PL", 200)]:
        table = [
            {
                "team": {"id": 1},
                "position": 1,
                "points": 18,
                "playedGames": 6,
                "won": 6,
                "draw": 0,
                "lost": 0,
                "goalsFor": 12,
                "goalsAgainst": 3,
                "goalDifference": 9,
            }
        ]
        store(
            connection,
            run_id,
            f"competitions/{code}/standings",
            {
                "season": {"id": season_id},
                "standings": [
                    {"type": "TOTAL", "table": table},
                    {"type": "HOME", "table": [{"team": {"id": 1}, "points": 9}]},
                    {"type": "AWAY", "table": [{"team": {"id": 1}, "points": 9}]},
                ],
            },
        )
    run_transformations(
        connection,
        TODAY,
        order=("transform/112_staging_standings.sql",),
        counted=("staging.standings",),
    )
    with connection.cursor() as cur:
        cur.execute("SELECT season_id, points FROM staging.standings ORDER BY season_id")
        assert cur.fetchall() == [(100, 18), (200, 18)]


def test_current_team_description_wins_over_history_loaded_afterwards(connection, run_id):
    store(
        connection,
        run_id,
        "competitions/PL/teams",
        {"teams": [{"id": 1, "name": "Current name", "venue": "Current ground"}]},
    )
    store(
        connection,
        run_id,
        "competitions/CL/teams",
        {"teams": [{"id": 1, "name": "Historic name", "venue": "Old ground"}]},
        params={"season": "2023"},
    )
    run_transformations(
        connection,
        TODAY,
        order=("transform/111_staging_teams.sql",),
        counted=("staging.teams",),
    )
    with connection.cursor() as cur:
        cur.execute("SELECT name, venue FROM staging.teams WHERE team_id = 1")
        assert cur.fetchone() == ("Current name", "Current ground")
        cur.execute("SELECT name, venue FROM raw.team_catalog WHERE team_id = 1")
        assert cur.fetchone() == ("Current name", "Current ground")


def test_cached_match_payload_is_replayable_and_uses_regular_time_score(
    connection, run_id, sample_payload
):
    match = deepcopy(sample_payload["matches"][0])
    match.update({"id": 901, "status": "FINISHED"})
    match["score"] = {
        "duration": "EXTRA_TIME",
        "fullTime": {"home": 2, "away": 1},
        "regularTime": {"home": 1, "away": 1},
        "halfTime": {"home": 0, "away": 0},
    }
    store(
        connection,
        run_id,
        "competitions/CL/matches",
        {"matches": [match]},
        params={"season": "2023"},
        day=TODAY - timedelta(days=1),
    )
    run_transformations(
        connection,
        TODAY,
        order=("transform/110_staging_matches.sql",),
        counted=("staging.matches",),
    )
    with connection.cursor() as cur:
        cur.execute(
            "SELECT home_goals, away_goals, home_goals_90min, away_goals_90min "
            "FROM staging.matches WHERE match_id = 901"
        )
        assert cur.fetchone() == (2, 1, 1, 1)


def test_extra_time_score_without_regular_time_does_not_create_90_minute_label(
    connection, run_id, sample_payload
):
    match = deepcopy(sample_payload["matches"][0])
    match.update({"id": 902, "status": "FINISHED"})
    match["score"] = {"duration": "PENALTY_SHOOTOUT", "fullTime": {"home": 5, "away": 4}}
    store(connection, run_id, "competitions/CL/matches", {"matches": [match]})
    run_transformations(
        connection,
        TODAY,
        order=("transform/110_staging_matches.sql",),
        counted=("staging.matches",),
    )
    with connection.cursor() as cur:
        cur.execute(
            "SELECT home_goals_90min, away_goals_90min FROM staging.matches WHERE match_id = 902"
        )
        assert cur.fetchone() == (None, None)
