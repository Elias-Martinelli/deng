"""Tests for the Dagster definitions.

The claims under test are the ones ADR-002 rests on: one partition per logical
date, the schedule targets *today's* partition, only transient errors are
retried, and a scheduled run produces the same tables as the CLI.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

dg = pytest.importorskip("dagster", reason="orchestrator extra not installed")

from deng.ingestion.football_data_client import ApiError, RetryableApiError  # noqa: E402
from deng.orchestration.definitions import (  # noqa: E402
    PARTITIONS_START,
    daily_partitions,
    defs,
    refresh_cron,
    run_step,
)


def test_definitions_load_with_one_asset_per_table():
    keys = {"/".join(k.path) for k in defs.resolve_asset_graph().get_all_asset_keys()}
    assert keys == {
        "raw/football_data",
        "staging/matches",
        "staging/teams",
        "staging/standings",
        "curated/dim_team",
        "curated/fact_match",
        "curated/fact_team_match_form",
        "meta/dq_results",
        "raw/team_crests",
        "raw/open_meteo",
        "staging/weather_forecast",
        "curated/dim_venue",
        "curated/fact_match_weather",
        "curated/fact_match_prediction",
        "raw/odds_api",
        "staging/bookmaker_odds",
        "staging/odds_event_match",
        "curated/fact_bookmaker_odds",
    }


def test_odds_refresh_runs_on_its_own_unpartitioned_job():
    # A partitioned job cannot carry unpartitioned assets, and a quote belongs
    # to a minute, not a day - hence the second job and its interval schedule.
    job = defs.resolve_job_def("odds_refresh")
    assert job.partitions_def is None
    assert defs.resolve_schedule_def("odds_refresh_schedule").cron_schedule == "*/15 * * * *"
    assert refresh_cron(5) == "*/5 * * * *"
    assert refresh_cron(120) == "0 */2 * * *"


def test_partitions_start_before_the_league_phase():
    assert daily_partitions.get_first_partition_key() == PARTITIONS_START


def test_schedule_ingests_under_todays_date():
    # Dagster's default last partition is yesterday; with that, the 06:00 run
    # would store today's API state under yesterday's ingestion_date.
    schedule = defs.resolve_schedule_def("daily_pipeline_schedule")
    tick = datetime(2026, 9, 21, 6, 0, tzinfo=ZoneInfo("Europe/Zurich"))
    with dg.instance_for_test() as instance:
        context = dg.build_schedule_context(instance=instance, scheduled_execution_time=tick)
        requests = schedule.evaluate_tick(context).run_requests
    assert [r.partition_key for r in requests] == ["2026-09-21"]


def test_run_step_lets_transient_errors_through_for_the_retry_policy():
    def rate_limited():
        raise RetryableApiError(429, "too many requests")

    with pytest.raises(RetryableApiError):
        run_step("ingest", rate_limited)


def test_run_step_forbids_retries_for_permanent_errors():
    def forbidden():
        raise ApiError(403, "competition not in plan")

    with pytest.raises(dg.Failure) as caught:
        run_step("ingest", forbidden)
    assert caught.value.allow_retries is False
    assert "403" in caught.value.description


def test_run_step_fails_on_a_non_zero_exit_code():
    with pytest.raises(dg.Failure) as caught:
        run_step("dq", lambda: 1)
    assert caught.value.allow_retries is False


# --- against PostgreSQL ------------------------------------------------------


@pytest.fixture(autouse=True)
def _no_crest_downloads(monkeypatch):
    """Keep the job tests offline: the crest step is tested on its own."""
    from deng.ingestion.crests import CrestResult

    monkeypatch.setattr(
        "deng.orchestration.definitions.fetch_crests", lambda connection: CrestResult()
    )


def _execute(partition_key: str):
    job = defs.resolve_job_def("daily_pipeline")
    with dg.instance_for_test() as instance:
        return job.execute_in_process(
            partition_key=partition_key, instance=instance, raise_on_error=False
        )


def _scalar(connection, sql: str, params=()):
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchone()[0]


@pytest.mark.postgres
def test_scheduled_run_builds_every_table(connection, monkeypatch):
    monkeypatch.setenv("INGEST_SOURCE", "samples")
    result = _execute("2026-09-20")
    assert result.success
    counts = {
        "/".join(e.materialization.asset_key.path): e.materialization.metadata
        for e in result.get_asset_materialization_events()
    }
    assert counts["raw/football_data"]["payloads"].value == 4
    assert counts["curated/fact_match"]["row_count"].value == 144
    assert counts["curated/fact_team_match_form"]["row_count"].value == 288


@pytest.mark.postgres
def test_rerunning_a_partition_does_not_duplicate(connection, monkeypatch):
    monkeypatch.setenv("INGEST_SOURCE", "samples")
    assert _execute("2026-09-20").success
    assert _execute("2026-09-20").success
    raw_rows = _scalar(
        connection,
        "SELECT count(*) FROM raw.football_data WHERE ingestion_date = %s",
        ("2026-09-20",),
    )
    assert raw_rows == 4


@pytest.mark.postgres
def test_a_permanent_error_fails_the_run_without_retrying(connection, monkeypatch):
    # No API key is a configuration error: retrying cannot fix it. If the
    # classification regressed, the step would be queued for a retry instead.
    monkeypatch.setenv("INGEST_SOURCE", "api")
    monkeypatch.setenv("FOOTBALL_DATA_API_KEY", "")
    result = _execute("2026-09-20")
    assert not result.success
    retries = [e for e in result.all_events if e.event_type_value == "STEP_UP_FOR_RETRY"]
    assert retries == []
    transform_runs = _scalar(
        connection,
        "SELECT count(*) FROM meta.pipeline_runs WHERE status = 'SUCCESS' "
        "AND pipeline_name = 'transform_curated'",
    )
    assert transform_runs == 0, "transform must not run after a failed ingest"
