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


# --- model forecast vs. bookmaker odds ---------------------------------------

from components import (  # noqa: E402
    OddsComparison,
    OutcomeRow,
    age_label,
    note,
    odds_comparison_card,
    odds_comparison_grid,
    odds_state_chip,
    signed_pp,
)


def comparison(**overrides) -> OddsComparison:
    values = dict(
        bookmaker="Pinnacle",
        state="CURRENT",
        model_label="22 Sep 14:00 CEST · form-poisson-v1",
        odds_label="22 Sep 14:05 CEST",
        fetched_label="22 Sep 14:20 CEST",
        age_label="12 min ago",
        outcomes=[
            OutcomeRow("Home win · Arsenal FC", 0.50, 2.10, 0.48),
            OutcomeRow("Draw", 0.28, 3.40, 0.30),
            OutcomeRow("Away win · Lille OSC", 0.22, 3.60, 0.22),
        ],
        overround=0.05,
    )
    values.update(overrides)
    return OddsComparison(**values)


def test_model_odds_are_one_over_the_probability():
    row = OutcomeRow("Home win", 0.5, 2.10, 0.48)
    assert row.model_odds == 2.0
    assert round(row.deviation_pp, 1) == 2.0
    assert OutcomeRow("Draw", 0.28).deviation_pp is None


def test_card_shows_both_timestamps_the_age_and_every_outcome():
    html = odds_comparison_card(comparison())
    assert "Model forecast: 22 Sep 14:00 CEST" in html
    assert "Odds: 22 Sep 14:05 CEST (bookmaker time)" in html
    assert "read 22 Sep 14:20 CEST, 12 min ago" in html
    for label in ("Home win · Arsenal FC", "Draw", "Away win · Lille OSC"):
        assert label in html
    assert "50 %" in html and "2.00" in html and "2.10" in html and "48 % fair" in html
    assert "+2.0 pp" in html and "−2.0 pp" in html and "±0.0 pp" in html
    assert "margin 5.0 %" in html


def test_deviation_is_called_a_model_deviation_not_an_edge():
    html = odds_comparison_card(comparison())
    assert "not a betting edge" in html and "edge" not in html.split("not a betting edge")[0]


def test_a_missing_price_is_shown_as_not_quoted():
    html = odds_comparison_card(
        comparison(state="INCOMPLETE", outcomes=[OutcomeRow("Draw", 0.28, None, None)])
    )
    assert "not quoted" in html and "incomplete" in html


def test_every_state_is_words_and_a_mark_not_colour_alone():
    for state in ("CURRENT", "STALE", "WITHDRAWN", "INCOMPLETE"):
        chip = odds_state_chip(state)
        assert "cl-chip" in chip and len(chip) > 40, state
    assert "not in the latest fetch" in odds_state_chip("WITHDRAWN")
    assert "cl-bad" in odds_state_chip("WITHDRAWN") and "cl-warn" in odds_state_chip("STALE")


def test_bookmaker_names_from_the_feed_cannot_inject_markup():
    html = odds_comparison_card(comparison(bookmaker="<b>x</b>"))
    assert "<b>x</b>" not in html and "&lt;b&gt;x&lt;/b&gt;" in html


def test_ages_use_the_coarsest_honest_unit():
    assert age_label(0.4) == "just now"
    assert age_label(12) == "12 min ago"
    assert age_label(180) == "3 h ago"
    assert age_label(3 * 1440) == "3 days ago"
    assert age_label(None) == "unknown age"


def test_signed_percentage_points_keep_the_sign():
    assert signed_pp(3.24) == "+3.2 pp" and signed_pp(-0.06) == "−0.1 pp"
    assert signed_pp(0) == "±0.0 pp" and signed_pp(None) == "–"


def test_grid_and_notes_wrap_their_content():
    assert odds_comparison_grid(["<i>a</i>", "<i>b</i>"]).count("<i>") == 2
    assert "cl-info" in note("x", "info") and "cl-info" not in note("x")
    assert "&lt;" in note("<x>")
