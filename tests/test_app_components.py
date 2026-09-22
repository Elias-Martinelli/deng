"""Tests for the viewer's HTML building blocks (no Streamlit needed)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from components import (  # noqa: E402
    MatchWeather,
    ResultRow,
    TeamForm,
    badge,
    crest_uri,
    form_card,
    form_pills,
    match_hero,
    outcome_for,
    result_list,
    status_chips,
    weather_card,
)


def team(**overrides) -> TeamForm:
    values = dict(
        name="Galatasaray SK",
        tla="GAL",
        crest_uri=None,
        sequence=["L"],
        matches_considered=1,
        points=0,
        goals_for=1,
        goals_against=3,
        days_rest=5,
    )
    values.update(overrides)
    return TeamForm(**values)


def test_data_from_the_api_cannot_inject_markup():
    html = match_hero("<script>x</script>", None, "B & C", "BC", "today", 1, "<img src=x>")
    assert "<script>" not in html and "<img" not in html
    assert "&lt;script&gt;" in html and "B &amp; C" in html


def test_outcome_is_seen_from_the_given_team():
    assert outcome_for(team_id=1, home_id=1, home_goals=2, away_goals=0) == "W"
    assert outcome_for(team_id=2, home_id=1, home_goals=2, away_goals=0) == "L"
    assert outcome_for(team_id=2, home_id=1, home_goals=1, away_goals=1) == "D"


def test_pills_carry_letters_not_only_colour():
    html = form_pills(["W", "D", "L"])
    assert ">W<" in html and ">D<" in html and ">L<" in html


def test_empty_form_says_so_instead_of_showing_nothing():
    assert "No completed match" in form_pills([])


def test_window_size_is_always_shown():
    assert "last 1 CL match" in form_card(team())
    assert "last 5 CL matches" in form_card(team(matches_considered=5, sequence=list("WWDLW")))
    assert "no CL match yet" in form_card(team(matches_considered=0, sequence=[]))


def test_no_per_club_coverage_caveat():
    # ADR-004: form is Champions League only for every club, so a caveat on
    # some clubs would wrongly imply the others include domestic matches.
    assert "Domestic" not in form_card(team())


def test_badge_falls_back_to_initials_without_a_tla():
    assert ">RCL<" in badge(None, "Racing Club Lens")


def test_result_list_bolds_the_winner_and_handles_empty():
    html = result_list([ResultRow("09 Sep 2026", "PSG", "Bratislava", 6, 1)], "none")
    assert 'cl-h cl-win">PSG' in html and 'cl-a">Bratislava' in html
    assert "none" in result_list([], "none")


def test_status_is_red_only_for_what_fails_a_run():
    warning_only = status_chips("2026-09-21", True, 11, 12, dq_critical_failed=0)
    assert "cl-warn" in warning_only and "cl-bad" not in warning_only
    assert "cl-bad" in status_chips("2026-09-21", True, 11, 12, dq_critical_failed=1)
    assert "cl-bad" in status_chips(None, False, 0, 0, dq_critical_failed=0)


def test_crest_is_embedded_when_stored_and_code_otherwise():
    uri = crest_uri("image/png", b"\x89PNG fake")
    assert uri.startswith("data:image/png;base64,")
    assert "<img" in badge("GAL", "Galatasaray SK", uri)
    assert ">GAL<" in badge("GAL", "Galatasaray SK", None)


def test_only_image_types_become_a_crest():
    assert crest_uri("text/html", b"<script>") is None
    assert crest_uri("image/png", b"") is None


def test_weather_shows_values_when_available():
    html = weather_card(MatchWeather("AVAILABLE", 12.4, 40, 0.2, 13.0, 3, "12 Oct 06:00", 1))
    assert "12 °C" in html and "40 % rain" in html and "Overcast" in html
    assert "1 day before kick-off" in html and "CC BY 4.0" in html


def test_weather_explains_every_missing_state():
    for status in ("NOT_YET_AVAILABLE", "VENUE_UNKNOWN", "NOT_CAPTURED", "MISSING"):
        html = weather_card(MatchWeather(status, available_from="28 Sep"))
        assert "°C" not in html
        assert len(html) > 60, status
    assert "28 Sep" in weather_card(MatchWeather("NOT_YET_AVAILABLE", available_from="28 Sep"))
