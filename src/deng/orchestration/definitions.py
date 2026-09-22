"""The daily pipeline as Dagster assets.

    raw.football_data -> staging.{matches,teams,standings} -> curated.*  --+
    curated.dim_team   -> raw.team_crests                                  +--> meta.dq_results
    curated.fact_match -> raw.open_meteo -> staging/curated weather      --+

Every asset is one of our tables, and every partition is one logical date: the
`ingestion_date` in the raw zone, the `%(logical_date)s` the transformations
receive, the `--date` the CLI takes. A backfill is therefore "materialise these
partitions" and needs no loop of our own.

The assets call the same functions as `python -m deng.pipeline`, so a scheduled
run executes exactly the code a reviewer can run by hand. Dagster adds the
schedule, the dependency order, retries, partition status and run history.

Backfilling older partitions is safe while newer ones exist: the staging
upserts only overwrite a row when the incoming `ingestion_date` is at least as
new (`sql/transform/11x`), so reprocessing 10 September cannot roll the curated
tables back from 20 September to 10 September.
"""

# Unlike every other module, no `from __future__ import annotations` here:
# Dagster inspects the type of the `context` parameter at import time and
# rejects it when annotations are postponed strings.
from collections.abc import Callable
from datetime import date
from typing import Any

import dagster as dg
import psycopg
from dagster import AssetExecutionContext

from deng import pipeline
from deng.config import get_settings
from deng.database import PipelineRun, connect
from deng.ingestion.crests import fetch_crests
from deng.ingestion.football_data_client import ApiError, RetryableApiError
from deng.ingestion.weather import ingest_weather
from deng.quality import run_checks
from deng.transformation import (
    WEATHER_COUNTED_TABLES,
    WEATHER_TRANSFORMATION_ORDER,
    run_transformations,
)

# The 2026/27 league phase starts in mid-September; the first partition sits
# before it so that the whole season is backfillable.
PARTITIONS_START = "2026-09-01"
TIMEZONE = "Europe/Zurich"

# end_offset=1 makes *today* a partition. Without it Dagster's last partition is
# yesterday, and the 06:00 run would ingest today's API state under yesterday's
# date - the opposite of what `ingestion_date` means everywhere else.
daily_partitions = dg.DailyPartitionsDefinition(
    start_date=PARTITIONS_START, timezone=TIMEZONE, end_offset=1
)

# Errors that can succeed on a later attempt: rate limit, API 5xx, network, and
# a database that is restarting or not yet accepting connections.
TRANSIENT_ERRORS: tuple[type[BaseException], ...] = (
    RetryableApiError,
    psycopg.OperationalError,
)

# The client already retries single requests a few seconds apart. This policy
# covers the longer outages: a minute, then two, then four. It applies only to
# TRANSIENT_ERRORS because `run_step` turns everything else into a Failure that
# forbids retries - repeating a 403 or a failed data-quality check changes
# nothing except the request budget spent.
TRANSIENT_RETRY = dg.RetryPolicy(
    max_retries=3,
    delay=60,
    backoff=dg.Backoff.EXPONENTIAL,
    jitter=dg.Jitter.PLUS_MINUS,
)

RAW = dg.AssetKey(["raw", "football_data"])
STAGING_MATCHES = dg.AssetKey(["staging", "matches"])
STAGING_TEAMS = dg.AssetKey(["staging", "teams"])
STAGING_STANDINGS = dg.AssetKey(["staging", "standings"])
DIM_TEAM = dg.AssetKey(["curated", "dim_team"])
FACT_MATCH = dg.AssetKey(["curated", "fact_match"])
FACT_TEAM_MATCH_FORM = dg.AssetKey(["curated", "fact_team_match_form"])
DQ_RESULTS = dg.AssetKey(["meta", "dq_results"])
TEAM_CRESTS = dg.AssetKey(["raw", "team_crests"])
RAW_WEATHER = dg.AssetKey(["raw", "open_meteo"])
STAGING_WEATHER = dg.AssetKey(["staging", "weather_forecast"])
DIM_VENUE = dg.AssetKey(["curated", "dim_venue"])
FACT_MATCH_WEATHER = dg.AssetKey(["curated", "fact_match_weather"])

WEATHER_SPECS: tuple[dg.AssetSpec, ...] = (
    dg.AssetSpec(STAGING_WEATHER, deps=[RAW_WEATHER], group_name="staging"),
    dg.AssetSpec(DIM_VENUE, deps=[DIM_TEAM], group_name="curated"),
    dg.AssetSpec(
        FACT_MATCH_WEATHER, deps=[STAGING_WEATHER, DIM_VENUE, FACT_MATCH], group_name="curated"
    ),
)

