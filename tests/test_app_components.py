"""Tests for the viewer's HTML building blocks (no Streamlit needed)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from components import (  # noqa: E402
    ResultRow,
    TeamForm,
    badge,
    form_card,
    form_pills,
    match_hero,
    outcome_for,
    result_list,
    status_chips,
)


def team(**overrides) -> TeamForm:
    values = dict(
        name="Galatasaray SK",
        tla="GAL",
        sequence=["L"],
        matches_considered=1,
        points=0,
        goals_for=1,
        goals_against=3,
        days_rest=5,
        has_domestic_coverage=False,
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
    assert "last 1 match" in form_card(team())
    assert "last 5 matches" in form_card(team(matches_considered=5, sequence=list("WWDLW")))
    assert "no matches yet" in form_card(team(matches_considered=0, sequence=[]))


def test_missing_domestic_coverage_is_flagged():
    assert "Domestic league not in the free API tier" in form_card(team())
    assert "Domestic league" not in form_card(team(has_domestic_coverage=True))


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
