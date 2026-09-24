"""The pipeline's idea of "today".

One place, because three parts of the pipeline have to agree on it: the CLI's
default date, the weather source (a forecast is only a forecast if it is
fetched on the day it is stamped with) and the odds budget ("once a day").

Europe/Zurich, not UTC: the schedule runs at 06:00 Zurich time, and a run that
starts after midnight local time must belong to the day the team would call it.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

PIPELINE_TZ = ZoneInfo("Europe/Zurich")


def pipeline_today() -> date:
    """The calendar day the pipeline considers 'today'."""
    return datetime.now(PIPELINE_TZ).date()


def pipeline_day(moment: datetime) -> date:
    """The pipeline's calendar day of a given moment."""
    return moment.astimezone(PIPELINE_TZ).date()