# Mirrors the table dependencies in sql/transform/. Used only for lineage in the
# UI - the execution order inside the transformation is TRANSFORMATION_ORDER.
MODEL_SPECS: tuple[dg.AssetSpec, ...] = (
    dg.AssetSpec(STAGING_MATCHES, deps=[RAW], group_name="staging"),
    dg.AssetSpec(STAGING_TEAMS, deps=[RAW], group_name="staging"),
    dg.AssetSpec(STAGING_STANDINGS, deps=[RAW], group_name="staging"),
    dg.AssetSpec(DIM_TEAM, deps=[STAGING_TEAMS], group_name="curated"),
    dg.AssetSpec(FACT_MATCH, deps=[STAGING_MATCHES, DIM_TEAM], group_name="curated"),
    dg.AssetSpec(FACT_TEAM_MATCH_FORM, deps=[FACT_MATCH], group_name="curated"),
)


def run_step(name: str, step: Callable[..., int], *args: Any, **kwargs: Any) -> None:
    """Call a CLI command and translate its outcome for Dagster.

    Transient errors propagate unchanged, so the asset's RetryPolicy applies.
    Any other exception, and any non-zero exit code, becomes a `Failure` with
    `allow_retries=False`: the run fails at once and says why.

    Raises:
        dg.Failure: on a permanent error or a non-zero exit code.
    """
    try:
        code = step(*args, **kwargs)
    except TRANSIENT_ERRORS:
        raise
    except Exception as exc:
        raise dg.Failure(
            description=f"{name} failed permanently: {type(exc).__name__}: {exc}",
            allow_retries=False,
        ) from exc
    if code != 0:
        raise dg.Failure(
            description=f"{name} exited with code {code} - see the step log for the reason",
            allow_retries=False,
        )


def _logical_date(context: AssetExecutionContext) -> date:
    # The partition key ("2026-09-21") *is* the logical date: the bridge
    # between Dagster's partitions and the `--date` of the CLI.
    return date.fromisoformat(context.partition_key)


def _count(table: str, where: str = "", params: tuple[Any, ...] = ()) -> int:
    # Row counts become asset metadata in the UI - a quick plausibility check
    # per run ("fact_match 144") without opening psql. `table` only ever comes
    # from the asset keys defined above, never from user input, so the
    # f-string is safe; values go through `params`.
    with connect() as connection, connection.cursor() as cursor:
        cursor.execute(f"SELECT count(*) FROM {table} {where}", params)  # noqa: S608 - literals
        row = cursor.fetchone()
    return int(row[0]) if row else 0


@dg.asset(
    key=RAW,
    partitions_def=daily_partitions,
    retry_policy=TRANSIENT_RETRY,
    group_name="raw",
    kinds={"postgres"},
    description=(
        "One JSONB payload per endpoint and logical date from football-data.org "
        "(or the committed samples when INGEST_SOURCE=samples). Idempotent upsert."
    ),
)
def raw_football_data(context: AssetExecutionContext) -> dg.MaterializeResult:
    """Apply the DDL (idempotent) and ingest every daily endpoint for the partition."""
    logical_date = _logical_date(context)
    source = get_settings().ingest_source
    # The DDL runs first so the very first run on an empty volume works without
    # a separate `make init`; on every later run it is a no-op.
    run_step("init", pipeline.command_init)
    run_step(
        "ingest",
        pipeline.command_ingest,
        logical_date,
        from_samples=source == "samples",
    )
    payloads = _count("raw.football_data", "WHERE ingestion_date = %s", (logical_date,))
    return dg.MaterializeResult(
        metadata={"logical_date": str(logical_date), "source": source, "payloads": payloads}
    )


@dg.multi_asset(
    specs=MODEL_SPECS,
    partitions_def=daily_partitions,
    retry_policy=TRANSIENT_RETRY,
    can_subset=False,
    description="raw -> staging -> curated in one transaction (sql/transform/).",
)
def curated_model(context: AssetExecutionContext):
    """Run the SQL transformations for the partition's logical date."""
    run_step("transform", pipeline.command_transform, _logical_date(context))
    for spec in MODEL_SPECS:
        table = ".".join(spec.key.path)
        yield dg.MaterializeResult(asset_key=spec.key, metadata={"row_count": _count(table)})


@dg.asset(
    key=TEAM_CRESTS,
    deps=[DIM_TEAM],
    partitions_def=daily_partitions,
    retry_policy=TRANSIENT_RETRY,
    group_name="raw",
    kinds={"postgres"},
    description=(
        "Club crest images, fetched once per crest URL. Best effort: a failed download is "
        "reported, not fatal - the viewer falls back to the team code."
    ),
)
def team_crests(context: AssetExecutionContext) -> dg.MaterializeResult:
    """Store the crests that are not stored yet (usually none after the first run)."""
    with connect() as connection:
        result = fetch_crests(connection)
    for team_id, reason in result.failed.items():
        context.log.warning("crest for team %s not stored: %s", team_id, reason)
    return dg.MaterializeResult(
        metadata={"fetched": len(result.fetched), "failed": len(result.failed)}
    )


