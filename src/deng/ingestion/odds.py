"""Bookmaker odds from The Odds API, for the model-versus-market comparison.

What is fetched, and why this way:

* **One request per fetch, for the whole competition.** `GET
  /v4/sports/soccer_uefa_champs_league/odds?regions=eu&markets=h2h` answers
  with every upcoming event and every bookmaker's 1X2 prices in one document.
  One region and one market cost one credit; the free tier has 500 a month.
* **The budget is the design constraint.** Fetching every 15 minutes around
  the clock would cost ~2 900 credits a month. So the pipeline fetches once a
  day as a baseline and at the configured interval only while a watched match
  is inside its window before kick-off (`ODDS_WATCH_HOURS_BEFORE_KICKOFF`).
  The API reports the remaining credits in a header; below the configured
  reserve the pipeline stops fetching and the last state stays visible, with
  its age, in the app.
* **Every fetch is kept**, not only the changes: knowing that the quote was
  still the same at 14:20 is information, and the curated step derives the
  change history from it.
* **The API is only ever called from here**, i.e. from the pipeline. The app
  reads tables; a page reload can never spend a credit.
* **Bookmakers spell club names their own way** ("Bayern Munich", "Inter
  Milan"). Events are resolved to fixtures by kick-off time plus name
  similarity against our team names and the aliases in
  `data/reference/bookmaker_team_aliases.csv`; an event that cannot be resolved
  stays UNMATCHED and is reported by a WARNING check, never guessed.
"""

from __future__ import annotations

import csv
import json
import logging
import re
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import psycopg
import requests
from psycopg.types.json import Jsonb

from deng.config import Settings
from deng.database.raw_loader import hash_payload
from deng.ingestion.football_data_client import ApiError, RetryableApiError
from deng.ingestion.weather import PIPELINE_TZ, _find

logger = logging.getLogger(__name__)

SOURCE = "the-odds-api.com"
SAMPLE_SOURCE = "the-odds-api.com (sample)"
MARKET = "h2h"  # 1X2 on regular time including stoppage time - no extra time
SAMPLE_DIR = Path("data") / "sample" / "the-odds-api"
ALIASES_FILE = Path("data") / "reference" / "bookmaker_team_aliases.csv"
# Kick-off times can differ by a few minutes between sources, and a bookmaker
# may list a postponed match under the old time for a while.
KICKOFF_TOLERANCE = timedelta(hours=3)
# Both team names must reach this similarity for an event to be matched.
MATCH_THRESHOLD = 0.6
# Sample file names carry the fetch time: odds_<sport>_2026-09-21T120000Z.json
SAMPLE_TIME = re.compile(r"_(\d{4}-\d{2}-\d{2})T(\d{2})(\d{2})(\d{2})Z\.json$")


@dataclass(frozen=True)
class OddsRequest:
    """One odds request: the competition, the bookmaker regions, the market."""

    sport: str
    regions: str = "eu"
    markets: str = MARKET
    bookmakers: str = ""

    @property
    def endpoint(self) -> str:
        """Endpoint path relative to the base URL."""
        return f"sports/{self.sport}/odds"

    def params(self) -> dict[str, Any]:
        """Query parameters as sent - without the API key, which is added at send time."""
        params: dict[str, Any] = {
            "regions": self.regions,
            "markets": self.markets,
            "oddsFormat": "decimal",
            "dateFormat": "iso",
        }
        if self.bookmakers:
            params["bookmakers"] = self.bookmakers
        return params


@dataclass(frozen=True)
class Quota:
    """Credit bookkeeping from the response headers."""

    remaining: int | None = None
    used: int | None = None
    last: int | None = None

    @classmethod
    def from_headers(cls, headers: Any) -> Quota:
        """Parse `x-requests-remaining`, `x-requests-used`, `x-requests-last`."""

        def number(name: str) -> int | None:
            value = headers.get(name)
            try:
                return int(float(value)) if value is not None else None
            except (TypeError, ValueError):
                return None

        return cls(
            remaining=number("x-requests-remaining"),
            used=number("x-requests-used"),
            last=number("x-requests-last"),
        )


@dataclass(frozen=True)
class FetchPlan:
    """The decision whether to spend a credit now, and why."""

    fetch: bool
    reason: str


