# Data Sources

Status: **confirmed 20 Sep 2026 by a real exploration run** – football-data.org
and Open-Meteo are the chosen core sources. Measured findings, including two
corrections to the assumptions below, are in
[`docs/evidence/api-exploration.md`](evidence/api-exploration.md); the decision
is recorded in [ADR-001](adr/ADR-001-football-data-source.md) (ACCEPTED).

The pipeline has **five** sources, each one module in `src/deng/sources/`. The
ingestion asks them in this order:

1. **football-data.org** – fixtures, results, teams, standings (§ 1)
2. **OpenStreetMap / Nominatim** – stadium coordinates (§ 3)
3. **the crest images** of football-data.org – club logos
4. **Open-Meteo** – weather forecasts (§ 2)
5. **The Odds API** – bookmaker odds (§ 2b, [ADR-005](adr/ADR-005-bookmaker-odds-source.md))

Football comes first because three of the later sources need to know which
matches and clubs exist – and they read that from the raw zone, never from a
table the transformation builds.

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
| Historical coverage (free) | **verified: historical seasons ARE served** – `?season=2023` returns the complete 2023/24 season (125 matches, HTTP 200); 47 seasons listed back to 1980 | "recent-season limits" – documentation is vague; the free plan has historically excluded the current season | multi-season, but result caps make bulk extraction impractical |
| Future fixtures | yes – whole season's schedule with `status=SCHEDULED`/`TIMED`, `utcDate`, `matchday`, `stage` | yes | yes (limited) |
| Update frequency | source updates within minutes after matches; we poll daily | near real time | irregular, community-maintained |
| Expected volume | measured: 144 league-phase matches (knockout drawn in December), 36 teams, 1 standings table; 212 KB per full fixture list; **< 2 MB raw per day, < 1 GB per season**; all 47 seasons ≈ 5 000–6 500 matches | comparable, but 100/day budget is consumed by ~3 endpoint × team loops | small |
| Documentation quality | good (`docs.football-data.org`), Postman collection | good, but marketing-heavy | mediocre, undocumented caps |
| Reliability | stable since 2015, single maintainer | commercial, stable | best effort |
| Licence / academic use | free tier explicitly aimed at non-commercial/learning use | free tier for evaluation | free tier for hobby use |
| Known limitations | no line-ups, injuries, player or match statistics; `odds` is a stub message object; no venue coordinates; `/teams/{id}/matches` silently limited to tier competitions – 11 of 36 clubs have no domestic data (referees, by contrast, ARE included) | 100 requests/day is a hard ceiling for a daily multi-endpoint batch; current-season access on the free plan uncertain | data quality and caps |
| Data-quality risks | measured: `?status=SCHEDULED` returns rows whose stored status is `TIMED`; `resultSet` aggregates do not add up and `standings.form` is null; `group` null since the 2024/25 format change; postponed matches change `utcDate`; neutral-venue final; scores corrected after the fact | schema churn between versions; nested nulls | strings instead of typed values |
| Fallback strategy | keep every raw payload → we own the history; if the API disappears, API-Football fixtures can be mapped by (date, home team, away team) | – | – |
| Verdict | **RECOMMENDED** – covers fixtures, results, standings, teams and H2H for CL within a generous minute-based limit | **REJECTED for the core** – daily budget too small for a repeatable batch; possible later add-on for injuries/line-ups if the plan question is clarified | **REJECTED** – free tier too capped |

Endpoints planned for the daily batch (football-data.org):

| Endpoint | Purpose | Calls/day |
|---|---|---|
| `GET /competitions/CL` | competition + current season metadata | 1 |
| `GET /competitions/CL/teams` | teams (id, name, short name, crest, venue name, address) | 1 |
| `GET /competitions/CL/matches` | all matches of the season (scheduled + finished), reloaded in full because matches are added mid-season | 1 |
| `GET /competitions/CL/standings` | league-phase table | 1 |
| `GET /competitions/CL/matches?season=YYYY` + `.../teams?season=YYYY` | past seasons as training data, switched on with the setting `FOOTBALL_DATA_SEASONS` | 2 per season, **once** |
| ~~`GET /teams/{id}/matches?status=FINISHED`~~ | dropped by [ADR-004](adr/ADR-004-champions-league-scope.md): form is Champions League only | – |
| ~~`GET /matches/{id}/head2head`~~ | not fetched: a COULD item for the final (backlog 2.5); the one pairing probed had no previous meetings | – |

**4 calls per day** – far inside 10 calls/minute, and the client throttles on
`X-Requests-Available-Minute`. Past seasons are the only extra cost and they are
paid once: measured 125 matches for 2023 and 189 for 2024, next to the 144 of
the current league phase.

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

## 2b. Bookmaker odds – candidates

Needed for the model-versus-market view in the app; decision in
[ADR-005](adr/ADR-005-bookmaker-odds-source.md).

