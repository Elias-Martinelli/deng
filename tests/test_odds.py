"""Odds ingestion without a database: request shape, quota, budget rules, name matching."""

from datetime import datetime, timedelta, timezone

import pytest

from deng.ingestion.football_data_client import ApiError, RetryableApiError
from deng.ingestion.odds import (
    Fixture,
    OddsRequest,
    Quota,
    fetch_odds,
    normalise,
    plan_fetch,
    read_samples,
    resolve_event,
    similarity,
)

UTC = timezone.utc
NOON = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)
KICKOFF = datetime(2026, 10, 13, 19, 0, tzinfo=UTC)
REQUEST = OddsRequest(sport="soccer_uefa_champs_league")


# --- request and response ---------------------------------------------------


def test_request_asks_for_the_1x2_market_in_decimal_odds():
    params = REQUEST.params()
    assert REQUEST.endpoint == "sports/soccer_uefa_champs_league/odds"
    assert params["markets"] == "h2h" and params["oddsFormat"] == "decimal"
    assert "apiKey" not in params, "the key is added at send time only"
    assert "bookmakers" not in params
    assert OddsRequest("x", bookmakers="pinnacle").params()["bookmakers"] == "pinnacle"


def test_quota_headers_are_parsed_and_tolerated_when_missing():
    quota = Quota.from_headers({"x-requests-remaining": "483", "x-requests-used": "17"})
    assert (quota.remaining, quota.used, quota.last) == (483, 17, None)
    assert Quota.from_headers({}) == Quota()
    assert Quota.from_headers({"x-requests-remaining": "n/a"}).remaining is None


class _Response:
    def __init__(self, status, body, headers=None):
        self.status_code, self._body, self.headers = status, body, headers or {}
        self.text = str(body)

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


class _Session:
    def __init__(self, response):
        self.response, self.calls = response, []

    def get(self, url, params, timeout):
        self.calls.append((url, params))
        return self.response


def test_the_stored_url_never_contains_the_key():
    session = _Session(_Response(200, [], {"x-requests-remaining": "10", "x-requests-last": "1"}))
    url, payload, quota = fetch_odds(session, "https://api.example/v4", "SECRET", REQUEST)
    assert session.calls[0][1]["apiKey"] == "SECRET", "the key is sent"
    assert "SECRET" not in url, "but never stored"
    assert url.startswith("https://api.example/v4/sports/soccer_uefa_champs_league/odds?")
    assert payload == [] and quota.remaining == 10 and quota.last == 1


def test_an_exhausted_quota_or_bad_key_is_a_permanent_error():
    # The API answers 401 for both; repeating it cannot help and would not
    # even cost a credit - it must not be queued for a retry.
    with pytest.raises(ApiError) as caught:
        fetch_odds(_Session(_Response(401, {"message": "quota reached"})), "u", "k", REQUEST)
    assert type(caught.value) is ApiError and "quota reached" in str(caught.value)


def test_rate_limit_and_server_errors_are_retryable():
    for status in (429, 503):
        with pytest.raises(RetryableApiError):
            fetch_odds(_Session(_Response(status, {})), "u", "k", REQUEST)


def test_a_non_list_payload_is_rejected():
    with pytest.raises(ApiError):
        fetch_odds(_Session(_Response(200, {"unexpected": True})), "u", "k", REQUEST)


def test_samples_carry_their_fetch_time_in_the_file_name():
    samples = read_samples(REQUEST)
    assert len(samples) == 2
    (_, first, first_at), (_, second, second_at) = samples
    assert first_at == datetime(2026, 9, 21, 12, 0, tzinfo=UTC)
    assert second_at == datetime(2026, 9, 22, 8, 0, tzinfo=UTC)
    assert len(first) == len(second) == 18
    assert {b["key"] for e in first for b in e["bookmakers"]} == {
        "pinnacle",
        "betsson",
        "williamhill",
        "onexbet",
    }


# --- the budget rules -------------------------------------------------------


def plan(**overrides):
    values = dict(
        now=NOON,
        has_key=True,
        last_fetch_at=None,
        last_remaining=None,
        reserve=50,
        refresh_minutes=15,
        watch_hours=48,
        kickoffs=[KICKOFF],
        force=False,
    )
    values.update(overrides)
    return plan_fetch(**values)


def test_no_key_means_no_fetch_ever():
    assert plan(has_key=False, force=True).fetch is False
    assert "ODDS_API_KEY" in plan(has_key=False).reason


def test_first_fetch_of_the_day_is_always_allowed():
    assert plan().fetch is True
    yesterday = NOON - timedelta(days=1)
    assert plan(last_fetch_at=yesterday, kickoffs=[]).fetch is True


def test_inside_the_watch_window_the_interval_applies():
    fetched = NOON - timedelta(minutes=10)
    denied = plan(last_fetch_at=fetched)
    assert denied.fetch is False and "interval is 15 min" in denied.reason
    allowed = plan(last_fetch_at=NOON - timedelta(minutes=16))
    assert allowed.fetch is True and "watch window" in allowed.reason


