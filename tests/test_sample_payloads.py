"""Contract tests against the committed real API samples.

These are not unit tests of our code but a guard on the *source schema*: if
football-data.org changes a field we depend on, or if our documented findings
turn out wrong, these fail. They run offline against
`data/sample/football-data/` (see docs/evidence/api-exploration.md).
"""

import json
from pathlib import Path

import pytest

SAMPLE_DIR = Path(__file__).resolve().parents[1] / "data" / "sample" / "football-data"

pytestmark = pytest.mark.skipif(
    not (SAMPLE_DIR / "matches_all.json").exists(),
    reason="API samples not present - run `make explore` first",
)


def load(name: str) -> dict:
    """Load one committed sample payload."""
    return json.loads((SAMPLE_DIR / f"{name}.json").read_text())


@pytest.fixture(scope="module")
def matches() -> list[dict]:
    """All matches of the sampled season."""
    return load("matches_all")["matches"]


def test_match_id_is_a_unique_business_key(matches):
    ids = [m["id"] for m in matches]
    assert len(ids) == len(set(ids))
    assert all(isinstance(i, int) for i in ids)


def test_every_match_has_the_fields_our_model_depends_on(matches):
    required = {"id", "utcDate", "status", "matchday", "stage", "homeTeam", "awayTeam", "score"}
    for match in matches:
        missing = required - match.keys()
        assert not missing, f"match {match.get('id')} is missing {missing}"


def test_home_and_away_team_are_never_the_same(matches):
    for match in matches:
        assert match["homeTeam"]["id"] != match["awayTeam"]["id"]


def test_team_references_carry_id_and_name(matches):
    for match in matches:
        for side in ("homeTeam", "awayTeam"):
            assert isinstance(match[side]["id"], int)
            assert match[side]["name"]


def test_kickoff_is_utc_iso8601(matches):
    for match in matches:
        assert match["utcDate"].endswith("Z")
        assert len(match["utcDate"]) == 20  # YYYY-MM-DDTHH:MM:SSZ


def test_status_values_are_known(matches):
    known = {
        "SCHEDULED",
        "TIMED",
        "IN_PLAY",
        "PAUSED",
        "FINISHED",
        "POSTPONED",
        "SUSPENDED",
        "CANCELLED",
    }
    assert {m["status"] for m in matches} <= known


def test_finished_matches_have_a_full_time_score(matches):
    finished = [m for m in matches if m["status"] == "FINISHED"]
    assert finished, "sample should contain finished matches"
    for match in finished:
        full_time = match["score"]["fullTime"]
        assert isinstance(full_time["home"], int)
        assert isinstance(full_time["away"], int)
        assert full_time["home"] >= 0 and full_time["away"] >= 0
        assert match["score"]["winner"] in {"HOME_TEAM", "AWAY_TEAM", "DRAW"}


def test_scheduled_filter_returns_timed_rows(matches):
    """Documented trap: ?status=SCHEDULED yields rows whose stored status is TIMED.

    A predicate `status = 'SCHEDULED'` on our own tables would return nothing.
    """
    scheduled_query = load("matches_scheduled")["matches"]
    assert scheduled_query, "sample should contain upcoming matches"
    assert all(m["status"] == "TIMED" for m in scheduled_query)
    assert not any(m["status"] == "SCHEDULED" for m in matches)


def test_group_is_null_since_the_league_phase_format(matches):
    """No group dimension: the 2024/25 format replaced groups with one league phase."""
    assert all(m["stage"] == "LEAGUE_STAGE" for m in matches)
    assert all(m.get("group") is None for m in matches)


def test_odds_is_a_stub_without_real_values(matches):
    """`odds` is always present but carries a marketing message on the free tier."""
    for match in matches:
        assert "msg" in match["odds"]


def test_standings_table_covers_all_league_phase_teams():
    standings = load("standings")["standings"]
    assert len(standings) == 1, "the league phase has a single table"
    table = standings[0]["table"]
    assert len(table) == 36
    positions = [row["position"] for row in table]
    assert positions == sorted(positions)
    assert all(row["form"] is None for row in table), "form is empty on the free tier"


def test_teams_endpoint_delivers_the_attributes_dim_team_needs():
    teams = load("teams")["teams"]
    assert len(teams) == 36
    ids = [t["id"] for t in teams]
    assert len(ids) == len(set(ids))
    for team in teams:
        for field in ("id", "name", "shortName", "tla"):
            assert team[field], f"team {team['id']} has no {field}"


def test_every_match_team_exists_in_the_teams_endpoint(matches):
    """Referential integrity between the two endpoints we join on."""
    known = {t["id"] for t in load("teams")["teams"]}
    referenced = {m[side]["id"] for m in matches for side in ("homeTeam", "awayTeam")}
    assert referenced <= known, f"unknown team ids: {referenced - known}"
