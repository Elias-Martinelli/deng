# Champions League Match Intelligence Data Platform

HSLU · DENG – Data Engineering · HS26 · End-to-End Batch Data Pipeline

[![CI](https://github.com/Elias-Martinelli/deng/actions/workflows/ci.yml/badge.svg)](https://github.com/Elias-Martinelli/deng/actions/workflows/ci.yml)

A reproducible daily batch pipeline that turns UEFA Champions League fixtures,
results, standings and team data into a curated, point-in-time-correct
pre-match dataset — served to a notebook, a Streamlit viewer and, later, to
machine learning.

![Data pipeline architecture](docs/architecture.svg)

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
given point in time** — the property that makes the data usable both for a
pre-match overview and as leakage-free training data.

## Problem Statement

Assembling a consistent pre-match picture means integrating several APIs
repeatedly, reconciling their keys, and recording *when* each piece of
information became available. Doing that by hand is error-prone; doing it in
the frontend on every click throws away history and burns a shared rate limit.
Details: [`docs/use-case.md`](docs/use-case.md).

## End User

* **Primary:** football analysts and interested users who want a structured
  pre-match overview of an upcoming fixture.
* **Secondary:** data scientists who need a point-in-time-correct feature table
  to train and evaluate match-outcome models.

## Data Product

| Table | One row represents | Status |
|---|---|---|
| `curated.fact_match` | one Champions League match | **implemented** |
| `curated.fact_team_match_form` | one team's participation in one match, with its form going in | **implemented** |
| `curated.dim_team` | one team | **implemented** |
| `curated.fact_match_snapshot` | one upcoming match on one pipeline run date | planned (final) |
| `curated.dim_venue`, `dim_date` | one venue / calendar day | planned (final) |

Full definitions, keys and reasoning: [`docs/data-model.md`](docs/data-model.md).

## Use Case

Select an upcoming fixture — say *RC Lens vs Sporting CP, 13 Oct 2026* — and
see the kick-off, venue, both teams' recent form (with the number of matches
that form rests on), previous meetings and recent results. Everything is served
from our own tables; the app makes no API calls.

Secondary: analyse how many days before kick-off each attribute group becomes
available, and train a baseline HOME/DRAW/AWAY classifier on features that
existed before the match.

## Data Sources

| Source | Content | Access | Limits (free tier) |
|---|---|---|---|
| [football-data.org v4](https://www.football-data.org) | CL fixtures, results, standings, teams, referees, head-to-head | REST/JSON, `X-Auth-Token`, free registration | 10 requests/min; no line-ups, injuries or match statistics; 11 of 36 clubs without domestic-league data |
| [Open-Meteo](https://open-meteo.com) | 16-day hourly forecast for the kick-off hour | REST/JSON, no key | 10 000 calls/day, CC BY 4.0 |
| [OpenStreetMap](https://www.openstreetmap.org) via `make venues` | stadium coordinates, once per season → `data/reference/venues.csv` | Nominatim, 1 req/s | ODbL |
| `data/reference/venues.csv` *(planned)* | stadium coordinates and time zones | versioned in this repo | maintained by hand |

Evaluation including rejected alternatives: [`docs/data-sources.md`](docs/data-sources.md).
Decision: [ADR-001](docs/adr/ADR-001-football-data-source.md) (ACCEPTED).
Measured behaviour of the live API: [`docs/evidence/api-exploration.md`](docs/evidence/api-exploration.md).

## Data Characteristics

* **Volume** (measured 20 Sep 2026): 144 league-phase matches, 36 teams, one
  standings table. ≈ 60 API calls and < 2 MB raw per daily run; < 1 GB per
  season. All 47 listed seasons together are roughly 5 000–6 500 matches.
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
| `odds` is a stub object with a marketing message | not parsed; validation checks for expected keys, not field presence |
| 11 of 36 clubs have no domestic-league data in the free tier | scope is Champions League only for every club ([ADR-004](docs/adr/ADR-004-champions-league-scope.md)), so form is comparable across all 36 |
| `group` null since the 2024/25 format change | no group dimension modelled |
| Matches rescheduled or postponed | full reload per day; the raw zone keeps each day's version |

## Architecture

The diagram at the top shows the local stack. One daily run, orchestrated by
Dagster, in three steps:

| Step | Trigger | What it does |
| --- | --- | --- |
| **1. Ingest** | daily 06:00 Europe/Zurich, plus backfill on demand | Fetches fixtures, results, teams and standings; forecasts for matches ≤ 16 days ahead; missing club crests. Stores every answer unchanged in `raw` with an idempotent upsert per day |
| **2. Transform** | after a successful ingest | SQL in one transaction: `raw` → typed `staging` → `curated` facts and dimensions, incl. point-in-time form and the weather status per match |
| **3. Quality checks** | after the transformation | 18 checks stored in `meta.dq_results`; a CRITICAL failure fails the run, a WARNING stays visible |

Colours in the diagram: grey = outside world (sources, consumers), blue =
processing step, purple = storage and orchestration; dashed = control, not
data. The source of the picture is [`docs/architecture.svg`](docs/architecture.svg)
(plain SVG, readable in light and dark mode).

* [Architecture v0.1](docs/architecture/architecture-v0.1.md) — the initial
  design with Mermaid diagrams for the conceptual, local and cloud views.
* [Architecture Decision Records](docs/adr/README.md) — data sources,
  orchestrator, raw storage, Champions League scope.
* Architecture v0.2 (midterm) will record what implementation changed.

## Batch Ingestion Strategy

One scheduled run per day. Each run: **extract → store raw → transform →
data-quality checks**.

Load strategy per endpoint — all **FULL** at this stage, with the reasoning
kept next to the code in [`src/deng/ingestion/extract.py`](src/deng/ingestion/extract.py):

| Endpoint | Rows | Strategy | Why |
|---|---|---|---|
| `competitions/CL` | 47 seasons | FULL | 9 KB, changes rarely |
| `competitions/CL/teams` | 36 | FULL | feeds `dim_team`, stable within a season |
| `competitions/CL/standings` | 36 | FULL | changes every matchday, one request |
| `competitions/CL/matches` | 144 | FULL | 212 KB in one request |
| Open-Meteo `v1/forecast` | 1 per venue with a match ≤ 16 days ahead | FULL per venue and day, **today only** | the forecast changes daily and every day's version is kept; a past date would return analysis data, not a forecast |
| club crests | 36 images | **INCREMENTAL** by URL | a changed crest gets a new URL, so a stored one is never fetched again |

Incremental loading via `lastUpdated` would cost an extra request to discover
what changed and would still miss matches the API *adds* mid-season. A full
reload of a small bounded payload is simpler, self-heals after a missed day and
costs one request. That stops being true once we ingest many seasons at once —
then incremental *by season* is the plan (backlog 1.9).

**Failure behaviour:** transient errors (429, 5xx, network) retry with
exponential back-off; 400/403/404 fail immediately because repeating them
cannot help and would spend the request budget. Requests are paced against the
`X-Requests-Available-Minute` header. Every run is recorded in
`meta.pipeline_runs`, failures included, with their error message.

## Local Development

Requirements: **Python ≥ 3.10** (the version Ubuntu 22.04 LTS ships, so no
upgrade is needed), `make`, and on Debian/Ubuntu/WSL the `python3-venv` package
(`sudo apt install python3-venv`). Docker is needed for the containerised path.

```bash
git clone https://github.com/Elias-Martinelli/deng.git
cd deng

./setup.sh                 # venv + install + .env + self-check   (or: make setup)
make doctor                # interpreter, dependencies, .env, API key
make test                  # 96 tests; the database ones skip without PostgreSQL
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

`make help` lists every target.

## PostgreSQL

Four schemas, separated by how far the data has been processed:

| Schema | Content |
|---|---|
| `raw` | API payloads exactly as received (JSONB) plus ingestion metadata |
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
    team_crests["raw.team_crests"] {
        text crest_url PK
        bytea image
    }

    dim_team ||--o{ fact_match : "home / away"
    fact_match ||--|{ fact_team_match_form : "2 per match"
    dim_team ||--o{ fact_team_match_form : "team_id"
    fact_match ||--|| fact_match_weather : "1 per match"
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
    team_crests["raw.team_crests"] {
        text crest_url PK
        uuid run_id FK
    }

    pipeline_runs ||--o{ football_data : "run_id"
    pipeline_runs ||--o{ open_meteo : "run_id"
    pipeline_runs ||--o{ team_crests : "run_id"
    pipeline_runs ||--o{ dq_results : "run_id"
```

How to read it: `||` exactly one, `o|` zero or one, `|{` one or many,
`o{` zero or many. **Solid lines are foreign keys** enforced by PostgreSQL;
**dashed lines are join keys without a constraint**, on purpose:
`venue_team_id` - a club missing from `venues.csv` (e.g. new after the
knockout draw) must not abort the weather run; its matches get `VENUE_UNKNOWN`
and a WARNING check reports it. `crest_url` - a crest is optional and fetched
after the team exists.

DDL: [`sql/schema/`](sql/schema/) · transformations: [`sql/transform/`](sql/transform/) ·
verification: [`sql/verify/`](sql/verify/).

## Docker

```bash
make up            # PostgreSQL with a health check and a named volume
make docker-ingest # run the pipeline inside its own image
make docker-app    # Streamlit viewer in a container → http://localhost:8501
make down          # stop (keeps data);  make reset  also deletes the volume
```

Services on one network: `postgres`, `dagster-webserver` and `dagster-daemon`
(started by `docker compose up -d`), the `pipeline` image for manual runs and
the `app` image (profile `app`). The pipeline is a batch job, not a daemon: the
orchestrator runs it on schedule, and `docker compose run` runs it by hand. Dependent services wait for
the database's *health check*, not merely for the container to exist, so a cold
start cannot fail with "connection refused". The app is a second build stage,
which keeps the pipeline image free of a web framework.

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
raw/football_data ──► staging/{matches,teams,standings} ──► curated/{dim_team,fact_match,fact_team_match_form} ─┐
curated/dim_team  ──► raw/team_crests ─────────────────────────────────────────────────────────────────────────────┼─► meta/dq_results
curated/fact_match ─► raw/open_meteo ──► staging/weather_forecast ──► curated/{dim_venue,fact_match_weather} ──────┘
      ingest                         transform (one transaction)                                         data quality
```

```bash
make orchestrator          # PostgreSQL + Dagster webserver + daemon → http://localhost:3000
make dagster-backfill FROM=2026-09-15 TO=2026-09-17   # one run per day, one at a time
```

* **Schedule:** `daily_pipeline_schedule`, 06:00 Europe/Zurich, active as soon
  as the daemon runs. The 06:00 run ingests under *today's* date.
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
and is what the orchestrator runs:

```bash
python -m deng.pipeline run --date 2026-09-18
python -m deng.pipeline backfill --from 2026-09-01 --to 2026-09-10
```

## Transformation

SQL files executed in order inside **one transaction**: either every curated
table is consistent with the same staging state, or nothing changed and the
previous data product is still there.

| Step | File | Produces |
|---|---|---|
| 1 | `110_staging_matches.sql` | `staging.matches` from raw JSONB |
| 2 | `111_staging_teams.sql` | `staging.teams` |
| 3 | `112_staging_standings.sql` | `staging.standings` (one snapshot per day) |
| 4 | `210_dim_team.sql` | `curated.dim_team` |
| 5 | `220_fact_match.sql` | `curated.fact_match` incl. derived outcome |
| 6 | `230_fact_team_match_form.sql` | `curated.fact_team_match_form` |
| 7 | `310_staging_weather_forecast.sql` | `staging.weather_forecast` (hourly, one version per day) |
| 8 | `320_dim_venue.sql` | `curated.dim_venue` from `venues.csv` |
| 9 | `330_fact_match_weather.sql` | `curated.fact_match_weather`: forecast or reason, per match |

Steps 7–9 are a **second transaction**: which forecasts to fetch is read from
`fact_match`, so the weather can only be fetched after steps 1–6 committed.

Justification for the two non-trivial ones:

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

The logic lives in `.sql` files rather than Python strings so it can be read,
reviewed and run by hand in `psql` — and so the BigQuery versions are the same
statements in a different dialect rather than a rewrite.

## Data Model

Grains, keys, facts and dimensions: [`docs/data-model.md`](docs/data-model.md).
Every grain is also a `COMMENT ON TABLE` in the database, so the documentation
cannot drift away from the schema.

## Data Quality

Eighteen checks run after every transformation
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

```bash
make dq        # run the checks; non-zero exit on a CRITICAL failure
```

## Reproducibility

Treated as a feature in its own right:

* `setup.sh` / `make setup` need no pyenv, direnv or conda — only the standard
  library's `venv`.
* `--from-samples` runs the entire pipeline against committed payloads, so a
  reviewer can reproduce every result **before registering an API key**.
* CI runs lint, 96 tests and a two-run idempotency smoke test against a real
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
| `make test` | 96 tests: config, API client, source schema, loader, transformations, weather, crests, DQ, orchestration, app components | `96 passed` (or `54 passed, 42 skipped` without a database; the 9 orchestration tests need `make setup-orchestrator`) |
| `make lint` | formatting and static checks | `All checks passed!` |
| `make verify` | raw zone, business keys, run log | `2/2 queries passed`, exit 0 |
| `make dq` | curated-layer data quality | `17/18 checks passed`, exit 0 |

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

Pick an upcoming fixture and see kick-off (Zurich time), venue, both teams'
form as W/D/L badges with the number of matches behind it, previous meetings
and recent results. Status chips at the top show data freshness and the latest
data-quality result; the sidebar holds the details.

**One page for desktop, iPhone and Android.** Instead of a native app, the
viewer is a responsive web page: cards on a CSS grid that switch from two
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

**The app never calls an external API** - nor loads anything from the internet
(no web fonts, no crest images from the API's CDN). Selecting a fixture runs a
SQL query against our curated tables. A frontend calling football-data.org on
each click would be quicker to write and would make the pipeline pointless: no
history, no reproducibility, no point-in-time correctness, and a rate limit
shared with every visitor.

## Google Cloud Architecture

*Planned for the final submission.* Ingestion writes raw JSON straight to a GCS
bucket (`raw/source=…/endpoint=…/ingestion_date=…/run_id.json`); BigQuery loads
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
* **Historical seasons are available but not ingested yet.** The API serves
  them (verified); how many to load is an open decision (backlog 1.9).
* **Backfill re-labels, it does not reconstruct.** The API always answers with
  today's state, so a backfill for 17 September writes today's data under that
  logical date. It recovers missed runs and enables re-processing; it does not
  recover what the API would have said back then.
* **Weather: first real forecast on 28 September.** Matchday 2 is 22 days
  after this writing; forecasts reach 16. Until then every upcoming match is
  `NOT_YET_AVAILABLE` - the AVAILABLE path is proven by integration tests
  ([evidence](docs/evidence/weather.md)).
* **No weather for Shakhtar and Sabah home matches** (`VENUE_UNKNOWN`): no
  verified venue, so no forecast for a guessed location.
* **No weather for past matches** (`NOT_CAPTURED`): a forecast cannot be
  fetched after the fact; post-match actuals from the archive API are backlog 2.7.
* **The forecast is for the hour containing the kick-off** (18:45 → 18:00 UTC),
  not an average over the match.
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
│   ├── ingestion/            # API client + which endpoints and why
│   ├── database/             # connections, idempotent raw loader, run log
│   ├── transformation/       # ordered SQL execution in one transaction
│   ├── orchestration/        # Dagster assets, schedule, retry policy
│   └── quality/              # the eighteen data-quality checks
│
├── sql/
│   ├── schema/               # DDL (applied by `make init`)
│   ├── transform/            # raw → staging → curated
│   └── verify/               # verification queries
│
├── app/                      # viewer over the curated tables (page + HTML components)
├── notebooks/                # exploration
├── tests/                    # 96 tests: unit, contract, integration
├── data/sample/              # committed API payloads (fixtures + offline source)
└── docs/
    ├── use-case.md · data-sources.md · data-model.md
    ├── rubric-checklist.md · project-backlog.md
    ├── architecture/ · adr/ · evidence/
```

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
