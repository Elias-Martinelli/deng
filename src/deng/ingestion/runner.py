"""The ingestion: ask every source, store every answer, record the run.

This is the whole of step 1 of the pipeline. It runs before any SQL, and the
order below is the order of the sources - nothing here transforms anything.

    1. football-data.org   fixtures, results, teams, standings
    2. openstreetmap.org   stadium coordinates (only clubs we have not asked about)
    3. crest images        club logos (only URLs we have not fetched)
    4. open-meteo.com      forecasts for matches inside the 16-day horizon
    5. the-odds-api.com    bookmaker odds, if the credit budget allows

Why football first: three later sources need to know which matches and clubs
exist. They read that from the raw zone - the answer this very run stored -
never from a table the transformation builds (tests/test_layering.py).

Best effort: crests and odds are extras from third parties. A failure there is
reported and recorded, but it does not fail the run; the football data, which
everything else rests on, does fail it.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

import psycopg

from deng.config import Settings
from deng.database import PipelineRun
from deng.sources import club_crests, football_data, open_meteo, openstreetmap, the_odds_api
from deng.sources.http import ApiError

logger = logging.getLogger(__name__)


@dataclass
class Context:
    """Everything a source needs to know about this run."""

    connection: psycopg.Connection
    logical_date: date
    settings: Settings
    from_samples: bool = False


@dataclass
class StepResult:
    """What one source did in this run."""

    source: str
    summary: str
    failed: bool = False
    lines: list[str] | None = None


def _football(context: Context, run_id) -> StepResult:
    result = football_data.ingest(
        context.connection,
        context.logical_date,
        run_id,
        context.settings,
        from_samples=context.from_samples,
    )
    return StepResult("football-data.org", result.summary, lines=result.lines)


def _openstreetmap(context: Context, run_id) -> StepResult:
    stored = openstreetmap.ingest(
        context.connection,
        context.logical_date,
        run_id,
        from_samples=context.from_samples,
    )
    return StepResult("openstreetmap.org", f"{stored} stadium(s) looked up")


def _crests(context: Context, run_id) -> StepResult:
    result = club_crests.fetch_crests(context.connection, run_id=run_id)
    return StepResult("club crests", result.summary)


def _weather(context: Context, run_id) -> StepResult:
    result = open_meteo.ingest_weather(
        context.connection,
        context.logical_date,
        run_id,
        context.settings.open_meteo_forecast_url,
        from_samples=context.from_samples,
    )
    return StepResult("open-meteo.com", result.summary)


def _odds(context: Context, run_id) -> StepResult:
    result = the_odds_api.ingest_odds(
        context.connection,
        run_id,
        context.settings,
        from_samples=context.from_samples,
    )
    return StepResult("the-odds-api.com", result.summary)


@dataclass(frozen=True)
class Step:
    """One source in the ingestion, in the order it runs."""

    name: str  # what --only takes
    pipeline_name: str  # what the run log calls it
    run: Callable[[Context, object], StepResult]
    best_effort: bool = False


STEPS: tuple[Step, ...] = (
    Step("football", "ingest_football_raw", _football),
    Step("openstreetmap", "ingest_osm_venues", _openstreetmap),
    Step("crests", "fetch_crests", _crests, best_effort=True),
    Step("weather", "ingest_weather", _weather),
    Step("odds", "ingest_odds", _odds, best_effort=True),
)

SOURCE_NAMES = tuple(step.name for step in STEPS)


def ingest_all(context: Context, only: str | None = None) -> list[StepResult]:
    """Run the sources in order and return what each of them did.

    Args:
        context: Connection, logical date, settings and the samples switch.
        only: Run a single source by name (see SOURCE_NAMES); all of them by default.

    Returns:
        One result per source that ran, in order.

    Raises:
        ApiError: from a source that is not best effort, after its run row has
            been recorded as FAILED.
    """
    results: list[StepResult] = []
    for step in STEPS:
        if only and step.name != only:
            continue
        try:
            with PipelineRun(context.connection, step.pipeline_name, context.logical_date) as run:
                results.append(step.run(context, run.run_id))
        except ApiError as exc:
            if not step.best_effort:
                raise
            logger.warning("%s failed (best effort): %s", step.name, exc)
            results.append(StepResult(step.name, f"failed: {exc}", failed=True))
    return results
