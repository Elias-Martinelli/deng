"""What an answer must contain before it may enter the raw zone.

The raw zone keeps every answer unchanged, and the SQL in `sql/transform/`
reads it later. So a changed API would surface far from its cause: a missing
`utcDate` breaks the cast in staging, a renamed `teams` list quietly gives an
empty dimension. These checks move that failure to the moment the answer
arrives - before anything is stored - and name the field that is missing.

The rule for schema drift, in two halves:

* **Required = what the SQL reads to build a key or a label.** Ids, the
  kick-off, the status, the score object, the list that holds the records.
  Missing, null or of the wrong type -> `ContractError`, the run fails, and the
  day's partial writes are rolled back. The message lists every problem found,
  so one look at the run log is enough.
* **Everything else is tolerated.** A new field, a missing optional one (a
  club without `tla`, a match without referees) passes. The raw zone stores it
  anyway, and the transformation already treats those columns as nullable.

Deliberately shallow: a check here costs a few dictionary lookups per record
and never looks at the meaning of a value - that is the data-quality checks'
job, on the curated tables.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import datetime
from typing import Any

from deng.sources.http import ApiError

# A few problems name the cause; a few hundred (every match missing the same
# field) would only bury it. The count of the rest is still reported.
MAX_LISTED_PROBLEMS = 5

_MISSING = object()


class ContractError(ApiError):
    """The answer arrived, but without a field the pipeline reads: schema drift.

    A subclass of ApiError, not of RetryableApiError: asking again returns the
    same shape, so the run fails at once and a human looks at the change.
    """

    def __init__(self, source: str, endpoint: str, problems: list[str]) -> None:
        """Summarise the problems in one message for the run log."""
        listed = "; ".join(problems[:MAX_LISTED_PROBLEMS])
        more = len(problems) - MAX_LISTED_PROBLEMS
        if more > 0:
            listed += f"; and {more} more"
        # The HTTP status was 200 (or a replayed sample) - the problem is the body.
        super().__init__(200, f"{source} {endpoint}: payload contract broken: {listed}")
        self.source = source
        self.endpoint = endpoint
        self.problems = problems


def _lookup(record: Any, path: str) -> Any:
    """Follow a dotted path ("score.fullTime.home"); _MISSING if a key is absent."""
    value = record
    for key in path.split("."):
        if not isinstance(value, dict) or key not in value:
            return _MISSING
        value = value[key]
    return value


def _is_timestamp(value: Any) -> bool:
    # Python 3.10's fromisoformat does not accept the trailing "Z" the APIs use.
    if not isinstance(value, str):
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


# The kinds a required field can have. "timestamp" is a string the SQL casts to
# timestamptz, so a malformed one would fail the transformation, not here.
_KINDS: dict[str, Callable[[Any], bool]] = {
    "int": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "str": lambda v: isinstance(v, str),
    "object": lambda v: isinstance(v, dict),
    "list": lambda v: isinstance(v, list),
    "timestamp": _is_timestamp,
}


def require(
    record: Any,
    path: str,
    kind: str,
    problems: list[str],
    where: str = "",
    nullable: bool = False,
) -> None:
    """Append a problem unless `record[path]` exists and is of `kind`.

    Args:
        record: The JSON object to look into.
        path: Dotted path to the field.
        kind: One of int, str, object, list, timestamp.
        problems: Collects the findings; nothing is raised here.
        where: Prefix that locates the record, e.g. "matches[3] (id 537327)".
        nullable: The key must exist, but null is a legitimate value (a score
            before kick-off, a knockout opponent that is not drawn yet).
    """
    value = _lookup(record, path)
    label = f"{where}.{path}" if where else path
    if value is _MISSING:
        problems.append(f"{label} missing")
    elif value is None:
        if not nullable:
            problems.append(f"{label} is null")
    elif not _KINDS[kind](value):
        problems.append(f"{label} is not {kind}: {str(value)[:40]!r}")


def records(
    payload: Any,
    key: str,
    problems: list[str],
    where: str = "",
    non_empty: bool = True,
) -> Iterator[tuple[str, dict[str, Any]]]:
    """Yield `(location, record)` for each object in the list `payload[key]`.

    A missing list, an empty one where records are expected, and an element
    that is not an object are problems; the elements that are objects are
    still yielded, so their own fields get checked too.
    """
    label = f"{where}.{key}" if where else key
    items = _lookup(payload, key)
    if not isinstance(items, list):
        problems.append(f"{label} missing or not a list")
        return
    if non_empty and not items:
        problems.append(f"{label} is empty")
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            problems.append(f"{label}[{index}] is not an object")
            continue
        # The id, when there is one, finds the record in the stored payload faster
        # than its position does.
        ident = item.get("id")
        yield (f"{label}[{index}]" + (f" (id {ident})" if ident is not None else "")), item


# --- football-data.org -----------------------------------------------------
#
# One function per endpoint, each listing exactly the fields its staging SQL
# (sql/transform/110-112) and the raw planning views (009) read as keys,
# timestamps or the label.


def _competition(payload: dict[str, Any], problems: list[str]) -> None:
    require(payload, "id", "int", problems)
    require(payload, "code", "str", problems)
    require(payload, "currentSeason.id", "int", problems)


def _teams(payload: dict[str, Any], problems: list[str]) -> None:
    for where, team in records(payload, "teams", problems):
        require(team, "id", "int", problems, where)
        require(team, "name", "str", problems, where)


def _standings(payload: dict[str, Any], problems: list[str]) -> None:
    require(payload, "season.id", "int", problems)
    # May be empty: before matchday 1 a competition can answer without a table.
    for where, group in records(payload, "standings", problems, non_empty=False):
        for row_where, row in records(group, "table", problems, where, non_empty=False):
            require(row, "team.id", "int", problems, row_where)
            require(row, "position", "int", problems, row_where)


def _matches(payload: dict[str, Any], problems: list[str]) -> None:
    for where, match in records(payload, "matches", problems):
        require(match, "id", "int", problems, where)
        require(match, "utcDate", "timestamp", problems, where)
        require(match, "status", "str", problems, where)
        require(match, "season.id", "int", problems, where)
        # The team objects must be there; their id may be null until a knockout
        # draw names the opponent (staging skips such a match until then).
        require(match, "homeTeam.id", "int", problems, where, nullable=True)
        require(match, "awayTeam.id", "int", problems, where, nullable=True)
        # The label: null before kick-off, an integer afterwards.
        require(match, "score.fullTime.home", "int", problems, where, nullable=True)
        require(match, "score.fullTime.away", "int", problems, where, nullable=True)


# Keyed by the endpoint's path template, as in football_data.DAILY_ENDPOINTS;
# past seasons use the same paths and therefore the same contract.
FOOTBALL_CONTRACTS: dict[str, Callable[[dict[str, Any], list[str]], None]] = {
    "competitions/{code}": _competition,
    "competitions/{code}/teams": _teams,
    "competitions/{code}/standings": _standings,
    "competitions/{code}/matches": _matches,
}


def check_football(path_template: str, payload: dict[str, Any], endpoint: str) -> None:
    """Raise ContractError if a football-data.org answer lacks a required field.

    Args:
        path_template: The endpoint's path template, which selects the contract.
        payload: The parsed answer.
        endpoint: The concrete endpoint, for the error message.

    Raises:
        ContractError: listing every problem found.
        KeyError: for an endpoint without a contract - adding an endpoint means
            stating what it must contain.
    """
    problems: list[str] = []
    FOOTBALL_CONTRACTS[path_template](payload, problems)
    if problems:
        raise ContractError("football-data.org", endpoint, problems)


# --- Open-Meteo ------------------------------------------------------------


def check_open_meteo(payload: dict[str, Any], variables: tuple[str, ...], endpoint: str) -> None:
    """Raise ContractError unless the hourly arrays are there and aligned.

    The payload is columnar: one array per variable, matched to `hourly.time`
    by position (sql/transform/310). An array that is missing or one element
    short would shift or drop values without any error in SQL.

    Raises:
        ContractError: listing every problem found.
    """
    problems: list[str] = []
    require(payload, "timezone", "str", problems)
    require(payload, "hourly.time", "list", problems)
    times = _lookup(payload, "hourly.time")
    if isinstance(times, list):
        if not times:
            problems.append("hourly.time is empty")
        for variable in variables:
            values = _lookup(payload, f"hourly.{variable}")
            if not isinstance(values, list):
                problems.append(f"hourly.{variable} missing or not a list")
            elif len(values) != len(times):
                problems.append(
                    f"hourly.{variable} has {len(values)} values for {len(times)} hours"
                )
    if problems:
        raise ContractError("open-meteo.com", endpoint, problems)
