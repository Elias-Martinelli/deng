# Champions League Match Intelligence Data Platform

HSLU · DENG – Data Engineering · HS26 · End-to-End Batch Data Pipeline

[![CI](https://github.com/Elias-Martinelli/deng/actions/workflows/ci.yml/badge.svg)](https://github.com/Elias-Martinelli/deng/actions/workflows/ci.yml)

A reproducible daily batch pipeline that collects UEFA Champions League
fixtures, results, standings, weather, bookmaker odds and stadium coordinates
and assembles them into a curated, point-in-time-correct dataset. **The
pipeline is the product.** A model that predicts the winner is what the data is
*for* — it is the downstream use, not part of this project. The Streamlit page
is an analysis dashboard for that data.

The whole project is three boxes, in this order:

![The three stages: ingest, transform, data product](docs/architecture-overview.svg)

How the pieces fit: [Architecture](#architecture) · what is done and what is
not: [Project Status](#project-status).

**Quick start** (no API key needed):

```bash
./setup.sh && make up && make init && make run-samples && make app
```

---

## Table of contents

[Overview](#project-overview) · [Problem](#problem-statement) · [End user](#end-user) ·
[Data product](#data-product) · [Use case](#use-case) · [Data sources](#data-sources) ·
[Data characteristics](#data-characteristics) · [Quality risks](#data-quality-risks) ·
[Architecture](#architecture) · [Ingestion](#batch-ingestion-strategy) ·
[Local development](#local-development) · [PostgreSQL](#postgresql) · [Docker](#docker) ·
[Orchestration](#workflow-orchestration) · [Transformation](#transformation) ·
[Data model](#data-model) · [Data quality](#data-quality) ·
[Reproducibility](#reproducibility) · [Verification](#verification) ·
[Notebook](#analytics--notebook) · [Streamlit](#streamlit-application) ·
[Cloud](#google-cloud-architecture) · [Limitations](#known-limitations) ·
[Status](#project-status) · [Contributing](#contributing-and-branch-strategy) ·
[Authors](#authors)

---

## Project Overview

Information about an upcoming Champions League match is scattered across
sources that update at different speeds: the fixture list is published months
ahead, standings change after every matchday, weather forecasts only become
meaningful two weeks out, and line-ups appear an hour before kick-off.

This platform ingests those sources on a schedule, keeps every raw payload,
and derives curated tables that answer **what was known about a match at a
given point in time**. That property is what a match-outcome model needs: it
may only learn from information that existed before kick-off. Building that
model is the downstream use of the data, not part of this project.

## Problem Statement

The source APIs only ever answer with today's state; what was known last week
is gone unless someone stored it. Training a model on match data therefore
means integrating several APIs every day, reconciling their keys, and recording
*when* each piece of information became available. A model trained on form or
weather that already contains the match it predicts looks excellent in testing
and fails in reality (data leakage).
Details: [`docs/use-case.md`](docs/use-case.md).

## End User

* **Primary: a data scientist or analyst** who wants to build and evaluate a
  match-outcome model (HOME_WIN / DRAW / AWAY_WIN) and needs a clean,
  documented, leakage-free table to train it on.
* **Secondary: anyone who wants to judge the data** before using it - the
  Streamlit dashboard shows how large the dataset is, how well each feature is
  covered, why a value is missing where it is, and one match in detail.

## Data Product

| Table | One row represents | Role for a model | Status |
|---|---|---|---|
| `curated.fact_match` | one Champions League match | label: `outcome`, derived from the goals | **implemented** |
| `curated.fact_team_match_form` | one team's participation in one match, with its form going in | features known before kick-off | **implemented** |
| `curated.fact_match_weather` | one match | forecast for the kick-off hour, fetched before kick-off, or why it is missing | **implemented** |
| `curated.fact_match_prediction` | one match, one model version, one run date | the baseline model's HOME/DRAW/AWAY probabilities as of that run | **implemented** (baseline) |
| `curated.fact_bookmaker_odds` | one odds change of one bookmaker for one match | the market's view, with the bookmaker's timestamp and ours | **implemented** |
| `curated.dim_team` | one team | name, three-letter code, crest URL | **implemented** |
| `curated.dim_venue` | one home venue (keyed by the home club) | coordinates for the weather, or the reason there are none | **implemented** |
| `curated.model_features` *(view)* | one match | **what a model would read**: the label plus every feature known before kick-off, in one row | **implemented** |
| `curated.team_crest` *(view)* | one team | the club logo, served from our own database instead of the API's CDN | **implemented** |
| `curated.fact_match_snapshot` | one upcoming match on one pipeline run date | **the training table**: everything known on that day | planned (final) |
| `curated.dim_date` | one calendar day | partition pruning in BigQuery | planned (final) |

Full definitions, keys and reasoning: [`docs/data-model.md`](docs/data-model.md).

## Use Case

1. **Model development** - train a baseline HOME/DRAW/AWAY classifier on
   features taken *N days before kick-off* and test it on later matchdays. The
   pipeline guarantees that every feature row only contains what was known at
   that point.
2. **Availability analysis** - how many days before kick-off does a usable
   forecast exist, how often do kick-off times move?
3. **Judging the data** - the Streamlit dashboard answers "could someone train
   a model on this?": how many matches per season, how many of them carry a
   label, how well each feature is covered and the honest reason when it is
   not, plus one fixture in detail. Everything is served from our own tables;
   the app makes no API calls.
4. **Model versus market** - for the same fixture, the baseline model's
   probabilities next to the 1X2 odds of named bookmakers, with both
   timestamps, the margin-free market probability, the deviation in
   percentage points and how both moved towards kick-off. The odds are fetched
   by the pipeline under a credit budget, never by the app.

A single league phase has 144 matches - too few to train on, so past seasons
are ingested as well. `FOOTBALL_DATA_SEASONS=2023,2024` costs one matches
request and one teams request per season; measured, 2023 adds 125 matches and
2024 adds 189 to the current 144. With both seasons in, the curated layer holds
458 matches, 60 clubs, 332 matches with a label and 664 form rows, and all 24
data-quality checks pass. The API lists 47 seasons, so this is a dial, not a
ceiling.

## Data Sources

**Five sources**, one file per source in
[`src/deng/sources/`](src/deng/sources/). Four providers: the crest images come
from football-data.org too, but they are a separate download with its own
strategy, so they are their own step.

| Source | What it is for | Access | Limit (free tier) |
|---|---|---|---|
| [football-data.org v4](https://www.football-data.org) | fixtures, results, teams, standings - the backbone, and the label a model learns | REST/JSON, `X-Auth-Token`, free registration | 10 requests/minute; no line-ups, injuries or match statistics; 11 of 36 clubs without domestic-league data |
| [Open-Meteo](https://open-meteo.com) | hourly forecast for the kick-off hour | REST/JSON, no key | forecasts 16 days ahead and nothing backwards; 10 000 calls/day, CC BY 4.0 |
| [The Odds API](https://the-odds-api.com) v4 | 1X2 odds (regular time) of ~25 European bookmakers, each with the bookmaker's own timestamp - the market's view next to ours | REST/JSON, `apiKey`, free registration; optional | 500 credits/month, one credit per fetch ([ADR-005](docs/adr/ADR-005-bookmaker-odds-source.md)) |
| [OpenStreetMap](https://www.openstreetmap.org) (Nominatim) | stadium coordinates - the football API has none and the weather API needs them | REST/JSON, no key | 1 request per second; asked once per club, not daily; ODbL |
| club crests (football-data.org) | the club logos the dashboard shows | plain HTTPS image download | one download per crest URL, ever |

Evaluation including rejected alternatives: [`docs/data-sources.md`](docs/data-sources.md).
Decisions: [ADR-001](docs/adr/ADR-001-football-data-source.md) (football, weather),
[ADR-005](docs/adr/ADR-005-bookmaker-odds-source.md) (odds), both ACCEPTED.
Measured behaviour of the live API: [`docs/evidence/api-exploration.md`](docs/evidence/api-exploration.md).

## Data Characteristics

* **Volume** (measured 20 Sep 2026): 144 league-phase matches, 36 teams, one
  standings table. A daily run costs 4 football requests, at most ~20 weather
  requests (one per venue with a match inside 16 days) and at most one odds
  credit; < 2 MB raw per day, < 1 GB per season. Each past season that is switched on costs two requests once (2023:
  125 matches, 2024: 189). All 47 listed seasons together are roughly
  5 000–6 500 matches.
* **Format:** nested JSON. Business keys are stable integers (`match.id`,
  `team.id`, `season.id`).
* **Change behaviour:** kick-off times and statuses change in place, scores are
  appended once, and **new fixtures appear mid-season** — the knockout rounds
  are drawn in December. This is the main argument for a scheduled daily batch
  rather than a one-off load.

## Data Quality Risks

Identified by measurement, not assumption ([evidence](docs/evidence/api-exploration.md)):

| Risk | Handling |
|---|---|
| `?status=SCHEDULED` returns rows stored as `TIMED` | upcoming matches are selected by `utc_kickoff`, never by the status string |
| The API's own aggregates do not add up (`wins+draws+losses ≠ count`) | all form figures computed from individual match rows; a constraint and a check enforce that ours add up |
| `standings.form` is always null | not used |
| `odds` is a stub object with a marketing message | not parsed; odds come from The Odds API instead |
| Bookmakers spell club names their own way ("Bayern Munich", "Inter Milan") | events are resolved by kick-off time plus name similarity and an alias file; an unresolved event stays `UNMATCHED` and a WARNING check names it - never guessed |
| A bookmaker suspends or withdraws a market before kick-off | a quote with fewer than three prices is stored as `is_complete = false`; one the latest fetch no longer carries is shown as withdrawn - both flagged in the app, not dropped |
| 11 of 36 clubs have no domestic-league data in the free tier | scope is Champions League only for every club ([ADR-004](docs/adr/ADR-004-champions-league-scope.md)), so form is comparable across all 36 |
| `group` null since the 2024/25 format change | no group dimension modelled |
| Matches rescheduled or postponed | full reload per day; the raw zone keeps each day's version |

## Architecture

The diagram at the top is the whole idea in three boxes. Two more pictures add
the detail; both are plain SVG, readable in light and dark mode.

![Sources, ingestion, warehouse, transformation, data product](docs/architecture-detail.svg)

[`docs/architecture-detail.svg`](docs/architecture-detail.svg) is today's
pipeline in full: the four APIs on the left (the crest images come from the
football API as well, which is why there are five sources), one Python file per
source, the warehouse with its three zones (`raw` as received, `staging` typed,
`curated` the data product), the SQL transformation, and the dashboard that
reads the result. Everything left of the warehouse is Python and everything
right of it is SQL; solid arrows are data, dashed ones are the platform that
runs, stores or records the work.

![Local path today versus cloud path for the final milestone](docs/architecture-target.svg)

[`docs/architecture-target.svg`](docs/architecture-target.svg) shows the same
pipeline with two destinations: the local path (PostgreSQL in Docker Compose) is
in place today, the cloud path (GCS bucket, BigQuery) is the final milestone,
and the platform row underneath carries both. The point of the picture is that
the ingestion and the SQL files stay the same - the cloud is a different target,
not a second pipeline.

One daily run, orchestrated by Dagster, in three steps:

| Step | Trigger | What it does |
| --- | --- | --- |
| **1. Ingest** | daily 06:00 Europe/Zurich, plus backfill on demand | Asks all five sources in order and stores every answer unchanged in `raw` - one row per source, question and day, written with an idempotent upsert. Nothing is transformed here |
| **2. Transform** | after a successful ingest | SQL files in order: `raw` → typed `staging` → `curated` facts, dimensions and the features that were known before kick-off |
| **3. Quality checks** | after the transformation | 24 checks stored in `meta.dq_results`; a CRITICAL failure fails the run, a WARNING stays visible |
| **Odds refresh** (own job) | every 15 min, configurable | Decides whether to spend a credit - once a day always, at the interval only while a watched match is within 48 h of kick-off, never below the quota reserve - then stores the fetch and rebuilds the odds change history |

**The rule that keeps this simple:** the ingestion may read the APIs, the files
under `data/` and the raw zone - never `staging`, never `curated`. That is not
only an intention: [`tests/test_layering.py`](tests/test_layering.py) searches
the ingestion code for those table names and fails if one appears. Three
read-only views on the raw zone make it possible: `raw.match_calendar` and
`raw.team_catalog` tell the later steps which matches and clubs exist, and
`raw.venue_coordinates` hands the weather step the coordinates the
OpenStreetMap step stored - all of it from answers, never from a built table.

* [Architecture v0.1](docs/architecture/architecture-v0.1.md) — the initial
  design with Mermaid diagrams for the conceptual, local and cloud views.
* [Architecture Decision Records](docs/adr/README.md) — data sources,
  orchestrator, raw storage, Champions League scope.
* Architecture v0.2 (midterm) will record what implementation changed.

## Batch Ingestion Strategy

One scheduled run per day, and inside it one rule:

> **Ingest everything first, transform afterwards.**

Every source is asked and every answer is stored before a single line of SQL
runs ([`src/deng/ingestion/runner.py`](src/deng/ingestion/runner.py) is that
step, all of it). The reason is the sentence worth saying out loud in a defence:
**the whole product can be rebuilt from the raw zone without asking an API
again.** If a transformation turns out to be wrong, we fix the SQL and re-run
it - the data is already here, no request budget is spent twice, and a source
that changes its answers tomorrow cannot change what we stored yesterday.

Load strategy per source, with the reasoning kept next to the code in the file
it belongs to:

| Source | How often | Strategy | Why |
|---|---|---|---|
| football-data.org: competition, teams, standings, matches ([`football_data.py`](src/deng/sources/football_data.py)) | every run, daily | **FULL** | four requests for the whole competition; matches are *added* mid-season (the December knockout draw) and kick-off times change in place, so a full reload is simpler than asking what changed - and it self-heals after a missed day |
| football-data.org: past seasons, `FOOTBALL_DATA_SEASONS` | **once** per season | **ONCE** | a finished season never changes again. One matches request and one teams request per season; `?season=2023` is part of the raw zone's key, so that answer sits next to today's instead of overwriting it |
| Open-Meteo: forecasts ([`open_meteo.py`](src/deng/sources/open_meteo.py)) | every run, daily | one request **per venue** with a match inside the 16-day horizon, **today only** | the forecast changes daily and every day's version is kept. A past date would return what the weather turned out to be, not what was predicted - so a backfill fetches no weather at all |
| The Odds API: 1X2 odds ([`the_odds_api.py`](src/deng/sources/the_odds_api.py)) | on a **credit budget** | **FULL per fetch, append-only** | one credit answers the whole competition, and every fetch is a new row because the intraday history *is* the data. Once a day as a baseline, at the configured interval only while a watched match is close to kick-off, never below the quota reserve |
| OpenStreetMap: stadium coordinates ([`openstreetmap.py`](src/deng/sources/openstreetmap.py)) | **once per club** | only clubs without a stored answer | stadiums do not move. On a normal day this step makes no request at all; when it does, it paces itself to one per second |
| club crests ([`club_crests.py`](src/deng/sources/club_crests.py)) | when a URL is new | **INCREMENTAL** by URL | a changed crest is published under a new URL, so a stored one is never fetched again |

Incremental loading of the daily endpoints via `lastUpdated` would cost an extra
request to discover what changed and would still miss the matches the API
*adds* mid-season. A full reload of a small, bounded payload is simpler and
costs one request. Past seasons are the exception, and they are exactly the
incremental case: fetched once, never again.

**Failure behaviour:** transient errors (429, 5xx, network) retry with
exponential back-off; 400/403/404 fail immediately because repeating them
cannot help and would spend the request budget. Requests are paced against the
`X-Requests-Available-Minute` header. Every run is recorded in
`meta.pipeline_runs`, failures included, with their error message. Crests and
odds are extras: a failure there is reported and recorded but does not fail the
run - the football data, which everything else rests on, does.

## Local Development

Requirements: **Python ≥ 3.10** (the version Ubuntu 22.04 LTS ships, so no
upgrade is needed), `make`, and on Debian/Ubuntu/WSL the `python3-venv` package
(`sudo apt install python3-venv`). Docker is needed for the containerised path.

```bash
git clone https://github.com/Elias-Martinelli/deng.git
cd deng

./setup.sh                 # venv + install + .env + self-check   (or: make setup)
make doctor                # interpreter, dependencies, .env, API key
make test                  # 137 tests; the database ones skip without PostgreSQL
make up                    # PostgreSQL in Docker, waits until healthy
make init                  # create schemas and tables (idempotent)
make run-samples           # ingest + transform + data quality, no API key needed
make verify                # verification queries
```

`setup.sh` picks the newest interpreter ≥ 3.10 that can actually build a
virtualenv and tells you which one it used; override with
`make setup PYTHON=python3.12`. Activating the venv is optional — every `make`
target uses `.venv` directly.

With an API key (free registration at
<https://www.football-data.org/client/register>), put it in `.env` and use the
live path:

```bash
make explore               # fetch fresh sample payloads and profile the schema
make run                   # ingest from the API + transform + data quality
```

Bookmaker odds are optional. With a free key from <https://the-odds-api.com>
in `.env` as `ODDS_API_KEY`:

```bash
make odds                  # = ingest --only odds; fetches if the budget rules allow
```

Without a key the step skips itself and says so; `make run-samples` replays two
committed sample fetches (fictional prices,
[`data/sample/the-odds-api/`](data/sample/the-odds-api/README.md)), so the whole
path works offline.

Stadium coordinates need no key and are asked once per season:

```bash
make venues                # = ingest --only openstreetmap
```

Offline, the committed answers in
[`data/sample/openstreetmap/`](data/sample/openstreetmap/) are replayed instead,
so `make run-samples` fills the venues too.

Past seasons as training data: set `FOOTBALL_DATA_SEASONS=2023,2024` in `.env`
and run `make ingest` once. Each season costs two requests; the answers stay in
the raw zone, so the transformation can be re-run from them at any time.

`make help` lists every target.

## PostgreSQL

Four schemas, separated by how far the data has been processed:

| Schema | Content |
|---|---|
| `raw` | every answer exactly as received (JSONB) plus who asked what and when - one table per source (`football_data`, `open_meteo`, `odds_api`, `osm_venues`, `team_crests`), the odds one append-only per fetch, plus three read-only views the ingestion plans its next questions with |
| `staging` | typed, flattened tables — rebuildable from raw at any time |
| `curated` | facts and dimensions: the data product |
| `meta` | `pipeline_runs`, `dq_results` |

`raw.football_data` holds **one row per (source, endpoint, request parameters,
ingestion date)**. A `UNIQUE` constraint on exactly that key plus
`INSERT … ON CONFLICT DO UPDATE` is what makes reruns safe; a `payload_hash`
over the canonical JSON shows whether the source actually changed that day.

### Entity-relationship diagram (simplified)

Keys and a few defining columns only; every column, grain and constraint is in
[`docs/data-model.md`](docs/data-model.md). `staging` is left out: it is the
typed copy of `raw`, connected by the transformations, not by foreign keys.

**The data product** — `dim_team` in the middle, one fact table per question:

```mermaid
erDiagram
    dim_team["curated.dim_team"] {
        bigint team_id PK
        text name
        text crest_url
    }
    dim_venue["curated.dim_venue"] {
        bigint team_id PK, FK
        numeric latitude
        numeric longitude
    }
    fact_match["curated.fact_match"] {
        bigint match_id PK
        bigint home_team_id FK
        bigint away_team_id FK
        timestamptz utc_kickoff
        text outcome
    }
    fact_team_match_form["curated.fact_team_match_form"] {
        bigint match_id PK, FK
        bigint team_id PK, FK
        int matches_considered
        int points_last_5
    }
    fact_match_weather["curated.fact_match_weather"] {
        bigint match_id PK, FK
        text weather_status
        numeric temperature_c
    }
    fact_match_prediction["curated.fact_match_prediction"] {
        bigint match_id PK, FK
        text model_version PK
        date as_of_date PK
        numeric home_prob
    }
    fact_bookmaker_odds["curated.fact_bookmaker_odds"] {
        bigint odds_id PK
        bigint match_id FK
        text bookmaker_key
        timestamptz source_updated_at
        numeric home_price
    }
    team_crests["raw.team_crests"] {
        text crest_url PK
        bytea image
    }

    dim_team ||--o{ fact_match : "home / away"
    fact_match ||--|{ fact_team_match_form : "2 per match"
    dim_team ||--o{ fact_team_match_form : "team_id"
    fact_match ||--|| fact_match_weather : "1 per match"
    fact_match ||--|{ fact_match_prediction : "1 per run date"
    fact_match ||--o{ fact_bookmaker_odds : "1 per odds change"
    dim_team ||--o| dim_venue : "home venue"
    dim_venue ||..o{ fact_match_weather : "venue_team_id"
    dim_team ||..o| team_crests : "crest_url"
```

**Run log and raw zone** — every raw row and every check result points to the
run that wrote it:

```mermaid
erDiagram
    direction LR
    pipeline_runs["meta.pipeline_runs"] {
        uuid run_id PK
        date logical_date
        text status
    }
    dq_results["meta.dq_results"] {
        bigint dq_result_id PK
        uuid run_id FK
        bool passed
    }
    football_data["raw.football_data"] {
        bigint raw_id PK
        uuid run_id FK
        jsonb payload
    }
    open_meteo["raw.open_meteo"] {
        bigint raw_id PK
        uuid run_id FK
        jsonb payload
    }
    osm_venues["raw.osm_venues"] {
        bigint raw_id PK
        uuid run_id FK
        jsonb payload
        text review_status
    }
    odds_api["raw.odds_api"] {
        bigint raw_id PK
        uuid run_id FK
        jsonb payload
    }
    team_crests["raw.team_crests"] {
        text crest_url PK
        uuid run_id FK
    }

    pipeline_runs ||--o{ football_data : "run_id"
    pipeline_runs ||--o{ open_meteo : "run_id"
    pipeline_runs ||--o{ osm_venues : "run_id"
    pipeline_runs ||--o{ odds_api : "run_id"
    pipeline_runs ||--o{ team_crests : "run_id"
    pipeline_runs ||--o{ dq_results : "run_id"
```

One table per source, all the same shape: the answer unchanged, plus the run
that fetched it. `raw.osm_venues` has one column the others do not need -
`review_status`, our own verdict about a stadium hit, stored next to the
untouched payload because a search can return the right name in the wrong city.

How to read it: `||` exactly one, `o|` zero or one, `|{` one or many,
`o{` zero or many. **Solid lines are foreign keys** enforced by PostgreSQL;
**dashed lines are join keys without a constraint**, on purpose:
`venue_team_id` - a club whose stadium OpenStreetMap could not resolve, or one
that is new after the knockout draw, must not abort the weather run; its matches
get `VENUE_UNKNOWN` and a WARNING check reports it. `crest_url` - a crest is
optional and fetched after the team exists.

DDL: [`sql/schema/`](sql/schema/) · transformations: [`sql/transform/`](sql/transform/) ·
verification: [`sql/verify/`](sql/verify/).

## Docker

```bash
make up            # PostgreSQL with a health check and a named volume
make docker-ingest # run the pipeline inside its own image
make docker-app    # Streamlit dashboard in a container → http://localhost:8501
make down          # stop (keeps data);  make reset  also deletes the volume
```

Services on one network: `postgres`, `dagster-webserver` and `dagster-daemon`
(started by `docker compose up -d`), the `pipeline` image for manual runs and
the `app` image (profile `app`). The pipeline is a batch job, not a daemon: the
orchestrator runs it on schedule, and `docker compose run` runs it by hand. Dependent services wait for
the database's *health check*, not merely for the container to exist, so a cold
start cannot fail with "connection refused". The app is a second build stage,
which keeps the pipeline image free of a web framework.

> **Docker not running?** Every Docker target first runs
> `scripts/ensure_docker.sh`: on Windows/WSL and macOS it starts Docker Desktop
> itself and waits until the engine answers (up to 3 minutes). On Linux it
> prints the command to start the daemon. If Docker Desktop starts but WSL
> still cannot see it, enable *Settings → Resources → WSL integration* for your
> distro once.

> **Port 5432 already taken?** If PostgreSQL is also installed natively, it
> keeps `localhost:5432` and host-side commands (`make init`, `make test`)
> silently talk to *that* database instead of the container. Set
> `POSTGRES_PORT=5433` in `.env` before `make up`. `ss -ltn | grep 5432` shows
> whether something is listening.

Executed end to end on an empty volume, including the three defects that the
first real run exposed: [evidence §11](docs/evidence/local-pipeline-run.md#11-docker-compose-executed-21-september-2026).

## Workflow Orchestration

**Dagster**, decided after a spike ([ADR-002](docs/adr/ADR-002-workflow-orchestrator.md)).
One asset per table, one daily partition per logical date:

```text
ingest — every source reads the APIs and the raw zone, never a built table
  raw/football_data ─┬─► raw/osm_venues ──► raw/open_meteo
                     ├─► raw/team_crests
                     └─► raw/odds_api                       (own job, every N minutes)

transform — SQL only                                        data quality
  raw/*  ──► staging/{matches, teams, standings, venues, weather_forecast, bookmaker_odds}
         ──► curated/{dim_team, dim_venue, fact_match, fact_team_match_form,
                      fact_match_prediction, fact_match_weather, fact_bookmaker_odds}  ──► meta/dq_results
```

```bash
make orchestrator          # PostgreSQL + Dagster webserver + daemon → http://localhost:3000
make dagster-backfill FROM=2026-09-15 TO=2026-09-17   # one run per day, one at a time
```

* **Schedule:** `daily_pipeline_schedule`, 06:00 Europe/Zurich, active as soon
  as the daemon runs. The 06:00 run ingests under *today's* date.
* **Second job:** `odds_refresh`, unpartitioned, every `ODDS_REFRESH_MINUTES`
  (default 15). Most ticks decide *not* to fetch: the asset applies the budget
  rules (daily baseline, watch window before kick-off, quota reserve) and
  records the reason in its metadata. Odds are not daily data, so they cannot
  share the daily partitions - hence the separate job.
* **Dependencies:** a failed ingest does not start the transform; a CRITICAL
  data-quality failure fails the run, a WARNING shows up in the asset metadata.
* **Retries:** only for transient errors (HTTP 429/5xx, network, database not
  reachable): 3 attempts, 1 → 2 → 4 minutes. A 403, a missing API key or a
  failed check fails at once - repeating it cannot change the answer.
* **Reruns and backfills:** re-materialise any partition in the UI or with
  `make dagster-backfill`. Safe because the raw load is an upsert and staging
  never overwrites newer data with older.
* **No API key?** Set `INGEST_SOURCE=samples` in `.env`; schedule and backfills
  then replay the committed payloads.
* **Without Docker:** `make setup-orchestrator && make dagster-dev`.

The assets call the same functions as the CLI, so the manual path still works
and is what the orchestrator runs. The CLI has seven commands, and that is all
of it:

```bash
python -m deng.pipeline init                    # create the schemas and tables (idempotent)
python -m deng.pipeline ingest                  # ask all five sources, store every answer
python -m deng.pipeline ingest --only weather   # one source: football|openstreetmap|crests|weather|odds
python -m deng.pipeline ingest --from-samples   # replay the committed answers, no API key needed
python -m deng.pipeline transform               # raw -> staging -> curated, all sources
python -m deng.pipeline dq                      # the 24 data-quality checks
python -m deng.pipeline run --date 2026-09-18   # ingest + transform + dq, in that order
python -m deng.pipeline backfill --from 2026-09-01 --to 2026-09-10
python -m deng.pipeline verify                  # the verification queries
```

`ingest`, `transform` and `run` take `--date`, `backfill` takes `--from` and
`--to`, the rest need no date. There is no separate `crests`, `weather` or
`odds` command any more: fetching is part of `ingest`, building tables is part
of `transform`. The `make` targets are one-line wrappers around exactly these
calls.

## Transformation

Thirteen SQL files in [`sql/transform/`](sql/transform/), executed in the order
their numbers give. The number says which layer a file builds - 1xx staging,
2xx/3xx/4xx curated - so the list reads top to bottom like the pipeline itself.

| # | File | Produces |
|---|---|---|
| 1 | `110_staging_matches.sql` | `staging.matches` from the raw JSON |
| 2 | `111_staging_teams.sql` | `staging.teams` |
| 3 | `112_staging_standings.sql` | `staging.standings` (one snapshot per day) |
| 4 | `210_dim_team.sql` | `curated.dim_team` |
| 5 | `220_fact_match.sql` | `curated.fact_match` incl. the derived outcome |
| 6 | `230_fact_team_match_form.sql` | `curated.fact_team_match_form`: each team's form going into the match |
| 7 | `240_fact_match_prediction.sql` | `curated.fact_match_prediction`: the baseline forecast, one per match and run date |
| 8 | `305_staging_venues.sql` | `staging.venues` from the stored OpenStreetMap answers |
| 9 | `310_staging_weather_forecast.sql` | `staging.weather_forecast` (hourly, one version per day) |
| 10 | `320_dim_venue.sql` | `curated.dim_venue` |
| 11 | `330_fact_match_weather.sql` | `curated.fact_match_weather`: the forecast, or the reason there is none |
| 12 | `410_staging_bookmaker_odds.sql` | `staging.bookmaker_odds`: one row per quoted outcome of every fetch not staged yet |
| — | `deng.transformation.odds_matching` | `staging.odds_event_match`: bookmaker event → our fixture, by kick-off time, name similarity and aliases. Python, because it is string matching, not set logic - and a transformation, because it reads curated tables |
| 13 | `420_fact_bookmaker_odds.sql` | `curated.fact_bookmaker_odds`: one row per odds change, with the margin removed |

They run in three transactions - 1–7 football, 8–11 weather, 12–13 odds with the
event matcher in between - because the later ones read what the earlier ones
wrote (`320` needs `dim_team`, `330` and `420` need `fact_match`). Each
transaction either lands completely or not at all, so the tables are never
half-built.

Why the non-trivial ones look the way they do:

* **`fact_match`** derives `outcome` from the goals instead of copying the
  API's `score.winner`, so the ML label can never contradict the numbers in its
  own row, and derives `is_upcoming` from the kick-off time instead of the
  status string, which the source uses inconsistently.
* **`fact_team_match_form`** computes each team's last-5 form from matches
  finished *strictly before* that match's kick-off. This directly serves the
  use case (the app shows it, a model would train on it) and is the mechanism
  that prevents data leakage.
* **`fact_match_weather`** takes the newest forecast *fetched before kick-off*
  for the kick-off hour - the same leakage rule - and gives every match a
  `weather_status` (`AVAILABLE`, `NOT_YET_AVAILABLE`, `VENUE_UNKNOWN`,
  `NOT_CAPTURED`, `MISSING`) instead of a silent null.
* **`fact_match_prediction`** is the baseline model `form-poisson-v1`, in SQL:
  Poisson goal rates from the league's home/away averages and each team's
  last-5 attack and defence, every input restricted to matches finished
  before the predicted match's kick-off. One row per match and run date,
  so the forecast is versioned and a comparison can use the forecast that
  existed when the odds were read. It is the thing the odds are compared
  with, not a claim to beat the market.
* **`model_features`** is a view on top of all of them: one row per match, the
  label plus every feature known before kick-off. It adds no logic of its own -
  it is where a reader (or a model) sees the result of all thirteen files at
  once.
* **`fact_bookmaker_odds`** keeps one row per *odds change* per bookmaker
  and market - the bookmaker's own timestamp, the prices, and the fetch
  interval in which we saw them - and removes the margin using the three
  prices of the same bookmaker at the same moment, never mixing bookmakers
  or moments.

The logic lives in `.sql` files rather than Python strings so it can be read,
reviewed and run by hand in `psql` — and so the BigQuery versions are the same
statements in a different dialect rather than a rewrite.

## Data Model

Grains, keys, facts and dimensions: [`docs/data-model.md`](docs/data-model.md).
Every grain is also a `COMMENT ON TABLE` in the database, so the documentation
cannot drift away from the schema. Eleven DDL files in
[`sql/schema/`](sql/schema/) create all of it, and `make init` can be re-run at
any time.

The one thing to look at first is the view
[`curated.model_features`](sql/schema/011_model_features.sql): **one row per
match, the label plus every feature known before kick-off** - exactly what a
model would read, and what the dashboard shows. It is a view rather than a
table because it only joins curated tables that already exist, so there is
nothing to keep in sync; the snapshot table planned for the final milestone
adds the missing dimension, one row per match *per day*.

## Data Quality

Twenty-four checks - 16 CRITICAL, 8 WARNING - run after every transformation
([`src/deng/quality/checks.py`](src/deng/quality/checks.py)) and are persisted
to `meta.dq_results`, so "was the data good on 18 September?" is a query rather
than an archaeology exercise in old logs.

* **CRITICAL** failures fail the run: empty fact table, duplicate business
  keys, matches lost between staging and curated, a team playing itself, a
  finished match without an outcome, an outcome that disagrees with the goals,
  a match without exactly two form rows, form counts that do not add up, form
  built on matches that were not yet played, a team missing from `dim_team`.
* **WARNING** failures are recorded and visible but do not stop the pipeline:
  implausible scores, and how well populated the form window currently is
  (early in a season most teams have fewer than three completed matches — real
  and worth knowing, not a reason to discard the run).
* **Forecast and odds:** every match has a forecast and its probabilities sum
  to 1 (CRITICAL); a bookmaker's fair probabilities sum to 1 and an incomplete
  quote has none (CRITICAL); prices and margins plausible, every bookmaker
  event resolved to a fixture, and a fresh fetch when a match is within 24 h
  (WARNING). The odds checks pass on an empty odds zone, so a reviewer without
  a key never sees a failure from them.
* **Completeness of the side data:** every club has a venue row - resolved or
  with a stored reason - and a crest (both WARNING: a missing picture or a
  stadium we could not verify is worth seeing, not worth failing a run for).

```bash
make dq        # run the checks; non-zero exit on a CRITICAL failure
```

## Reproducibility

Treated as a feature in its own right:

* `setup.sh` / `make setup` need no pyenv, direnv or conda — only the standard
  library's `venv`.
* `--from-samples` runs the entire pipeline against committed payloads, so a
  reviewer can reproduce every result **before registering an API key**.
* CI runs lint, 137 tests and a two-run idempotency smoke test against a real
  PostgreSQL, on Python 3.10 and 3.12.
* Every number in [`docs/evidence/`](docs/evidence/) is console output from a
  command in this README, not a description of one.

Two environment bugs were found this way and fixed: `make` targets resolving
`pytest` from `PATH` instead of the project venv, and interpreter detection
accepting a `python3.12` whose `ensurepip` is missing.

## Verification

| Command | Verifies | Expected |
|---|---|---|
| `make doctor` | interpreter, dependencies, `.env`, no tracked secrets | `Ready.` |
| `make test` | 137 tests: config, API client, source schemas, loader, transformations, weather, crests, odds, DQ, orchestration, app components, and the architecture rule (`test_layering.py`) | `137 passed` (fewer without a database: the integration tests skip; the orchestration tests need `make setup-orchestrator`) |
| `make lint` | formatting and static checks | `All checks passed!` |
| `make verify` | raw zone, business keys, run log, odds and forecast | `3/3 queries passed`, exit 0 |
| `make dq` | curated-layer data quality | `24/24 checks passed` with past seasons ingested; `23/24` with the current season only - the open WARNING is the form window early in a season. Exit 0 either way |

Worked examples with real output:
[`docs/evidence/local-pipeline-run.md`](docs/evidence/local-pipeline-run.md).

## Analytics / Notebook

[`notebooks/01_explore_curated_data.ipynb`](notebooks/01_explore_curated_data.ipynb)
explores the curated layer: what is in the warehouse, the fixtures, the outcome
distribution, form and its coverage, plus a query that **re-verifies the
leakage guard independently** of the pipeline's own checks.

```bash
make setup-app     # installs the Streamlit and Jupyter extras
make notebook      # JupyterLab with the project environment
```

Rule: exploration belongs in the notebook, pipeline logic in `src/` and `sql/`.
If a query becomes part of the product, it moves into a transformation and gets
a test.

## Streamlit Application

```bash
make app           # http://localhost:8501   (or: make docker-app)
```

**An analysis dashboard for the model data, not the product.** It answers the
question this project exists for - *could someone train a match-outcome model on
this, and what exactly would they get?* - in four panels. The first three read
`curated.model_features`, the same view a model would read:

* **The dataset** - how many matches, how many of them already carry a label,
  per season, with the first and last match date. More seasons is the lever, and
  the caption says what one costs.
* **Feature coverage** - for how many matches each feature is present, and the
  honest reason when it is not ("kick-off beyond the 16-day forecast horizon"),
  plus the number of matches per weather state. A gap with a reason is data; a
  silent null would be a bug.
* **Leakage guarantees** - the three rules that make the features usable (form
  uses only matches finished before kick-off, the forecast was fetched before
  kick-off, every match has exactly two form rows), each **recomputed in the
  page from the tables** instead of quoted from the pipeline.
* **One match in detail**, underneath: kick-off (Zurich time), venue, both
  teams' form as W/D/L badges with the number of matches behind it, the weather
  state, previous meetings and recent results - the same row a model would get,
  in a shape a person can sanity-check.

Status chips at the top show data freshness and the latest data-quality result;
the sidebar holds the run log and every check. The dashboard earns no points on
its own; it makes the curated tables inspectable in a defence.

**Model forecast vs. bookmaker odds.** For the chosen fixture, one card per
bookmaker (selectable, several side by side): the model's HOME / DRAW / AWAY
probability and its odds (1 / p), the bookmaker's current 1X2 odds (regular
time incl. stoppage time) and the margin-free market probability from that
bookmaker's three prices, and the difference in percentage points - labelled
a *model deviation*, never a betting edge. The forecast's timestamp and the
odds' timestamp (the bookmaker's own, plus when the pipeline read it and how
old that is) are shown separately. Stale, withdrawn and incomplete quotes are
flagged in words. During a match the forecast is labelled as the pre-match
forecast: a live comparison is not offered until a live model exists
(backlog 12.3). A chart below shows how each bookmaker's quote and the
forecast moved towards kick-off (steps: a quote holds until changed), with a
table view. All numbers are fictional until a real key has fetched real
odds; the sample fetches say so on the page.

**One page for desktop, iPhone and Android.** Instead of a native app, the
dashboard is a responsive web page: cards on a CSS grid that switch from two
columns to one below 640 px, no tables that scroll sideways on a phone. Open the
URL on a phone in the same network, or use "Add to Home Screen" for an app-like
icon. Verified by rendering in Chrome with the iPhone 15 and Pixel 7 device
profiles (no horizontal overflow at 393 / 412 px) - see
[evidence §13](docs/evidence/local-pipeline-run.md#13-responsive-viewer-desktop-iphone-android-21-september-2026).
Native apps were rejected: an iPhone build needs a Mac with Xcode, both need an
API layer in front of the database, and none of it is assessed.

| Desktop | iPhone 15 | Pixel 7 |
|---|---|---|
| ![desktop](docs/evidence/streamlit-app.png) | ![iPhone](docs/evidence/streamlit-iphone.png) | ![Android](docs/evidence/streamlit-android.png) |

The screenshots were taken before the dataset panels were added and show the
match-detail part of the page, which now sits underneath them.

**The app never calls an external API** - nor loads anything from the internet
(no web fonts, no crest images from the API's CDN). Selecting a fixture runs a
SQL query against our curated tables; the odds too were fetched by the
pipeline under its credit budget, so reloading the page can never spend one. A frontend calling football-data.org on
each click would be quicker to write and would make the pipeline pointless: no
history, no reproducibility, no point-in-time correctness, and a rate limit
shared with every visitor.

## Google Cloud Architecture

*Planned for the final submission* - the right-hand path in
[`docs/architecture-target.svg`](docs/architecture-target.svg). Ingestion writes
raw JSON straight to a GCS bucket (`raw/source=…/endpoint=…/ingestion_date=…/run_id.json`); BigQuery loads
staging from GCS and builds curated tables with `MERGE`, partitioned by
`match_date` / `snapshot_date` and clustered by team and match ids. Terraform
provisions the bucket, the dataset, a service account and IAM bindings. The
production path must not depend on local storage — the raw writer is already an
abstraction for exactly that swap.

## Known Limitations

Documented honestly, because hidden failures cost more than known ones:

* **No line-ups, injuries, player or match statistics** on the free tier.
* **Champions League only, by decision** ([ADR-004](docs/adr/ADR-004-champions-league-scope.md)):
  form, rest days and results ignore domestic matches for every club. Windows
  are therefore small (at most 8 league-phase matches), which
  `matches_considered` makes visible.
* **Past seasons are ingested on demand, not by default.**
  `FOOTBALL_DATA_SEASONS` is empty in a daily run, which gives 144 matches;
  with `2023,2024` it is 458. How many of the 47 listed seasons a training set
  should have is still an open decision.
* **The training table is still to come.** `curated.model_features` is one row
  per match, as the data looks today. The snapshot table
  `curated.fact_match_snapshot` - one row per match *per day*, which is what
  makes "what was known ten days before kick-off?" a query - is planned for the
  final milestone.
* **Backfill re-labels, it does not reconstruct.** The API always answers with
  today's state, so a backfill for 17 September writes today's data under that
  logical date. It recovers missed runs and enables re-processing; it does not
  recover what the API would have said back then.
* **Weather exists only inside 16 days, and never backwards.** A match further
  out is `NOT_YET_AVAILABLE` (the AVAILABLE path is proven by integration
  tests, [evidence](docs/evidence/weather.md)); a match already played is
  `NOT_CAPTURED`, because a forecast cannot be fetched after the fact - the
  post-match actuals from the archive API are backlog 2.7.
* **No weather for Shakhtar and Sabah home matches** (`VENUE_UNKNOWN`):
  OpenStreetMap gives no verified venue for them, and a guessed location would
  be worse than an honest gap. The reason is stored with the club, in
  [`openstreetmap.py`](src/deng/sources/openstreetmap.py).
* **The forecast is for the hour containing the kick-off** (18:45 → 18:00 UTC),
  not an average over the match.
* **Bookmaker odds: no live fetch yet.** The committed sample fetches follow
  The Odds API's documented schema with fictional prices; the first real fetch
  needs a personal key (backlog 13.5). The free budget of 500 credits a month
  covers roughly two watched matchdays at 15-minute resolution -
  `ODDS_WATCH_MATCH_IDS` and `ODDS_REFRESH_MINUTES` are the levers.
* **The baseline model is a baseline.** `form-poisson-v1` runs on at most
  five Champions League matches per club; its deviation from the market is a
  statement about the model, not about the market. Fair probabilities remove
  the margin proportionally, which ignores the favourite-longshot bias.
* **No live comparison.** During a match the app shows the pre-match forecast
  against the last odds read and says so; the interval job does not fetch for
  matches already kicked off.
* **Tests share the local database** and empty its tables; run `make
  run-samples` again after `make test`.
* The knockout fixtures do not exist until the December draw, so the fixture
  list is currently the 144-match league phase.

## Project Status

| Milestone | Deadline | Status |
|---|---|---|
| Milestone 1 — initial pitch | week 3 | **complete** — use case, verified sources, Architecture v0.1, ADRs, backlog |
| Midterm — local pipeline | 22 Oct 2026, 15:30 | **largely complete** — ingestion, raw zone, transformations, curated model, data quality, Dagster orchestration, Docker Compose verified, Streamlit, notebook. Open: raw validation, Architecture v0.2, clean-environment test |
| Final — cloud pipeline | 10 Dec 2026, 20:00 | not started |

Rubric coverage: [`docs/rubric-checklist.md`](docs/rubric-checklist.md) ·
Backlog: [`docs/project-backlog.md`](docs/project-backlog.md).

## Repository Layout

```text
.
├── README.md
├── setup.sh                  # one-command setup (no pyenv/direnv/conda needed)
├── Makefile                  # setup · test · up · run · verify · app · notebook
├── docker-compose.yml        # postgres + Dagster + pipeline + app on one network
├── Dockerfile                # three stages: pipeline, app, orchestrator
├── orchestrator/             # Dagster instance + workspace config (DAGSTER_HOME)
├── pyproject.toml            # dependencies and extras (dev / app / notebook)
├── .env.example              # configuration template — copy to .env
│
├── src/deng/
│   ├── config.py             # validated settings from the environment
│   ├── pipeline.py           # CLI: init · ingest · transform · dq · run · backfill · verify
│   ├── sources/              # one file per source, each answering the same two questions
│   │                         #   (plan: what to fetch · fetch: how):
│   │                         #   football_data · openstreetmap · club_crests ·
│   │                         #   open_meteo · the_odds_api  (+ http.py: the two error types)
│   ├── ingestion/            # runner.py: THE ingestion — the five sources, in order
│   │                         #   raw_reads.py: the few questions it may ask the raw zone
│   ├── database/             # connections, idempotent raw loader, run log
│   ├── transformation/       # ordered SQL execution + odds_matching.py (event → fixture)
│   ├── orchestration/        # Dagster assets, schedule, retry policy
│   └── quality/              # the twenty-four data-quality checks
│
├── sql/
│   ├── schema/               # 11 DDL files (applied by `make init`)
│   ├── transform/            # 13 files: raw → staging → curated
│   └── verify/               # verification queries
│
├── app/                      # the dashboard: dataset panels, odds section, HTML components
├── notebooks/                # exploration
├── tests/                    # 137 tests: unit, contract, integration, layering rule
├── data/sample/              # committed API answers — the offline path
├── data/reference/           # bookmaker_team_aliases.csv
└── docs/
    ├── architecture-overview.svg · architecture-detail.svg · architecture-target.svg
    ├── use-case.md · data-sources.md · data-model.md
    ├── rubric-checklist.md · project-backlog.md
    ├── architecture/ · adr/ · evidence/
```

Two sentences that explain the whole layout: **`sources/` asks, `sql/` builds,
and nothing in `sources/` or `ingestion/` may read what `sql/` built.** The
Makefile and the CLI are wrappers; the Dagster assets call the same functions.

## Contributing and Branch Strategy

Two students, both responsible for the whole architecture.

* `main` is always working: CI green, `make run-samples` succeeds.
* Work happens on `feat/<topic>`, `fix/<topic>` or `docs/<topic>` branches.
* Conventional commit messages: `feat:`, `fix:`, `docs:`, `test:`, `refactor:`,
  `ci:`, `chore:`. The body explains *why*, not what the diff already shows.
* **Nobody merges their own pull request.** The reviewer must be able to
  explain the change in the oral defence — that is the actual purpose of the
  review, not style policing.
* A change is done when it is implemented, tested, documented and its evidence
  is reproducible.

Division of responsibilities (ownership means "drives it and writes the docs",
not "the only one who understands it"):

| Area | Owner | Reviewer |
|---|---|---|
| Football ingestion, API client, raw model | Elias Martinelli | Noah Rodriguez |
| Weather ingestion, venue reference data | Noah Rodriguez | Elias Martinelli |
| Transformations, data model, data quality | Noah Rodriguez | Elias Martinelli |
| Orchestration, Docker, Makefile, CI | Elias Martinelli | Noah Rodriguez |
| Streamlit app and notebook | Noah Rodriguez | Elias Martinelli |
| Terraform, GCS, BigQuery model | shared — paired session, then split by table | — |
| Documentation and evidence | each documents what they built | — |

## Authors

| | Author | GitHub | E-mail |
| --- | --- | --- | --- |
| <img src="https://github.com/Elias-Martinelli.png?size=80" width="40" alt=""> | **Elias Martinelli** | [@Elias-Martinelli](https://github.com/Elias-Martinelli) | <elias.martinelli@stud.hslu.ch> |
| <img src="https://github.com/Noah-Rod.png?size=80" width="40" alt=""> | **Noah Rodriguez** | [@Noah-Rod](https://github.com/Noah-Rod) | <noah.rodriguez@stud.hslu.ch> |

HSLU, module DENG (Data Engineering), autumn semester 2026.
