"""The pipeline's idea of "today" and "now".

One place, because several parts of the pipeline have to agree on it: the CLI's
default date, the weather source (a forecast is only a forecast if it is
fetched on the day it is stamped with), the odds budget ("once a day") and the
SQL that decides what is still to come (`meta.pipeline_now()`).

Europe/Zurich, not UTC: the schedule runs at 06:00 Zurich time, and a run that
starts after midnight local time must belong to the day the team would call it.

A sample run replays a fixed snapshot, so it must not read the wall clock: run
on 18 October, the September samples would otherwise be judged against October
and give a different result every day. `replaying(day)` pins the clock to that
day's scheduled run; `connect()` hands the same moment to PostgreSQL.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

PIPELINE_TZ = ZoneInfo("Europe/Zurich")
# When the daily schedule runs (deng.orchestration: hour_of_day=6).
SCHEDULED_TIME = time(6, 0)
# The day a sample run replays by default: the first scheduled run after the
# newest committed sample (football 20 Sep, forecast 21 Sep, odds 21/22 Sep),
# so every sample was already fetched when the replayed run starts.
SAMPLES_DATE = date(2026, 9, 23)

_pinned: datetime | None = None


def pipeline_now() -> datetime:
    """The moment the pipeline considers 'now': the wall clock unless pinned."""
    return _pinned or datetime.now(PIPELINE_TZ)


def pipeline_today() -> date:
    """The calendar day the pipeline considers 'today'."""
    return pipeline_day(pipeline_now())


def pipeline_day(moment: datetime) -> date:
    """The pipeline's calendar day of a given moment."""
    return moment.astimezone(PIPELINE_TZ).date()


def scheduled_moment(day: date) -> datetime:
    """When the scheduled run of `day` starts."""
    return datetime.combine(day, SCHEDULED_TIME, tzinfo=PIPELINE_TZ)


def pinned_moment() -> datetime | None:
    """The pinned moment while a replay runs, None on the wall clock."""
    return _pinned


@contextmanager
def replaying(day: date) -> Iterator[datetime]:
    """Run the block as the scheduled run of `day` (a sample replay)."""
    global _pinned
    previous, _pinned = _pinned, scheduled_moment(day)
    try:
        yield _pinned
    finally:
        _pinned = previous
