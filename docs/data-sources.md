# Data Sources

Status: **evaluated 18 Sep 2026 – football-data.org and Open-Meteo recommended,
final confirmation after the first real API exploration (see
[`scripts/explore_football_api.py`](../scripts/explore_football_api.py)).**
Decision record: [ADR-001](adr/ADR-001-football-data-source.md).

Guiding principle: as few sources as possible, each one free, documented,
reachable without scraping and usable for an academic project.

## 1. Football data – candidates

| Criterion | **football-data.org** (recommended) | API-Football (api-sports.io) | TheSportsDB |
|---|---|---|---|
| API / URL | `https://api.football-data.org/v4` | `https://v3.football.api-sports.io` | `https://www.thesportsdb.com/api/v1/json/<key>/` |
| Authentication | header `X-Auth-Token`, free registration (e-mail) | header `x-apisports-key`, free registration | free public key `123` (v1) |
| Free tier | 12 competitions incl. **UEFA Champions League**, fixtures, results, standings, teams, head-to-head; scores/schedules "delayed" (irrelevant for a daily batch) | 100 requests/day, all endpoints (fixtures, standings, injuries, line-ups, statistics, predictions) | 30 requests/min; many endpoints capped (`eventsseason` limited to 15 events, team search limited to Arsenal) |
| Rate limit | **10 requests/minute**; headers `X-Requests-Available-Minute`, `X-RequestCounter-Reset`; HTTP 429 when exceeded | 100/day, ~10/min | 30/min, 429 on excess |
| Data format | JSON, flat v4 structures | JSON, deeply nested `response[]` | JSON, all values as strings |
| Historical coverage (free) | **current season only** (older seasons return HTTP 403 "restricted resource"); head-to-head sub-resource returns previous encounters | "recent-season limits" – documentation is vague; the free plan has historically excluded the current season | multi-season, but result caps make bulk extraction impractical |
| Future fixtures | yes – whole season's schedule with `status=SCHEDULED`/`TIMED`, `utcDate`, `matchday`, `stage` | yes | yes (limited) |
| Update frequency | source updates within minutes after matches; we poll daily | near real time | irregular, community-maintained |
| Expected volume | CL season ≈ 189 matches, 36 teams, 1 standings table; ~150 KB per full fixture list; **< 2 MB raw per day, < 1 GB per season** | comparable, but 100/day budget is consumed by ~3 endpoint × team loops | small |
| Documentation quality | good (`docs.football-data.org`), Postman collection | good, but marketing-heavy | mediocre, undocumented caps |
| Reliability | stable since 2015, single maintainer | commercial, stable | best effort |
| Licence / academic use | free tier explicitly aimed at non-commercial/learning use | free tier for evaluation | free tier for hobby use |
| Known limitations | no line-ups, injuries, player stats, match statistics or odds on the free tier; no venue coordinates | 100 requests/day is a hard ceiling for a daily multi-endpoint batch; current-season access on the free plan uncertain | data quality and caps |
| Data-quality risks | kick-off time `TBD` early in the season (`utcDate` at 00:00, `status=SCHEDULED` vs `TIMED`); postponed/rescheduled matches change `utcDate`; neutral-venue final; scores corrected after the fact | schema churn between versions; nested nulls | strings instead of typed values |
| Fallback strategy | keep every raw payload → we own the history; if the API disappears, API-Football fixtures can be mapped by (date, home team, away team) | – | – |
| Verdict | **RECOMMENDED** – covers fixtures, results, standings, teams and H2H for CL within a generous minute-based limit | **REJECTED for the core** – daily budget too small for a repeatable batch; possible later add-on for injuries/line-ups if the plan question is clarified | **REJECTED** – free tier too capped |

Endpoints planned for the daily batch (football-data.org):

| Endpoint | Purpose | Calls/day |
|---|---|---|
| `GET /competitions/CL` | competition + current season metadata | 1 |
| `GET /competitions/CL/teams` | teams (id, name, short name, crest, venue name, address) | 1 |
| `GET /competitions/CL/matches` | all matches of the season (scheduled + finished) | 1–2 |
| `GET /competitions/CL/standings` | league-phase table | 1 |
| `GET /teams/{id}/matches?status=FINISHED` | team form across all free-tier competitions (36 teams) | 36 |
| `GET /matches/{id}/head2head` | historical encounters for upcoming matches (only within 14 days of kick-off) | ≤ 18 |

≈ 60 calls per day ⇒ ~6 minutes at 10 calls/minute. Well within limits, and the
client throttles on `X-Requests-Available-Minute`.

## 2. Weather data – candidates