@dataclass
class OddsResult:
    """What one odds run did."""

    plan: FetchPlan | None = None
    fetched_at: datetime | None = None
    inserted: bool = False
    event_count: int = 0
    quota: Quota = field(default_factory=Quota)
    events_matched: int = 0
    events_unmatched: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        """One line for logs and CLI output."""
        if self.plan is not None and not self.plan.fetch:
            return f"skipped: {self.plan.reason}"
        state = "stored" if self.inserted else "already stored"
        quota = f", {self.quota.remaining} credits left" if self.quota.remaining is not None else ""
        return (
            f"{self.event_count} event(s) {state} ({self.plan.reason if self.plan else 'sample'}"
            f"{quota}); {self.events_matched} matched, {len(self.events_unmatched)} unmatched"
        )


# --------------------------------------------------------------------------
# Deciding whether to fetch
# --------------------------------------------------------------------------


def plan_fetch(
    *,
    now: datetime,
    has_key: bool,
    last_fetch_at: datetime | None,
    last_remaining: int | None,
    reserve: int,
    refresh_minutes: int,
    watch_hours: int,
    kickoffs: list[datetime],
    force: bool = False,
) -> FetchPlan:
    """Decide whether this run may spend a credit.

    Pure function of its inputs, so the budget rules are unit-tested without a
    database or a clock. The rules, in order:

    1. No key: never.
    2. Quota reserve reached: no - except one probe a day, because the monthly
       reset is only visible in the header of a real answer.
    3. `force` (the CLI flag): yes.
    4. No fetch yet on the pipeline's calendar day: yes (the daily baseline).
    5. A watched match kicks off within `watch_hours`: yes, but not more often
       than every `refresh_minutes`.
    6. Otherwise: no - the daily fetch already happened.

    Args:
        now: The current time (aware).
        has_key: Whether an API key is configured.
        last_fetch_at: When the API was last called, if ever.
        last_remaining: Credits the API reported after that call, if known.
        reserve: Credits to keep untouched.
        refresh_minutes: Minimum minutes between fetches inside the window.
        watch_hours: How long before kick-off a match is watched.
        kickoffs: Kick-off times of the watched, unfinished matches.
        force: Fetch regardless of window and interval (still not without a key
            and not into the reserve).
    """
    if not has_key:
        return FetchPlan(False, "ODDS_API_KEY is not set")
    since_last = (now - last_fetch_at) if last_fetch_at else None
    if last_remaining is not None and last_remaining <= reserve:
        if since_last is not None and since_last < timedelta(days=1):
            return FetchPlan(
                False,
                f"quota reserve reached ({last_remaining} credits left, reserve {reserve}); "
                f"next probe {_fmt(last_fetch_at + timedelta(days=1))}",
            )
        return FetchPlan(
            True, f"daily probe with {last_remaining} credits left (reserve {reserve})"
        )
    if force:
        return FetchPlan(True, "forced")
    today = now.astimezone(PIPELINE_TZ).date()
    if last_fetch_at is None or last_fetch_at.astimezone(PIPELINE_TZ).date() < today:
        return FetchPlan(True, f"first fetch of {today}")
    window_end = now + timedelta(hours=watch_hours)
    upcoming = sorted(k for k in kickoffs if now < k <= window_end)
    if not upcoming:
        return FetchPlan(
            False,
            f"no watched match within {watch_hours} h; daily fetch done at {_fmt(last_fetch_at)}",
        )
    hours_to_kickoff = (upcoming[0] - now).total_seconds() / 3600
    if since_last is not None and since_last < timedelta(minutes=refresh_minutes):
        return FetchPlan(
            False,
            f"fetched {int(since_last.total_seconds() // 60)} min ago; interval is "
            f"{refresh_minutes} min (next kick-off in {hours_to_kickoff:.1f} h)",
        )
    return FetchPlan(True, f"watch window: kick-off in {hours_to_kickoff:.1f} h")


def _fmt(moment: datetime | None) -> str:
    return moment.astimezone(PIPELINE_TZ).strftime("%d %b %H:%M") if moment else "?"


def latest_state(connection: psycopg.Connection) -> tuple[datetime | None, int | None]:
    """When the real API was last called and how many credits it reported left."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT ingested_at, requests_remaining
              FROM raw.odds_api
             WHERE source = %s
             ORDER BY ingested_at DESC
             LIMIT 1
            """,
            (SOURCE,),
        )
        row = cursor.fetchone()
    return (row[0], row[1]) if row else (None, None)


def watched_kickoffs(connection: psycopg.Connection, watch_ids: frozenset[int]) -> list[datetime]:
    """Kick-off times of the unfinished matches the interval job watches."""
    with connection.cursor() as cursor:
        if watch_ids:
            cursor.execute(
                "SELECT utc_kickoff FROM curated.fact_match "
                "WHERE NOT is_finished AND match_id = ANY(%s)",
                (sorted(watch_ids),),
            )
        else:
            cursor.execute("SELECT utc_kickoff FROM curated.fact_match WHERE NOT is_finished")
        return [row[0] for row in cursor.fetchall()]


