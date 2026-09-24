"""Command-line entry point of the local pipeline.

    python -m deng.pipeline init                      prepare the schemas
    python -m deng.pipeline ingest                    ingest for today
    python -m deng.pipeline ingest --date 2026-09-18  ingest for one logical date
    python -m deng.pipeline transform                 raw -> staging -> curated
    python -m deng.pipeline crests                    fetch club crests not stored yet
    python -m deng.pipeline weather                   forecasts for matches <= 16 days ahead
    python -m deng.pipeline odds                      bookmaker odds, if the budget rules allow
    python -m deng.pipeline dq                        data-quality checks
    python -m deng.pipeline run                       ingest + transform + dq in one go
    python -m deng.pipeline backfill --from 2026-09-01 --to 2026-09-10
    python -m deng.pipeline verify                    run the verification queries

The Dagster assets (`deng.orchestration`) call exactly these entry points, so
what runs under the scheduler is the same code a reviewer can run by hand.
Nothing here knows about the orchestrator.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, timedelta

from deng.config import get_settings
from deng.database import PipelineRun, RawLoader, apply_sql_files, connect
from deng.ingestion.crests import fetch_crests
from deng.ingestion.extract import fetch_endpoints, read_sample_endpoints
from deng.ingestion.football_data_client import ApiError, FootballDataClient
from deng.ingestion.odds import ingest_odds, match_events
from deng.ingestion.weather import ingest_weather, pipeline_today
from deng.quality import run_checks
from deng.transformation import (
    ODDS_COUNTED_TABLES,
    ODDS_CURATED_ORDER,
    ODDS_STAGING_ORDER,
    WEATHER_COUNTED_TABLES,
    WEATHER_TRANSFORMATION_ORDER,
    run_transformations,
)

logger = logging.getLogger(__name__)

# Exit codes follow the Unix convention the orchestrator and CI rely on:
#   0 success, 1 the step failed, 2 wrong usage (bad arguments).
# A non-zero exit is what makes a failed run visible to Dagster, `make` and CI.

# Name under which ingestion runs appear in meta.pipeline_runs.
PIPELINE_NAME = "ingest_football_raw"
DATE_HELP = "logical date (default: today in Europe/Zurich)"


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and dispatch to the requested command."""
    parser = build_parser()
    args = parser.parse_args(argv)
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
    )

    if args.command == "init":
        return command_init()
    if args.command == "ingest":
        return command_ingest(args.date or pipeline_today(), from_samples=args.from_samples)
    if args.command == "backfill":
        return command_backfill(args.date_from, args.date_to, from_samples=args.from_samples)
    if args.command == "transform":
        return command_transform(args.date or pipeline_today())
    if args.command == "weather":
        return command_weather(args.date or pipeline_today(), from_samples=args.from_samples)
    if args.command == "crests":
        return command_crests()
    if args.command == "odds":
        return command_odds(from_samples=args.from_samples, force=args.force)
    if args.command == "dq":
        return command_dq()
    if args.command == "run":
        return command_run(args.date or pipeline_today(), from_samples=args.from_samples)
    if args.command == "verify":
        return command_verify()
    parser.print_help()
    return 2


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser."""
    parser = argparse.ArgumentParser(prog="deng.pipeline", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="create schemas and tables (idempotent)")

    ingest = sub.add_parser("ingest", help="ingest raw payloads for one logical date")
    ingest.add_argument("--date", type=date.fromisoformat, help=DATE_HELP)
    ingest.add_argument(
        "--from-samples",
        action="store_true",
        help="use the committed sample payloads instead of calling the API (no key needed)",
    )

    backfill = sub.add_parser("backfill", help="re-run ingestion for a range of logical dates")
    backfill.add_argument("--from", dest="date_from", type=date.fromisoformat, required=True)
    backfill.add_argument("--to", dest="date_to", type=date.fromisoformat, required=True)
    backfill.add_argument("--from-samples", action="store_true", help="see `ingest --from-samples`")

    transform = sub.add_parser("transform", help="raw -> staging -> curated for one logical date")
    transform.add_argument("--date", type=date.fromisoformat, help=DATE_HELP)

    sub.add_parser("crests", help="fetch club crests that are not stored yet (incremental)")

    weather = sub.add_parser("weather", help="fetch and transform forecasts for one logical date")
    weather.add_argument("--date", type=date.fromisoformat, help=DATE_HELP)
    weather.add_argument("--from-samples", action="store_true", help="see `ingest --from-samples`")

    odds = sub.add_parser(
        "odds", help="fetch bookmaker odds if the budget rules allow, then transform"
    )
    odds.add_argument("--from-samples", action="store_true", help="see `ingest --from-samples`")
    odds.add_argument(
        "--force",
        action="store_true",
        help="fetch now regardless of the watch window and interval (still not into the reserve)",
    )

    sub.add_parser("dq", help="run the data-quality checks and persist the results")

    run = sub.add_parser("run", help="ingest, transform and check in one go")
    run.add_argument("--date", type=date.fromisoformat, help=DATE_HELP)
    run.add_argument("--from-samples", action="store_true", help="see `ingest --from-samples`")

    sub.add_parser("verify", help="run the verification queries and print the results")
    return parser


def command_init() -> int:
    """Apply the DDL. Safe to run repeatedly."""
    with connect() as connection:
        applied = apply_sql_files(connection)
    print(f"applied {len(applied)} SQL file(s): {', '.join(applied)}")
    return 0


def command_ingest(logical_date: date, from_samples: bool = False) -> int:
    """Fetch every daily endpoint and store the payloads in the raw zone.

    One run row is written per execution. Every payload is loaded with the
    idempotent upsert, so a second run for the same date updates in place.

    Args:
        logical_date: The date this run is responsible for.
        from_samples: Read the committed sample payloads instead of calling the
            API. Lets a reviewer exercise the pipeline without credentials.
    """
    settings = get_settings()
    # `source` is part of the raw zone's unique key, so replayed samples live in
    # their own rows and can never overwrite a real API answer for the same day
    # (and vice versa). Staging takes the newest payload of the day.
    source_name = "football-data.org" if not from_samples else "football-data.org (sample)"

    if from_samples:
        responses = read_sample_endpoints(settings.football_data_competition)
    else:
        try:
            api_key = settings.require_football_api_key()
        except ValueError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            print(
                "       or run with --from-samples to use the committed payloads.", file=sys.stderr
            )
            # A configuration error, reported as exit 1 rather than a traceback;
            # Dagster turns it into a non-retryable failure (run_step).
            return 1
        client = FootballDataClient(api_key=api_key, base_url=settings.football_data_base_url)
        responses = fetch_endpoints(client, settings.football_data_competition)

    with connect(settings) as connection:
        with PipelineRun(connection, PIPELINE_NAME, logical_date) as run:
            loader = RawLoader(connection, source=source_name)
            try:
                for endpoint, response in responses:
                    result = loader.load(
                        run_id=run.run_id,
                        endpoint=endpoint.path.format(code=settings.football_data_competition),
                        request_params=endpoint.params,
                        request_url=response.url,
                        payload=response.payload,
                        ingestion_date=logical_date,
                    )
                    run.add_counts(
                        extracted=result.record_count or 0,
                        loaded=1 if result.inserted else 0,
                        updated=1 if result.updated else 0,
                    )
                    print(
                        f"  {endpoint.name:<12} {result.action:<9} "
                        f"records={result.record_count} hash={result.payload_hash[:12]}"
                    )
                # One commit for all endpoints of the day: either the whole day's
                # snapshot is stored or none of it. A half-stored day (teams but
                # no matches) would let the transformation build an inconsistent
                # curated state.
                connection.commit()
            except ApiError:
                # Covers RetryableApiError too (subclass). Roll back this day's
                # partial writes, then re-raise so PipelineRun records FAILED
                # and the orchestrator can decide whether to retry.
                connection.rollback()
                raise

    print(f"ingest for {logical_date}: OK")
    return 0


def command_transform(logical_date: date) -> int:
    """Run the SQL transformations for one logical date."""
    with connect() as connection:
        with PipelineRun(connection, "transform_curated", logical_date) as run:
            result = run_transformations(connection, logical_date)
            run.add_counts(loaded=result.total_rows_written)
    for name, affected in result.statements:
        print(f"  {name:<44} {affected:>6} rows")
    print()
    for table, count in result.row_counts.items():
        print(f"  {table:<32} {count:>6} rows")
    print(f"transform for {logical_date}: OK")
    return 0


def command_weather(logical_date: date, from_samples: bool = False) -> int:
    """Fetch forecasts for matches inside the horizon, then build the weather tables.

    Runs after the football transformation: which matches need a forecast is
    read from curated.fact_match. The transformation runs even when nothing was
    fetched, because every match still gets its weather status.
    """
    settings = get_settings()
    with connect(settings) as connection:
        with PipelineRun(connection, "ingest_weather", logical_date) as run:
            result = ingest_weather(
                connection,
                logical_date,
                run.run_id,
                settings.open_meteo_forecast_url,
                from_samples=from_samples,
            )
            run.add_counts(loaded=len(result.stored))
        print(f"  weather {result.summary}")
        with PipelineRun(connection, "transform_weather", logical_date) as run:
            transformed = run_transformations(
                connection,
                logical_date,
                order=WEATHER_TRANSFORMATION_ORDER,
                counted=WEATHER_COUNTED_TABLES,
            )
            run.add_counts(loaded=transformed.total_rows_written)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT weather_status, count(*) FROM curated.fact_match_weather "
                "GROUP BY 1 ORDER BY 1"
            )
            for status, count in cursor.fetchall():
                print(f"  {status:<18} {count:>4} matches")
    print(f"weather for {logical_date}: OK")
    return 0


def command_crests() -> int:
    """Store missing club crests. Best effort: failures are reported, not fatal.

    Returns 0 even when single downloads fail - a missing crest is a cosmetic
    gap the viewer covers with the team code, and the `every_team_has_a_crest`
    WARNING check keeps it visible. Only a database error fails this step.
    """
    with connect() as connection:
        with PipelineRun(connection, "fetch_crests", pipeline_today()) as run:
            result = fetch_crests(connection, run_id=run.run_id)
            run.add_counts(loaded=len(result.fetched))
    for team_id, reason in result.failed.items():
        print(f"  team {team_id}: {reason}")
    print(f"crests: {result.summary}")
    return 0


def command_odds(from_samples: bool = False, force: bool = False, best_effort: bool = False) -> int:
    """Fetch bookmaker odds when the budget rules allow, then build the odds tables.

    The fetch decision (daily baseline, interval inside the watch window, quota
    reserve) is taken here in the pipeline and nowhere else: the app only reads
    tables, so reloading it can never spend a credit. The transformation runs
    even when nothing was fetched, so a fetch that was stored but not yet
    staged (e.g. after a crash) is picked up.

    Args:
        from_samples: Replay the committed sample fetches (no key needed).
        force: Fetch regardless of window and interval.
        best_effort: Report an API failure and return 0 instead of 1 - used by
            `run`, where a third-party odds outage must not fail the football
            pipeline. The failed run is still recorded in meta.pipeline_runs.
    """
    settings = get_settings()
    today = pipeline_today()
    try:
        with connect(settings) as connection:
            with PipelineRun(connection, "ingest_odds", today) as run:
                result = ingest_odds(
                    connection, run.run_id, settings, from_samples=from_samples, force=force
                )
                run.add_counts(extracted=result.event_count, loaded=1 if result.inserted else 0)
            with PipelineRun(connection, "transform_odds", today) as run:
                staged = run_transformations(
                    connection, today, order=ODDS_STAGING_ORDER, counted=()
                )
                result.events_matched, result.events_unmatched = match_events(connection)
                curated = run_transformations(
                    connection, today, order=ODDS_CURATED_ORDER, counted=ODDS_COUNTED_TABLES
                )
                run.add_counts(loaded=staged.total_rows_written + curated.total_rows_written)
    except ApiError as exc:
        # Covers RetryableApiError too. The PipelineRun above already recorded
        # the failure with this message.
        print(f"ERROR: odds fetch failed: {exc}", file=sys.stderr)
        return 0 if best_effort else 1
    print(f"  odds {result.summary}")
    for label in result.events_unmatched:
        print(f"  unmatched event: {label} - add an alias to bookmaker_team_aliases.csv")
    for table, count in curated.row_counts.items():
        print(f"  {table:<32} {count:>6} rows")
    print("odds: OK")
    return 0


def command_dq(run_id=None) -> int:
    """Run the data-quality checks; non-zero exit when a CRITICAL check fails."""
    with connect() as connection:
        results = run_checks(connection, run_id=run_id)

    width = max(len(r.check.name) for r in results)
    blocking = 0
    for result in results:
        status = "PASS" if result.passed else "FAIL"
        if result.is_blocking:
            blocking += 1
        print(
            f"  [{status}] {result.check.name:<{width}}  {result.check.severity:<8} "
            f"{result.observed}"
        )
    passed = sum(1 for r in results if r.passed)
    print(f"\ndata quality: {passed}/{len(results)} checks passed", end="")
    print(f", {blocking} CRITICAL failure(s)" if blocking else "")
    return 1 if blocking else 0


def command_run(logical_date: date, from_samples: bool = False) -> int:
    """Ingest, transform and check - the sequence the orchestrator schedules daily."""
    # The order is a dependency chain, not a preference: transform reads what
    # ingest stored, crests, weather and odds read what transform built, and the
    # checks judge the finished state. Each step stops the chain on failure -
    # except crests and odds, which are best effort (third-party extras).
    print(f"=== ingest {logical_date} ===")
    code = command_ingest(logical_date, from_samples=from_samples)
    if code != 0:
        return code

    print(f"\n=== transform {logical_date} ===")
    code = command_transform(logical_date)
    if code != 0:
        return code

    print("\n=== crests ===")
    command_crests()

    print(f"\n=== weather {logical_date} ===")
    code = command_weather(logical_date, from_samples=from_samples)
    if code != 0:
        return code

    print("\n=== odds ===")
    command_odds(from_samples=from_samples, best_effort=True)

    print("\n=== data quality ===")
    code = command_dq()
    if code != 0:
        # The transformation itself was consistent; the data it produced is not.
        # Failing here is the point: a scheduled run must not report success.
        print("\nrun FAILED: a CRITICAL data-quality check did not pass", file=sys.stderr)
        return code

    print(f"\nrun for {logical_date}: OK")
    return 0


def command_backfill(date_from: date, date_to: date, from_samples: bool = False) -> int:
    """Re-run ingestion for every logical date in a closed range.

    Note the honest limitation: the API always answers with *today's* state, so
    a backfill re-labels current data under past logical dates rather than
    recovering what the API said back then. It is the right mechanism for
    recovering missed runs and for re-processing, and it is documented as such
    (see docs/architecture/architecture-v0.2.md once written).
    """
    if date_from > date_to:
        print("ERROR: --from must not be after --to", file=sys.stderr)
        return 2  # usage error, see the exit-code convention at the top
    current = date_from
    failures = 0
    while current <= date_to:
        print(f"\n=== backfill {current} ===")
        try:
            if command_ingest(current, from_samples=from_samples) != 0:
                failures += 1
        except Exception as exc:  # noqa: BLE001 - one bad day must not stop the range
            failures += 1
            logger.error("backfill failed for %s: %s", current, exc)
        current += timedelta(days=1)
    total = (date_to - date_from).days + 1
    print(f"\nbackfill finished: {total - failures}/{total} dates succeeded")
    return 1 if failures else 0


def command_verify() -> int:
    """Run the verification queries in `sql/verify/` and print their results."""
    from deng.database.connection import _find_sql_dir

    verify_dir = _find_sql_dir() / "verify"
    files = sorted(verify_dir.glob("*.sql"))
    if not files:
        print("no verification queries found", file=sys.stderr)
        return 1

    failures = 0
    with connect() as connection, connection.cursor() as cursor:
        for path in files:
            print(f"\n=== {path.name} ===")
            cursor.execute(path.read_text())
            columns = [c.name for c in cursor.description or []]
            rows = cursor.fetchall()
            print("  " + " | ".join(columns))
            for row in rows:
                print("  " + " | ".join(str(v) for v in row))
            # Convention: a verification query may expose a boolean column
            # named `passed`; False anywhere means the check failed.
            if "passed" in columns:
                index = columns.index("passed")
                if any(row[index] is False for row in rows):
                    failures += 1
                    print("  -> FAILED")
    print(f"\nverification: {len(files) - failures}/{len(files)} queries passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
