"""The payload contracts: required fields fail fast, everything else is tolerated.

Two directions matter equally. Every committed sample - real API answers - must
pass, or the check would stop a healthy day. And each way an answer can drift
(a field gone, a list renamed, a value of another type) must fail with a
message that names the field.
"""

import copy
import json
from pathlib import Path

import pytest

from deng.sources.contracts import ContractError, check_football, check_open_meteo
from deng.sources.http import ApiError, RetryableApiError
from deng.sources.open_meteo import HOURLY_VARIABLES

SAMPLES = Path(__file__).resolve().parents[1] / "data" / "sample"
FOOTBALL = SAMPLES / "football-data"

ENDPOINT_SAMPLES = {
    "competitions/{code}": "competition.json",
    "competitions/{code}/teams": "teams.json",
    "competitions/{code}/standings": "standings.json",
    "competitions/{code}/matches": "matches_all.json",
}


def _sample(name: str) -> dict:
    return json.loads((FOOTBALL / name).read_text())


def _matches_problems(payload: dict) -> list[str]:
    with pytest.raises(ContractError) as caught:
        check_football("competitions/{code}/matches", payload, "competitions/CL/matches")
    return caught.value.problems


@pytest.mark.parametrize("template,filename", sorted(ENDPOINT_SAMPLES.items()))
def test_every_committed_sample_passes(template, filename):
    check_football(template, _sample(filename), template)


@pytest.mark.parametrize("filename", ["matches_finished.json", "matches_scheduled.json"])
def test_filtered_match_answers_pass_too(filename):
    check_football("competitions/{code}/matches", _sample(filename), "matches")


def test_the_committed_forecast_passes():
    for path in (SAMPLES / "open-meteo").glob("forecast_*.json"):
        check_open_meteo(json.loads(path.read_text()), HOURLY_VARIABLES, path.name)


def test_a_missing_required_field_names_the_record_and_the_field():
    payload = _sample("matches_all.json")
    first = payload["matches"][0]
    del first["utcDate"]

    problems = _matches_problems(payload)

    assert problems == [f"matches[0] (id {first['id']}).utcDate missing"]


def test_a_renamed_list_is_drift_not_an_empty_day():
    payload = _sample("teams.json")
    payload["clubs"] = payload.pop("teams")

    with pytest.raises(ContractError, match="teams missing or not a list"):
        check_football("competitions/{code}/teams", payload, "competitions/CL/teams")


def test_an_empty_fixture_list_is_rejected():
    payload = _sample("matches_all.json")
    payload["matches"] = []

    assert _matches_problems(payload) == ["matches is empty"]


def test_a_value_of_another_type_is_rejected():
    payload = _sample("matches_all.json")
    payload["matches"][0]["id"] = "537327"
    payload["matches"][1]["utcDate"] = "next Tuesday"

    problems = _matches_problems(payload)

    assert len(problems) == 2
    assert "id is not int" in problems[0]
    assert "utcDate is not timestamp" in problems[1]


def test_new_and_missing_optional_fields_are_tolerated():
    payload = _sample("matches_all.json")
    for match in payload["matches"]:
        match["xG"] = {"home": 1.4, "away": 0.9}  # a field the API might add
        del match["referees"]  # one we never read
        match["homeTeam"].pop("tla", None)
    payload["brandNewTopLevelKey"] = True

    check_football("competitions/{code}/matches", payload, "competitions/CL/matches")


def test_null_is_allowed_where_it_has_a_meaning():
    # Before kick-off there is no score; before a knockout draw no opponent.
    payload = _sample("matches_all.json")
    match = payload["matches"][0]
    match["score"]["fullTime"] = {"home": None, "away": None}
    match["awayTeam"] = {"id": None, "name": None}

    check_football("competitions/{code}/matches", payload, "competitions/CL/matches")


def test_a_null_id_is_not_allowed():
    payload = _sample("teams.json")
    payload["teams"][2]["id"] = None

    with pytest.raises(ContractError, match=r"teams\[2\]\.id is null"):
        check_football("competitions/{code}/teams", payload, "competitions/CL/teams")


def test_a_broken_standings_row_is_found_two_levels_deep():
    payload = _sample("standings.json")
    del payload["standings"][0]["table"][4]["team"]

    with pytest.raises(ContractError, match=r"standings\[0\]\.table\[4\]\.team\.id missing"):
        check_football("competitions/{code}/standings", payload, "competitions/CL/standings")


def test_the_message_lists_a_few_problems_and_counts_the_rest():
    payload = _sample("matches_all.json")
    for match in payload["matches"]:
        del match["status"]

    with pytest.raises(ContractError) as caught:
        check_football("competitions/{code}/matches", payload, "competitions/CL/matches")

    assert len(caught.value.problems) == len(payload["matches"])
    assert f"and {len(payload['matches']) - 5} more" in str(caught.value)


def test_drift_is_permanent_so_it_is_never_retried():
    payload = _sample("competition.json")
    del payload["currentSeason"]

    with pytest.raises(ApiError) as caught:
        check_football("competitions/{code}", payload, "competitions/CL")
    assert not isinstance(caught.value, RetryableApiError)


def test_an_endpoint_without_a_contract_cannot_be_ingested():
    with pytest.raises(KeyError):
        check_football("competitions/{code}/scorers", {}, "competitions/CL/scorers")


def test_a_forecast_array_one_hour_short_is_rejected():
    path = next((SAMPLES / "open-meteo").glob("forecast_*.json"))
    payload = json.loads(path.read_text())
    payload["hourly"]["wind_speed_10m"].pop()
    del payload["hourly"]["weather_code"]

    with pytest.raises(ContractError) as caught:
        check_open_meteo(payload, HOURLY_VARIABLES, "v1/forecast")

    hours = len(payload["hourly"]["time"])
    assert caught.value.problems == [
        f"hourly.wind_speed_10m has {hours - 1} values for {hours} hours",
        "hourly.weather_code missing or not a list",
    ]


def test_samples_are_not_modified_by_the_checks():
    payload = _sample("matches_all.json")
    before = copy.deepcopy(payload)
    check_football("competitions/{code}/matches", payload, "matches")
    assert payload == before


# --- against PostgreSQL ------------------------------------------------------


@pytest.mark.postgres
def test_drift_fails_the_run_and_stores_nothing_of_the_day(connection, monkeypatch, tmp_path):
    """The fixture list arrives last; the three answers before it are rolled back."""
    from datetime import date

    from deng.config import get_settings
    from deng.ingestion import runner
    from deng.sources import football_data

    for name in ENDPOINT_SAMPLES.values():
        (tmp_path / name).write_text((FOOTBALL / name).read_text())
    broken = _sample("matches_all.json")
    del broken["matches"][7]["score"]
    (tmp_path / "matches_all.json").write_text(json.dumps(broken))
    monkeypatch.setattr(football_data, "sample_dir", lambda: tmp_path)

    context = runner.Context(connection, date(2026, 10, 19), get_settings(), from_samples=True)
    with pytest.raises(ContractError, match=r"matches\[7\].*score\.fullTime\.home missing"):
        runner.ingest_all(context, only="football")

    with connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM raw.football_data")
        assert cursor.fetchone()[0] == 0
        cursor.execute("SELECT status, error_message FROM meta.pipeline_runs")
        status, message = cursor.fetchone()
    assert status == "FAILED"
    assert message.startswith("ContractError: HTTP 200: football-data.org competitions/CL/matches")
