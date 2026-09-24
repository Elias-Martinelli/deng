"""Command-line entry point of the local pipeline.

    python -m deng.pipeline init                      prepare the schemas
    python -m deng.pipeline ingest                    ask all five sources, store the answers
    python -m deng.pipeline ingest --only weather     ask a single source
    python -m deng.pipeline transform                 raw -> staging -> curated (all of it)
    python -m deng.pipeline dq                        data-quality checks
    python -m deng.pipeline run                       ingest + transform + dq in one go
    python -m deng.pipeline backfill --from 2026-09-01 --to 2026-09-10
    python -m deng.pipeline verify                    run the verification queries

Three commands carry the pipeline, in this order: **ingest** asks every source
and stores the answers unchanged; **transform** builds every table from those
answers with SQL; **dq** judges the result. Nothing in ingest reads a table
that transform built - that is what lets the whole product be rebuilt from the
raw zone without asking an API again.

The Dagster assets (`deng.orchestration`) call exactly these entry points, so
what runs under the scheduler is the same code a reviewer can run by hand.
Nothing here knows about the orchestrator.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, timedelta

from deng.clock import pipeline_today
from deng.config import get_settings
from deng.database import PipelineRun, apply_sql_files, connect
from deng.ingestion import runner
from deng.quality import run_checks
from deng.transformation import (
    ODDS_COUNTED_TABLES,
    ODDS_CURATED_ORDER,
    ODDS_STAGING_ORDER,
    WEATHER_COUNTED_TABLES,
    WEATHER_TRANSFORMATION_ORDER,
    run_transformations,
)
from deng.transformation.odds_matching import match_events

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
        return command_ingest(
            args.date or pipeline_today(), from_samples=args.from_samples, only=args.only
        )
    if args.command == "backfill":
        return command_backfill(args.date_from, args.date_to, from_samples=args.from_samples)
    if args.command == "transform":
        return command_transform(args.date or pipeline_today())
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

    ingest = sub.add_parser("ingest", help="ask every source and store the answers (raw zone)")
    ingest.add_argument("--date", type=date.fromisoformat, help=DATE_HELP)
    ingest.add_argument(
        "--from-samples",
        action="store_true",
        help="use the committed sample payloads instead of calling the APIs (no key needed)",
    )
    ingest.add_argument(
        "--only",
        choices=runner.SOURCE_NAMES,
        help="ingest a single source instead of all of them",
    )

    backfill = sub.add_parser("backfill", help="re-run ingestion for a range of logical dates")
    backfill.add_argument("--from", dest="date_from", type=date.fromisoformat, required=True)
    backfill.add_argument("--to", dest="date_to", type=date.fromisoformat, required=True)
    backfill.add_argument("--from-samples", action="store_true", help="see `ingest --from-samples`")

    transform = sub.add_parser("transform", help="raw -> staging -> curated (all sources)")
    transform.add_argument("--date", type=date.fromisoformat, help=DATE_HELP)

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


def command_ingest(logical_date: date, from_samples: bool = False, only: str | None = None) -> int:
    """Ask every source and store every answer in the raw zone.

    Nothing is transformed here. That is the point: after this command the raw
    zone holds today's answers of all five sources, and the transformation can
    be re-run from them any time without asking an API again.

    Args:
        logical_date: The date this run is responsible for.
        from_samples: Replay the committed sample answers instead of calling the
            APIs, so a reviewer can run the pipeline without credentials.
        only: Run a single source (see `--only`), all of them by default.
    """
    settings = get_settings()
    try:
        with connect(settings) as connection:
            context = runner.Context(connection, logical_date, settings, from_samples)
            results = runner.ingest_all(context, only=only)
    except ValueError as exc:  # a missing API key, reported without a traceback
        print(f"ERROR: {exc}", file=sys.stderr)
        print("       or run with --from-samples to use the committed answers.", file=sys.stderr)
        return 1

    for result in results:
        print(f"  {result.source:<20} {result.summary}")
        for line in result.lines or []:
            print(f"      {line}")
    print(f"ingest for {logical_date}: OK")
    return 0


def command_transform(logical_date: date) -> int:
    """Build every table from the raw zone: staging, then curated.

    Three transactions, because two of them depend on the one before:

    1. football   raw -> staging.{matches,teams,standings} -> curated facts,
       the team form and the baseline forecast;
    2. weather    the stored OpenStreetMap answers -> staging.venues, the
       forecasts -> curated.fact_match_weather;
    3. odds       the stored bookmaker answers -> staging, then the event
       matcher (Python) pairs them with our fixtures, then curated.

    Each transaction either lands completely or not at all, so the tables are
    never half-built.
    """
    with connect() as connection:
        with PipelineRun(connection, "transform_curated", logical_date) as run:
            football = run_transformations(connection, logical_date)
            run.add_counts(loaded=football.total_rows_written)

        with PipelineRun(connection, "transform_weather", logical_date) as run:
            weather = run_transformations(
                connection,
                logical_date,
                order=WEATHER_TRANSFORMATION_ORDER,
                counted=WEATHER_COUNTED_TABLES,
            )
            run.add_counts(loaded=weather.total_rows_written)

        with PipelineRun(connection, "transform_odds", logical_date) as run:
            staged = run_transformations(
                connection, logical_date, order=ODDS_STAGING_ORDER, counted=()
            )
            matched, unmatched = match_events(connection)
            odds = run_transformations(
                connection,
                logical_date,
                order=ODDS_CURATED_ORDER,
                counted=ODDS_COUNTED_TABLES,
            )
            run.add_counts(loaded=staged.total_rows_written + odds.total_rows_written)

    for result in (football, weather, odds):
        for name, affected in result.statements:
            print(f"  {name:<44} {affected:>6} rows")
    print()
    for result in (football, weather, odds):
        for table, count in result.row_counts.items():
            print(f"  {table:<32} {count:>6} rows")
    print(f"  bookmaker events matched: {matched}, unmatched: {len(unmatched)}")
    for label in unmatched:
        print(f"    unmatched: {label} - add an alias to bookmaker_team_aliases.csv")
    print(f"transform for {logical_date}: OK")
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
    """Ingest every source, then transform, then check - the daily sequence."""
    print(f"=== ingest {logical_date} ===")
    code = command_ingest(logical_date, from_samples=from_samples)
    if code != 0:
        return code

    print(f"\n=== transform {logical_date} ===")
    code = command_transform(logical_date)
    if code != 0:
        return code

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