@dg.asset(
    key=RAW_WEATHER,
    deps=[FACT_MATCH],
    partitions_def=daily_partitions,
    retry_policy=TRANSIENT_RETRY,
    group_name="raw",
    kinds={"postgres"},
    description=(
        "Open-Meteo forecasts for venues hosting a match within 16 days. Only fetched for "
        "today's partition: for a past date the answer would not be a forecast."
    ),
)
def raw_open_meteo(context: AssetExecutionContext) -> dg.MaterializeResult:
    """Load the venues and fetch today's forecasts."""
    settings = get_settings()
    logical_date = _logical_date(context)
    with connect(settings) as connection:
        with PipelineRun(connection, "ingest_weather", logical_date) as run:
            try:
                result = ingest_weather(
                    connection,
                    logical_date,
                    run.run_id,
                    settings.open_meteo_forecast_url,
                    from_samples=settings.ingest_source == "samples",
                )
            except TRANSIENT_ERRORS:
                raise
            except ApiError as exc:
                raise dg.Failure(description=f"weather: {exc}", allow_retries=False) from exc
            run.add_counts(loaded=len(result.stored))
    if result.skipped_reason:
        context.log.info("weather fetch skipped: %s", result.skipped_reason)
    return dg.MaterializeResult(
        metadata={"planned": result.planned, "stored": len(result.stored), "note": result.summary}
    )


@dg.multi_asset(
    specs=WEATHER_SPECS,
    partitions_def=daily_partitions,
    retry_policy=TRANSIENT_RETRY,
    can_subset=False,
    description="Forecast unpacking, dim_venue and fact_match_weather in one transaction.",
)
def weather_model(context: AssetExecutionContext):
    """Build the weather tables; every match gets a weather status."""
    try:
        with connect() as connection:
            with PipelineRun(connection, "transform_weather", _logical_date(context)) as run:
                result = run_transformations(
                    connection,
                    _logical_date(context),
                    order=WEATHER_TRANSFORMATION_ORDER,
                    counted=WEATHER_COUNTED_TABLES,
                )
                run.add_counts(loaded=result.total_rows_written)
    except TRANSIENT_ERRORS:
        raise
    except Exception as exc:
        raise dg.Failure(description=f"weather transform: {exc}", allow_retries=False) from exc
    for spec in WEATHER_SPECS:
        table = ".".join(spec.key.path)
        yield dg.MaterializeResult(asset_key=spec.key, metadata={"row_count": _count(table)})


@dg.asset(
    key=DQ_RESULTS,
    deps=[FACT_MATCH, FACT_TEAM_MATCH_FORM, DIM_TEAM, TEAM_CRESTS, FACT_MATCH_WEATHER],
    partitions_def=daily_partitions,
    retry_policy=TRANSIENT_RETRY,
    group_name="quality",
    kinds={"postgres"},
    description="The data-quality checks, persisted to meta.dq_results. CRITICAL fails the run.",
)
def data_quality(context: AssetExecutionContext) -> dg.MaterializeResult:
    """Run every check; a CRITICAL failure fails the run, a WARNING only shows up."""
    try:
        with connect() as connection:
            results = run_checks(connection)
    except TRANSIENT_ERRORS:
        raise
    failed = [r for r in results if not r.passed]
    blocking = [r for r in failed if r.is_blocking]
    for result in failed:
        context.log.warning(
            "%s check %s failed: %s", result.check.severity, result.check.name, result.observed
        )
    metadata = {
        "checks": len(results),
        "passed": len(results) - len(failed),
        "failed": ", ".join(r.check.name for r in failed) or "none",
    }
    if blocking:
        raise dg.Failure(
            description=f"{len(blocking)} CRITICAL data-quality check(s) failed: "
            + ", ".join(r.check.name for r in blocking),
            metadata=metadata,
            allow_retries=False,
        )
    return dg.MaterializeResult(metadata=metadata)


daily_pipeline = dg.define_asset_job(
    name="daily_pipeline",
    selection=dg.AssetSelection.assets(
        raw_football_data, curated_model, team_crests, raw_open_meteo, weather_model, data_quality
    ),
    partitions_def=daily_partitions,
    description="ingest -> transform -> crests -> weather -> data quality for one logical date.",
)

# 06:00 Zurich: late enough that the previous evening's matches are final in
# the API, early enough that the day's fixtures are current before kick-off.
daily_schedule = dg.build_schedule_from_partitioned_job(
    daily_pipeline,
    hour_of_day=6,
    minute_of_hour=0,
    default_status=dg.DefaultScheduleStatus.RUNNING,
)

defs = dg.Definitions(
    assets=[
        raw_football_data,
        curated_model,
        team_crests,
        raw_open_meteo,
        weather_model,
        data_quality,
    ],
    jobs=[daily_pipeline],
    schedules=[daily_schedule],
)
