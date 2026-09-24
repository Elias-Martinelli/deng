"""Odds against PostgreSQL: change history, fair probabilities, flags, idempotency.

The football samples are ingested first (fixtures and the model forecast), then
the two committed odds fetches are replayed - see data/sample/the-odds-api/README.md
for what the second fetch deliberately changes.
"""

from datetime import date, datetime, timedelta, timezone

import pytest

from deng.config import Settings
from deng.database import RawLoader
from deng.ingestion.odds import ingest_odds, match_events
from deng.ingestion.weather import load_venues
from deng.quality import run_checks
from deng.transformation import (
    ODDS_COUNTED_TABLES,
    ODDS_CURATED_ORDER,
    ODDS_STAGING_ORDER,
    WEATHER_COUNTED_TABLES,
    WEATHER_TRANSFORMATION_ORDER,
    run_transformations,
)

pytestmark = pytest.mark.postgres

FOOTBALL_DATE = date(2026, 9, 20)
UTC = timezone.utc
# Events the second sample fetch changes (see the sample README).
REPRICED = {575341, 575353, 575344}
WITHDRAWN = (575344, "onexbet")
INCOMPLETE = (575350, "betsson")


def settings(**overrides) -> Settings:
    values = dict(_env_file=None, odds_api_key="k", odds_quota_reserve=50)
    values.update(overrides)
    return Settings(**values)


@pytest.fixture
def football(connection, run_id, all_samples):
    loader = RawLoader(connection)
    for endpoint, payload in all_samples.items():
        loader.load(
            run_id=run_id,
            endpoint=endpoint,
            request_params={},
            request_url=f"https://api.football-data.org/v4/{endpoint}",
            payload=payload,
            ingestion_date=FOOTBALL_DATE,
        )
    connection.commit()
    run_transformations(connection, FOOTBALL_DATE)
    load_venues(connection)
    run_transformations(
        connection,
        FOOTBALL_DATE,
        order=WEATHER_TRANSFORMATION_ORDER,
        counted=WEATHER_COUNTED_TABLES,
    )


def odds_run(connection, run_id, **kwargs):
    result = ingest_odds(connection, run_id, settings(), **kwargs)
    run_transformations(connection, FOOTBALL_DATE, order=ODDS_STAGING_ORDER, counted=())
    result.events_matched, result.events_unmatched = match_events(connection)
    run_transformations(
        connection, FOOTBALL_DATE, order=ODDS_CURATED_ORDER, counted=ODDS_COUNTED_TABLES
    )
    return result


def rows(connection, sql, params=()):
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchall()


def scalar(connection, sql, params=()):
    return rows(connection, sql, params)[0][0]


@pytest.fixture
def replayed(connection, run_id, football):
    return odds_run(connection, run_id, from_samples=True)


def test_every_sample_event_is_resolved_to_a_fixture(connection, replayed):
    assert replayed.events_unmatched == []
    assert replayed.events_matched == 18
    methods = dict(
        rows(connection, "SELECT method, count(*) FROM staging.odds_event_match GROUP BY 1")
    )
    assert methods == {"NAME": 18}


def test_the_history_holds_one_row_per_quote_change(connection, replayed):
    # 18 events x 4 bookmakers at the first fetch; the second fetch adds a row
    # only where the quote changed: 3 repriced events (one of them minus the
    # withdrawn bookmaker) and one event with a moved timestamp.
    assert (
        scalar(connection, "SELECT count(*) FROM curated.fact_bookmaker_odds") == 72 + 4 + 4 + 3 + 4
    )
    unchanged = rows(
        connection,
        """
        SELECT min(first_seen_at), max(last_seen_at) FROM curated.fact_bookmaker_odds
         WHERE match_id NOT IN (575341, 575353, 575344, 575350)
        """,
    )[0]
    assert unchanged == (
        datetime(2026, 9, 21, 12, tzinfo=UTC),
        datetime(2026, 9, 22, 8, tzinfo=UTC),
    )
    repriced = rows(
        connection,
        "SELECT count(*) FROM curated.fact_bookmaker_odds "
        "WHERE match_id = 575341 AND bookmaker_key = 'pinnacle'",
    )[0][0]
    assert repriced == 2


def test_fair_probabilities_come_from_one_bookmakers_three_prices(connection, replayed):
    off = scalar(
        connection,
        """
        SELECT count(*) FROM curated.fact_bookmaker_odds
         WHERE is_complete AND (
               abs(home_prob_fair + draw_prob_fair + away_prob_fair - 1) >= 0.001
            OR abs(home_prob_fair
                   - (1 / home_price) / (1 / home_price + 1 / draw_price + 1 / away_price))
               > 0.0001
            OR overround <= 0)
        """,
    )
    assert off == 0