| Criterion | **The Odds API** (chosen) | API-Football odds | football-data.org odds |
|---|---|---|---|
| API / URL | `https://api.the-odds-api.com/v4/sports/soccer_uefa_champs_league/odds` | `/odds?fixture=&bookmaker=` | `odds` field on `/matches` |
| Authentication | `apiKey` query parameter, free registration | free registration | paid add-on |
| Free tier | **500 credits/month**; one credit per region × market per request; all sports, most bookmakers | 100 requests/day, one request per fixture and bookmaker | stub message only |
| Content | every upcoming event of the competition with every bookmaker of a region (~25 in `eu`), bookmaker key + name, `last_update` per bookmaker and market, h2h/spreads/totals | per fixture | – |
| Data format | JSON array of events; decimal or American odds | JSON | – |
| Rate limit | credit budget only; `x-requests-remaining` / `x-requests-used` / `x-requests-last` headers; HTTP 401 when exhausted | 100/day | – |
| Licence | free plan for personal/evaluation use | evaluation | – |
| Known limitations | budget: 15-minute polling around the clock costs ~2 900/month, so the pipeline polls only in a window before watched matches; bookmakers spell club names their own way (aliases needed); h2h only covers regular time | daily budget spent by one matchday | not data |
| Verdict | **RECOMMENDED** – one request per fetch for the whole competition, named bookmakers, own timestamps | rejected – per-fixture-and-bookmaker requests do not fit a matchday into 100/day | rejected |

## 3. Stadium coordinates – OpenStreetMap (Nominatim)

The football API delivers no coordinates and the weather API needs them, so
OpenStreetMap is a source of the pipeline like the other four – **not** a CSV
maintained by hand. `make venues` (`ingest --only openstreetmap`) stores every
answer in the raw zone, and `sql/transform/305_staging_venues.sql` unpacks it
into `staging.venues`, exactly as `110` unpacks the football payload.

| Criterion | **OpenStreetMap / Nominatim** (chosen) |
|---|---|
| API / URL | `https://nominatim.openstreetmap.org/search` |
| Authentication | none; the usage policy requires an identifying `User-Agent` |
| Rate limit | at most **1 request per second**; 36 clubs once a season is far inside it |
| Cadence | **once per club, not daily** – stadiums do not move, so the plan only returns clubs without a stored answer and a normal run asks nothing |
| Where the answer lands | `raw.osm_venues`: the Nominatim payload untouched, plus what we asked, when and by which run – and two extra columns the other sources do not need, `review_status` (`RESOLVED` / `NOT_AVAILABLE`) and `review_note`: **our verdict is stored next to the payload**, no longer only in a CSV. The view `raw.venue_coordinates` hands the newest row per club to the weather source |
| Data format | JSON array of search hits; `lat`, `lon`, `display_name`, `osm_type`, `osm_id` |
| Known limitations | searching the API's venue name blindly puts clubs in the wrong city – the first run put Napoli in Novara, Barcelona in a village near Girona and Roma in Turin. 8 clubs therefore have a corrected search term and 5 flagged rows were checked on the map by hand, each with the reason next to the search term in `src/deng/sources/openstreetmap.py` ([evidence](evidence/weather.md#2-venues-why-the-apis-venue-fields-could-not-be-geocoded-blindly)) |
| Unresolvable | 2 of 36 clubs have no usable home venue (Shakhtar have played outside Ukraine since 2022; the API delivers no venue for Sabah FK). They get no coordinates, their matches get the weather status `VENUE_UNKNOWN`, and a WARNING check names every club without a venue row |
| Offline path | the 36 committed answers in `data/sample/openstreetmap/` keep `--from-samples` working without a network |
| Licence | **ODbL** – attribution required |
| Verdict | **CHOSEN** – free, no key, and once it is a source the coordinates get the same audit trail as every other payload: which question, which answer, which day, which verdict |

### Reference data still maintained in the repository

| Dataset | File | Purpose | Source |
|---|---|---|---|
| Bookmaker team aliases | `data/reference/bookmaker_team_aliases.csv` | how bookmaker feeds spell the 36 clubs ("Bayern Munich", "Inter Milan"); joins odds events to fixtures together with the kick-off time | maintained by hand; a WARNING check names every event that still fails to resolve |

One small, versioned, reviewable file – and an unresolved event is reported, not
silently dropped. The former `data/reference/venues.csv` and
`scripts/build_venues.py` are gone: their job is now § 3 above.

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
| Venue name | with the fixture (home stadium); neutral final venue known in advance | football-data.org teams (their spelling) and OpenStreetMap (ours) | `NOT_AVAILABLE` |
| Venue coordinates | after the club's one OpenStreetMap lookup (`make venues`, once per club) | OpenStreetMap → `raw.osm_venues` | `NOT_AVAILABLE` stored as the verdict; the match gets `VENUE_UNKNOWN`, and a club with no venue row at all raises a data-quality WARNING |
| Standings / league position | after matchday 1; changes after every matchday | football-data.org | `NOT_YET_AVAILABLE` before matchday 1 |
| Team form (last 5 matches) | as soon as ≥ 1 Champions League match is finished (ADR-004) | computed from our own match rows, not from an API aggregate | `PARTIAL` (fewer than 5 matches) |
| Head-to-head | if the teams met before (any season) | football-data.org head2head (not ingested yet, backlog 2.5) | `NO_PREVIOUS_MEETINGS` |
| Weather forecast | ≤ 16 days before kick-off (reliable ≤ 7 days) | Open-Meteo forecast | `NOT_YET_AVAILABLE` |
| Weather actuals | ≥ 5 days after the match | Open-Meteo archive | `NOT_YET_AVAILABLE` |
| Bookmaker odds | while the event is listed as upcoming; the pipeline spends credits only in a window before watched matches ([ADR-005](adr/ADR-005-bookmaker-odds-source.md)) | The Odds API | no quote for the match – never an invented price |
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
* The Odds API (v4) pricing and documentation: <https://the-odds-api.com>
* Nominatim usage policy and OpenStreetMap licence: <https://operations.osmfoundation.org/policies/nominatim/>, <https://www.openstreetmap.org/copyright>