def test_outside_the_watch_window_only_the_daily_fetch_happens():
    far_away = NOON + timedelta(days=5)
    decision = plan(last_fetch_at=NOON - timedelta(hours=2), kickoffs=[far_away])
    assert decision.fetch is False and "no watched match within 48 h" in decision.reason
    # A match that already kicked off is not watched: no live model, no live fetch.
    in_play = plan(last_fetch_at=NOON - timedelta(hours=2), kickoffs=[NOON - timedelta(hours=1)])
    assert in_play.fetch is False


def test_the_quota_reserve_stops_fetching_except_one_probe_a_day():
    recent = NOON - timedelta(hours=3)
    stopped = plan(last_fetch_at=recent, last_remaining=50, force=True)
    assert stopped.fetch is False and "reserve" in stopped.reason
    probe = plan(last_fetch_at=NOON - timedelta(hours=25), last_remaining=12)
    assert probe.fetch is True and "probe" in probe.reason
    assert plan(last_fetch_at=recent, last_remaining=51, force=True).fetch is True


def test_force_ignores_window_and_interval():
    decision = plan(last_fetch_at=NOON - timedelta(minutes=1), kickoffs=[], force=True)
    assert decision.fetch is True and decision.reason == "forced"


# --- resolving bookmaker events to fixtures ------------------------------------


def test_names_are_compared_without_legal_forms_accents_or_case():
    assert normalise("FC Bayern München") == {"bayern", "munchen"}
    assert normalise("Paris Saint-Germain FC") == normalise("Paris Saint Germain")
    assert normalise("FK Bodø/Glimt") == normalise("Bodo/Glimt")
    assert normalise("FC Porto") == {"porto"}, "a name that is only a legal form keeps it"
    assert normalise("PSV") == {"psv"}


def test_similarity_is_one_when_one_name_contains_the_other():
    assert similarity(normalise("Bayern Munich"), normalise("Bayern")) == 1.0
    assert similarity(normalise("Inter Milan"), normalise("Inter")) == 1.0
    assert similarity(normalise("Manchester United"), normalise("Manchester City")) == 0.5
    assert similarity(normalise("Real Madrid"), normalise("Real Betis")) == 0.5


def fixture(match_id, home, away, kickoff=KICKOFF, aliases=()):
    return Fixture(
        match_id,
        kickoff,
        tuple(normalise(n) for n in home),
        tuple(normalise(n) for n in (*away, *aliases)),
    )


FIXTURES = [
    fixture(1, ("Manchester City FC", "Man City", "MCI"), ("Paris Saint-Germain FC", "PSG")),
    fixture(2, ("Manchester United FC", "Man United"), ("Club Atlético de Madrid", "Atleti")),
    fixture(3, ("Real Madrid CF", "Real Madrid"), ("FC Internazionale Milano", "Inter")),
    fixture(4, ("AS Roma", "Roma"), ("PAE AEK", "PAE AEK"), kickoff=KICKOFF - timedelta(hours=2)),
]


def test_an_event_is_resolved_by_kickoff_and_both_names():
    found = resolve_event("Manchester City", "Paris Saint Germain", KICKOFF, FIXTURES)
    assert found.match_id == 1 and found.confidence == 1.0
    assert resolve_event("Manchester United", "Atletico Madrid", KICKOFF, FIXTURES).match_id == 2
    assert resolve_event("Real Madrid", "Inter Milan", KICKOFF, FIXTURES).match_id == 3


def test_bookmakers_kickoff_may_differ_by_minutes_but_not_by_a_day():
    slavia = [fixture(4, ("AS Roma", "Roma"), ("SK Slavia Praha", "Slavia Praha"))]
    assert resolve_event("Roma", "Slavia Prague", KICKOFF, slavia).match_id is None, (
        "Prague/Praha needs an alias"
    )
    with_alias = [fixture(4, ("AS Roma",), ("SK Slavia Praha",), aliases=("Slavia Prague",))]
    shifted = KICKOFF - timedelta(minutes=15)
    assert resolve_event("Roma", "Slavia Prague", shifted, with_alias).match_id == 4
    next_day = KICKOFF + timedelta(days=1)
    assert resolve_event("Roma", "Slavia Prague", next_day, with_alias).match_id is None


def test_legal_forms_do_not_hide_a_match():
    # "PAE AEK" vs "AEK Athens": the legal form drops out, AEK remains.
    assert resolve_event("Roma", "AEK Athens", KICKOFF - timedelta(hours=2), FIXTURES).match_id == 4


def test_ambiguity_is_reported_not_guessed():
    twins = [
        fixture(10, ("Inter",), ("Milan",)),
        fixture(11, ("Inter",), ("Milan",)),
    ]
    found = resolve_event("Inter", "Milan", KICKOFF, twins)
    assert found.match_id is None and "ambiguous" in found.note