# --------------------------------------------------------------------------
# Fetching and storing
# --------------------------------------------------------------------------


def fetch_odds(
    session: requests.Session, base_url: str, api_key: str, request: OddsRequest
) -> tuple[str, list[dict[str, Any]], Quota]:
    """GET the odds. Returns the URL *without the key*, the event list and the quota.

    Raises:
        RetryableApiError: HTTP 429, 5xx or a network failure - worth retrying.
        ApiError: any other error; 401 covers both an invalid key and an
            exhausted quota (the API answers 401 for both).
    """
    url = f"{base_url.rstrip('/')}/{request.endpoint}"
    try:
        response = session.get(url, params={**request.params(), "apiKey": api_key}, timeout=30)
    except requests.RequestException as exc:
        raise RetryableApiError(0, f"network error: {exc}") from exc
    quota = Quota.from_headers(response.headers)
    if response.status_code == 429 or response.status_code >= 500:
        raise RetryableApiError(response.status_code, response.text[:200])
    if response.status_code != 200:
        raise ApiError(response.status_code, _error_message(response))
    try:
        payload = response.json()
    except ValueError as exc:
        raise ApiError(response.status_code, "invalid JSON from The Odds API") from exc
    if not isinstance(payload, list):
        raise ApiError(response.status_code, f"unexpected payload: {str(payload)[:200]}")
    # The URL stored in the raw zone must never contain the key; rebuilding it
    # from the parameters we sent is simpler and safer than scrubbing the
    # response URL.
    return requests.Request("GET", url, params=request.params()).prepare().url, payload, quota


def _error_message(response: requests.Response) -> str:
    try:
        body = response.json()
        if isinstance(body, dict) and "message" in body:
            return str(body["message"])
    except ValueError:
        pass
    return response.text[:200]


def read_samples(request: OddsRequest) -> list[tuple[str, list[dict[str, Any]], datetime]]:
    """Every committed sample fetch, oldest first, with the fetch time from its name."""
    directory = _find(SAMPLE_DIR)
    samples = []
    for path in sorted(directory.glob(f"odds_{request.sport}_*.json")):
        found = SAMPLE_TIME.search(path.name)
        if not found:
            logger.warning("sample %s has no fetch time in its name - skipped", path.name)
            continue
        day, hour, minute, second = found.groups()
        fetched_at = datetime.fromisoformat(f"{day}T{hour}:{minute}:{second}+00:00")
        samples.append((f"file://{path}", json.loads(path.read_text()), fetched_at))
    return samples