| Criterion | **Open-Meteo** (recommended) | OpenWeatherMap | Meteostat |
|---|---|---|---|
| API / URL | `https://api.open-meteo.com/v1/forecast`, `https://archive-api.open-meteo.com/v1/archive` | `https://api.openweathermap.org/data/3.0/onecall` | Python library / RapidAPI |
| Authentication | **none** for non-commercial use | API key | RapidAPI key |
| Free tier | 10 000 calls/day, 5 000/hour, 600/minute | 1 000 calls/day (One Call 3.0), credit card required | limited via RapidAPI |
| Data format | JSON, arrays per variable (columnar) | JSON | pandas DataFrame |
| Historical coverage | archive API (ERA5 reanalysis) from 1940, ~5 days delay; `past_days` up to 92 | paid | station data |
| Forecast horizon | **16 days** (`forecast_days=16`), hourly and daily aggregates | 8 days daily / 48 h hourly | none |
| Update frequency | models update every 1–6 hours | hourly | daily |
| Expected volume | one call per (fixture, run day) within the 16-day window: ≤ 20 calls/day, ~5 KB each | – | – |
| Documentation quality | excellent, interactive | good | ok |
| Reliability | high, open source, widely used | high | medium |
| Licence | **CC BY 4.0** – attribution required, storage/redistribution allowed | proprietary terms | CC BY-NC |
| Known limitations | forecast only ≤ 16 days ahead; needs coordinates (not delivered by football API) | credit card for free tier | no forecast |
| Data-quality risks | forecast quality degrades beyond ~7 days; hourly value must be picked for kick-off hour in the venue's time zone | – | – |
| Fallback strategy | archive API for post-match actuals; missing forecast ⇒ `NOT_YET_AVAILABLE` | – | – |
| Verdict | **RECOMMENDED** – no key, generous limits, forecast + archive from one provider | rejected (card, small limit) | rejected (no forecast) |

## 3. Reference data (maintained in the repository)

| Dataset | File | Purpose | Source |
|---|---|---|---|
| Venues | `data/reference/venues.csv` (planned) | stadium name, city, country, latitude, longitude, time zone for the 36 league-phase clubs; joins football venue names to weather coordinates | Wikipedia stadium pages, checked manually; ~36 rows |

Small, versioned and reviewable – preferable to geocoding at run time, which
would introduce a third external dependency into every run. Open-Meteo's free
geocoding API remains a fallback for clubs that are missing from the file.

## 4. Optional enrichment (COULD, not planned before the final)

| Source | What | Why it might be worth it |
|---|---|---|
| ClubElo (`http://api.clubelo.com/<Club>`) | CSV Elo-rating history for European clubs since 1939, no key | multi-season team-strength signal that compensates for the current-season-only limitation; trivially batchable (one CSV per club) |

## 5. Availability-aware ingestion – when is which information known?

Missing data must never be invented. Each attribute of an upcoming match has a
typical availability window; the snapshot table stores an explicit availability
state per attribute group.

| Information | Typically available | Source | State when missing |
|---|---|---|---|
| Fixture (teams, stage, matchday) | months ahead (draw in late August) | football-data.org | – (a match without fixture does not exist) |
| Kick-off date/time | dates at the draw, times a few weeks later; may change | football-data.org (`status` SCHEDULED → TIMED) | `KICKOFF_TBD` |
| Venue name | with the fixture (home stadium); neutral final venue known in advance | football-data.org teams / reference file | `NOT_AVAILABLE` |
| Venue coordinates | always (reference file) | `venues.csv` | `NOT_AVAILABLE` (new club not yet in file – data-quality alert) |
| Standings / league position | after matchday 1; changes after every matchday | football-data.org | `NOT_YET_AVAILABLE` before matchday 1 |
| Team form (last 5 matches) | as soon as ≥ 1 match is finished; domestic matches only for clubs from free-tier leagues | football-data.org team matches | `PARTIAL` (fewer than 5 matches) |
| Head-to-head | if the teams met before (any season) | football-data.org head2head | `NO_PREVIOUS_MEETINGS` |
| Weather forecast | ≤ 16 days before kick-off (reliable ≤ 7 days) | Open-Meteo forecast | `NOT_YET_AVAILABLE` |
| Weather actuals | ≥ 5 days after the match | Open-Meteo archive | `NOT_YET_AVAILABLE` |
| Line-ups | ~1 h before kick-off | **not in free tier** | `NOT_AVAILABLE` |
| Injuries / suspensions | days before | **not in free tier** | `NOT_AVAILABLE` |
| Final score | minutes after the match | football-data.org (`status=FINISHED`) | `NOT_YET_PLAYED` |

Implication for the pipeline: one daily batch is enough. Each run records for
every upcoming match which attribute groups were available on that day; the
snapshot table therefore doubles as a data-availability audit trail.

## Sources

* football-data.org pricing and coverage: <https://www.football-data.org/pricing>, <https://www.football-data.org/coverage>
* football-data.org API reference and policies: <https://www.football-data.org/documentation/api>, <https://docs.football-data.org/general/v4/policies.html>
* API-Football pricing: <https://www.api-football.com/pricing>
* TheSportsDB documentation: <https://www.thesportsdb.com/documentation>
* Open-Meteo documentation and terms: <https://open-meteo.com/en/docs>, <https://open-meteo.com/en/terms>