def test_suspended_and_withdrawn_quotes_are_flagged_not_dropped(connection, replayed):
    match_id, bookmaker = INCOMPLETE
    incomplete = rows(
        connection,
        "SELECT is_complete, away_price, home_prob_fair FROM curated.bookmaker_odds_latest "
        "WHERE match_id = %s AND bookmaker_key = %s",
        (match_id, bookmaker),
    )
    assert incomplete == [(False, None, None)]
    match_id, bookmaker = WITHDRAWN
    current = dict(
        rows(
            connection,
            "SELECT bookmaker_key, is_current FROM curated.bookmaker_odds_latest "
            "WHERE match_id = %s",
            (match_id,),
        )
    )
    assert current[bookmaker] is False and sum(current.values()) == 3


def test_comparison_keeps_model_and_odds_timestamps_apart(connection, replayed):
    row = rows(
        connection,
        """
        SELECT predicted_at, odds_fetched_at, source_updated_at, home_prob, home_model_odds,
               home_prob_fair, home_deviation_pp, is_pre_match
          FROM curated.odds_comparison_latest
         WHERE match_id = 575341 AND bookmaker_key = 'pinnacle'
        """,
    )[0]
    predicted_at, fetched_at, source_at, prob, model_odds, fair, deviation, pre_match = row
    assert fetched_at == datetime(2026, 9, 22, 8, tzinfo=UTC)
    assert source_at == datetime(2026, 9, 22, 7, 41, 12, tzinfo=UTC)
    assert predicted_at > fetched_at, "the forecast was computed now, the odds are the sample's"
    assert float(model_odds) == round(1 / float(prob), 2)
    assert float(deviation) == round((float(prob) - float(fair)) * 100, 1)
    assert pre_match is True


def test_replaying_the_samples_again_changes_nothing(connection, run_id, replayed):
    before = (
        scalar(connection, "SELECT count(*) FROM raw.odds_api"),
        scalar(connection, "SELECT count(*) FROM staging.bookmaker_odds"),
        scalar(connection, "SELECT count(*) FROM curated.fact_bookmaker_odds"),
    )
    odds_run(connection, run_id, from_samples=True)
    after = (
        scalar(connection, "SELECT count(*) FROM raw.odds_api"),
        scalar(connection, "SELECT count(*) FROM staging.bookmaker_odds"),
        scalar(connection, "SELECT count(*) FROM curated.fact_bookmaker_odds"),
    )
    assert before == after == (2, 2 * 18 * 4 * 3 - 3 - 1, 87)


def test_data_quality_passes_with_odds_and_forecasts(connection, run_id, replayed):
    results = run_checks(connection, run_id=run_id)
    failed = {r.check.name for r in results if not r.passed}
    assert not any(r.is_blocking for r in results), failed
    assert "odds_events_resolved_to_fixtures" not in failed
    assert "prediction_for_every_match" not in failed


# --- the API path, with a fake session --------------------------------------


class FakeResponse:
    def __init__(self, payload, remaining):
        self.status_code, self._payload, self.text = 200, payload, ""
        self.headers = {"x-requests-remaining": str(remaining), "x-requests-last": "1"}

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, remaining=400):
        self.calls, self.remaining = 0, remaining

    def get(self, url, params, timeout):
        self.calls += 1
        return FakeResponse([], self.remaining)


def test_a_reload_never_spends_a_credit_only_the_pipeline_does(connection, run_id, football):
    session = FakeSession()
    now = datetime(2026, 9, 22, 10, 0, tzinfo=UTC)
    first = ingest_odds(connection, run_id, settings(), session=session, now=now)
    assert first.plan.fetch and first.inserted and session.calls == 1
    assert first.quota.remaining == 400
    # Same day, no watched match within 48 h (matchday 2 is three weeks away):
    # a second run - or a hundred app reloads - costs nothing.
    again = ingest_odds(
        connection, run_id, settings(), session=session, now=now + timedelta(minutes=20)
    )
    assert again.plan.fetch is False and session.calls == 1
    forced = ingest_odds(
        connection, run_id, settings(), session=session, now=now + timedelta(minutes=21), force=True
    )
    assert forced.plan.fetch and session.calls == 2
    assert scalar(connection, "SELECT count(*) FROM raw.odds_api") == 2, "every real fetch is a row"


def test_the_quota_reserve_pauses_fetching_and_keeps_the_last_state(connection, run_id, football):
    session = FakeSession(remaining=50)
    now = datetime(2026, 9, 22, 10, 0, tzinfo=UTC)
    assert ingest_odds(connection, run_id, settings(), session=session, now=now).plan.fetch
    paused = ingest_odds(
        connection, run_id, settings(), session=session, now=now + timedelta(hours=1), force=True
    )
    assert paused.plan.fetch is False and "reserve" in paused.plan.reason
    assert session.calls == 1
    assert rows(connection, "SELECT requests_remaining FROM raw.odds_api") == [(50,)]


def test_without_a_key_the_step_skips_and_says_so(connection, run_id, football):
    session = FakeSession()
    result = ingest_odds(connection, run_id, settings(odds_api_key=""), session=session)
    assert result.plan.fetch is False and "ODDS_API_KEY" in result.summary
    assert session.calls == 0