def store(
    connection: psycopg.Connection,
    request: OddsRequest,
    url: str,
    payload: list[dict[str, Any]],
    run_id: uuid.UUID,
    fetched_at: datetime,
    quota: Quota | None = None,
    source: str = SOURCE,
) -> bool:
    """Append one fetch to the raw zone. Returns True when the row was new.

    The unique key includes the fetch time, so a real fetch is always a new row
    while a replayed sample (whose fetch time comes from its file name) updates
    its own row - reruns of `--from-samples` cannot inflate the table.
    """
    quota = quota or Quota()
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO raw.odds_api AS r
                (source, endpoint, request_params, request_url, ingested_at, run_id,
                 payload, payload_hash, event_count,
                 requests_remaining, requests_used, requests_last)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (source, endpoint, request_params, ingested_at) DO UPDATE SET
                request_url = EXCLUDED.request_url, run_id = EXCLUDED.run_id,
                payload = EXCLUDED.payload, payload_hash = EXCLUDED.payload_hash,
                event_count = EXCLUDED.event_count,
                requests_remaining = EXCLUDED.requests_remaining,
                requests_used = EXCLUDED.requests_used, requests_last = EXCLUDED.requests_last
            RETURNING (xmax = 0) AS was_inserted
            """,
            (
                source,
                request.endpoint,
                Jsonb(request.params()),
                url,
                fetched_at,
                run_id,
                Jsonb(payload),
                hash_payload({"events": payload}),
                len(payload),
                quota.remaining,
                quota.used,
                quota.last,
            ),
        )
        row = cursor.fetchone()
    return bool(row and row[0])


def ingest_odds(
    connection: psycopg.Connection,
    run_id: uuid.UUID,
    settings: Settings,
    from_samples: bool = False,
    force: bool = False,
    session: requests.Session | None = None,
    now: datetime | None = None,
) -> OddsResult:
    """Fetch the odds if the budget rules allow, store them, and resolve the events.

    Args:
        connection: Open connection; committed after the raw row.
        run_id: Run the raw row belongs to.
        settings: The odds settings (key, sport, regions, budget rules).
        from_samples: Replay the committed samples instead of calling the API.
        force: Ignore window and interval (CLI `--force`).
        session: HTTP session (tests pass a fake one).
        now: Override for the current time (tests).
    """
    result = OddsResult()
    request = OddsRequest(
        sport=settings.odds_api_sport,
        regions=settings.odds_api_regions,
        bookmakers=settings.odds_api_bookmakers,
    )
    now = now or datetime.now(timezone.utc)

    if from_samples:
        samples = read_samples(request)
        result.plan = FetchPlan(bool(samples), f"{len(samples)} sample fetch(es)")
        for url, payload, fetched_at in samples:
            inserted = store(
                connection, request, url, payload, run_id, fetched_at, source=SAMPLE_SOURCE
            )
            result.inserted = result.inserted or inserted
            result.event_count = len(payload)
            result.fetched_at = fetched_at
        connection.commit()
        return result

    last_fetch_at, last_remaining = latest_state(connection)
    result.plan = plan_fetch(
        now=now,
        has_key=bool(settings.odds_api_key.get_secret_value()),
        last_fetch_at=last_fetch_at,
        last_remaining=last_remaining,
        reserve=settings.odds_quota_reserve,
        refresh_minutes=settings.odds_refresh_minutes,
        watch_hours=settings.odds_watch_hours_before_kickoff,
        kickoffs=watched_kickoffs(connection, settings.odds_watch_match_id_set),
        force=force,
    )
    if not result.plan.fetch:
        logger.info("odds %s", result.summary)
        return result

    url, payload, quota = fetch_odds(
        session or requests.Session(),
        settings.odds_api_base_url,
        settings.odds_api_key.get_secret_value(),
        request,
    )
    result.fetched_at = now
    result.quota = quota
    result.event_count = len(payload)
    result.inserted = store(connection, request, url, payload, run_id, now, quota)
    connection.commit()
    if quota.remaining is not None and quota.remaining <= settings.odds_quota_reserve:
        logger.warning(
            "odds quota reserve reached: %s credits left (reserve %s) - fetching pauses",
            quota.remaining,
            settings.odds_quota_reserve,
        )
    logger.info("odds %s", result.summary)
    return result


# --------------------------------------------------------------------------
# Resolving bookmaker events to our fixtures
# --------------------------------------------------------------------------

# Tokens that carry no identity: legal forms and generic words. "united",
# "city", "real" and the like stay - removing them would make Manchester
# United and Manchester City the same club.
STOPWORDS = frozenset(
    "fc cf sc sk fk kv cp ac as ssc afc bk sv rc osc pae ae club clube de da del di "
    "balompie calcio spor kulubu 1907".split()
)
TRANSLITERATE = str.maketrans({"ø": "o", "æ": "ae", "ß": "ss", "ł": "l", "đ": "d", "ð": "d"})


def normalise(name: str) -> frozenset[str]:
    """A club name as a set of comparable tokens: lower-case, ASCII, no legal forms."""
    text = unicodedata.normalize("NFKD", name.lower().translate(TRANSLITERATE))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    tokens = [t for t in re.split(r"[^a-z0-9]+", text) if t]
    kept = frozenset(t for t in tokens if t not in STOPWORDS)
    return kept or frozenset(tokens)


def similarity(a: frozenset[str], b: frozenset[str]) -> float:
    """Overlap coefficient: shared tokens over the smaller set (1.0 = one contains the other)."""
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def load_aliases(path: Path | None = None) -> dict[int, list[str]]:
    """Bookmaker spellings per team id from the reference CSV."""
    path = path or _find(ALIASES_FILE)
    aliases: dict[int, list[str]] = {}
    if not path.exists():
        return aliases
    with path.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row.get("alias"):
                aliases.setdefault(int(row["team_id"]), []).append(row["alias"])
    return aliases


@dataclass(frozen=True)
class Fixture:
    """A fixture with every spelling we know for each side."""

    match_id: int
    utc_kickoff: datetime
    home_names: tuple[frozenset[str], ...]
    away_names: tuple[frozenset[str], ...]


@dataclass(frozen=True)
class EventMatch:
    """The resolution of one bookmaker event."""

    match_id: int | None
    confidence: float
    note: str


def resolve_event(
    home: str, away: str, commence_time: datetime, fixtures: list[Fixture]
) -> EventMatch:
    """Pick the fixture for an event: same kick-off (within tolerance), both names similar.

    Pure function: tested without a database. Ambiguity (two fixtures equally
    similar) is an UNMATCHED result with a note, not a guess.
    """
    home_tokens, away_tokens = normalise(home), normalise(away)
    scored = []
    for fixture in fixtures:
        if abs(fixture.utc_kickoff - commence_time) > KICKOFF_TOLERANCE:
            continue
        home_sim = max(similarity(home_tokens, n) for n in fixture.home_names)
        away_sim = max(similarity(away_tokens, n) for n in fixture.away_names)
        if min(home_sim, away_sim) >= MATCH_THRESHOLD:
            scored.append((home_sim + away_sim, fixture.match_id))
    if not scored:
        return EventMatch(None, 0.0, "no fixture within 3 h whose team names are similar enough")
    scored.sort(reverse=True)
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        return EventMatch(None, 0.0, f"ambiguous between matches {scored[0][1]} and {scored[1][1]}")
    score, match_id = scored[0]
    return EventMatch(match_id, round(score / 2, 3), "kick-off time and team names")


def load_fixtures(connection: psycopg.Connection, aliases: dict[int, list[str]]) -> list[Fixture]:
    """Every fixture with its team names, short names, codes and aliases."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT m.match_id, m.utc_kickoff,
                   h.team_id, h.name, h.short_name, h.tla,
                   a.team_id, a.name, a.short_name, a.tla
              FROM curated.fact_match m
              JOIN curated.dim_team h ON h.team_id = m.home_team_id
              JOIN curated.dim_team a ON a.team_id = m.away_team_id
            """
        )
        rows = cursor.fetchall()

    def names(team_id: int, *spellings: str | None) -> tuple[frozenset[str], ...]:
        candidates = [s for s in spellings if s] + aliases.get(team_id, [])
        return tuple(normalise(s) for s in candidates)

    return [
        Fixture(
            int(r[0]), r[1], names(int(r[2]), r[3], r[4], r[5]), names(int(r[6]), r[7], r[8], r[9])
        )
        for r in rows
    ]


def match_events(
    connection: psycopg.Connection, aliases: dict[int, list[str]] | None = None
) -> tuple[int, list[str]]:
    """Resolve every staged event without a match. Returns (matched, unmatched labels).

    Re-evaluates UNMATCHED events every time, so a new alias in the CSV takes
    effect on the next run without any manual repair.
    """
    aliases = load_aliases() if aliases is None else aliases
    fixtures = load_fixtures(connection, aliases)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT DISTINCT s.event_id, s.commence_time, s.home_team_name, s.away_team_name
              FROM staging.bookmaker_odds s
              LEFT JOIN staging.odds_event_match x ON x.event_id = s.event_id
             WHERE x.event_id IS NULL OR x.match_id IS NULL
             ORDER BY s.commence_time, s.event_id
            """
        )
        events = cursor.fetchall()

    matched, unmatched = 0, []
    with connection.cursor() as cursor:
        for event_id, commence_time, home, away in events:
            found = resolve_event(home, away, commence_time, fixtures)
            if found.match_id is None:
                unmatched.append(f"{home} vs {away} ({commence_time:%d %b %H:%M} UTC)")
            else:
                matched += 1
            cursor.execute(
                """
                INSERT INTO staging.odds_event_match AS x
                    (event_id, match_id, commence_time, home_team_name, away_team_name,
                     method, confidence, note, matched_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now())
                ON CONFLICT (event_id) DO UPDATE SET
                    match_id = EXCLUDED.match_id, commence_time = EXCLUDED.commence_time,
                    home_team_name = EXCLUDED.home_team_name,
                    away_team_name = EXCLUDED.away_team_name, method = EXCLUDED.method,
                    confidence = EXCLUDED.confidence, note = EXCLUDED.note, matched_at = now()
                """,
                (
                    event_id,
                    found.match_id,
                    commence_time,
                    home,
                    away,
                    "NAME" if found.match_id is not None else "UNMATCHED",
                    found.confidence,
                    found.note,
                ),
            )
    connection.commit()
    for label in unmatched:
        logger.warning("odds event not resolved to a fixture: %s", label)
    return matched, unmatched


def pipeline_day(moment: datetime) -> date:
    """The pipeline's calendar day of a moment (Europe/Zurich)."""
    return moment.astimezone(PIPELINE_TZ).date()
