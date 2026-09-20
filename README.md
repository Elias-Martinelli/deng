# Champions League Match Intelligence Data Platform

HSLU · DENG – Data Engineering · HS26 · End-to-End Batch Data Pipeline

[![CI](https://github.com/Elias-Martinelli/deng/actions/workflows/ci.yml/badge.svg)](https://github.com/Elias-Martinelli/deng/actions/workflows/ci.yml)

> **Project status: Milestone 1 (initial pitch) – foundation.** The repository
> contains the use case, data-source analysis, Architecture v0.1, decision
> records, backlog and a tested Python skeleton (API client + configuration).
> Ingestion into PostgreSQL, Docker Compose and orchestration follow for the
> midterm. See [Project Status](#project-status).

## Project Overview

A reproducible **daily batch pipeline** that ingests UEFA Champions League
fixtures, results, standings and team data from [football-data.org](https://www.football-data.org)
and weather forecasts from [Open-Meteo](https://open-meteo.com), stores the raw
payloads unchanged, and transforms them into curated, point-in-time-correct
tables that describe **what is known about an upcoming match on a given day**.

```text
football-data.org ─┐                       ┌─ Analytics / ML (leakage-free features)
Open-Meteo ────────┼─► batch ingestion ─► RAW ─► STAGING ─► CURATED ─┤
venues.csv ────────┘   (daily, orchestrated)                         └─ Streamlit viewer (optional)
```

Local (midterm): PostgreSQL in Docker Compose. Final: Google Cloud Storage raw
zone + BigQuery, provisioned with Terraform. Full detail in
[`docs/architecture/architecture-v0.1.md`](docs/architecture/architecture-v0.1.md).

## Problem Statement

Pre-match information is scattered over several sources with different update
cadences (fixtures months ahead, standings after each matchday, weather only
~16 days ahead, line-ups an hour before). Assembling a consistent overview – or a
training set that does not leak future information – requires integrating these
sources repeatedly and recording *when* each piece of information became
available. Details: [`docs/use-case.md`](docs/use-case.md).

## End User

Football analysts and football-interested users who want a structured pre-match
overview for an upcoming Champions League fixture; secondarily data scientists
who need a leakage-free feature table.

## Data Product

| Table | Grain (one row = …) | Purpose |
|---|---|---|
| `fact_match` | one Champions League match | fixture, venue, status, score |
| `fact_team_match_form` | one team in one match | rolling form of the last 5 completed matches *before* that match |
| `fact_match_snapshot` | one upcoming match on one pipeline run date | everything known that day incl. weather forecast and explicit availability states |
| `dim_team`, `dim_venue`, `dim_date` | one team / venue / calendar day | descriptive attributes, coordinates, time zone |

## Use Case

Select an upcoming fixture (e.g. *FC Barcelona vs Arsenal FC, 22 Oct 2026*) and
obtain fixture details, venue, weather forecast, recent form, standings and
head-to-head – all served from our curated tables, never from live API calls.
Secondary: analyse how many days before kick-off each attribute group becomes
available, and train a baseline outcome model on snapshot features.

## Data Sources

| Source | Content | Access | Limits (free) |
|---|---|---|---|
| football-data.org v4 | CL fixtures, results, standings, teams, referees, head-to-head | REST/JSON, `X-Auth-Token`, free registration | 10 requests/min; no line-ups/injuries/statistics; 11 of 36 clubs without domestic-league data |
| Open-Meteo | 16-day forecast, historical archive | REST/JSON, no key | 10 000 calls/day; CC BY 4.0 |
| `data/reference/venues.csv` (planned) | stadium coordinates and time zones | versioned in repo | maintained manually |

Full evaluation incl. rejected alternatives: [`docs/data-sources.md`](docs/data-sources.md),
decision: [ADR-001](docs/adr/ADR-001-football-data-source.md) (ACCEPTED), measured
findings from the live API: [`docs/evidence/api-exploration.md`](docs/evidence/api-exploration.md).

## Data Characteristics

* Volume (measured 20 Sep 2026): 144 league-phase matches, 36 teams, 1 standings
  table; knockout fixtures are added after the December draw. ≈ 60 API calls and
  < 2 MB raw per daily run; < 1 GB raw per season. All 47 listed seasons together
  are roughly 5 000–6 500 matches.
* Format: nested JSON (football), columnar JSON time series (weather).
* Keys: `match.id`, `team.id` (stable integers from football-data.org);
  weather keyed by `(match_id, forecast_date)`.
* Change behaviour: fixtures change kick-off time/status in place, and **new
  fixtures appear mid-season** (knockout draw in December); scores are appended
  once; forecasts are overwritten daily → raw payloads are kept per ingestion
  date, and `lastUpdated` is a candidate incremental watermark.

## Data Quality Risks

Kick-off times `TBD` early in the season, postponed/rescheduled matches, neutral
final venue, score corrections, teams without domestic-league data on the free
tier, forecasts unavailable > 16 days ahead, missing venue coordinates for newly
qualified clubs. Handling strategy: [`docs/data-sources.md` §5](docs/data-sources.md#5-availability-aware-ingestion--when-is-which-information-known).

## Architecture

* [Architecture v0.1](docs/architecture/architecture-v0.1.md) – conceptual,
  local/midterm and cloud/final views with Mermaid diagrams.
* [Architecture Decision Records](docs/adr/README.md) – data sources,
  orchestrator, raw storage.

## Batch Ingestion Strategy

One scheduled run per day (data changes a few times per day at most; forecast
models update every 1–6 h). Each run: extract → validate → store raw (immutable,
per ingestion date) → transform → data-quality checks → snapshot append.
Full vs. incremental per endpoint is decided in the midterm sprint based on the
real payloads (`docs/rubric-checklist.md`, backlog 2.9).

## Local Development

```bash
git clone https://github.com/Elias-Martinelli/deng.git
cd deng
make setup                     # venv + editable install + copies .env.example to .env
source .venv/bin/activate
# edit .env → FOOTBALL_DATA_API_KEY (free key: https://www.football-data.org/client/register)
make test                      # unit tests, no network required
make lint
make explore                   # fetch small real samples into data/sample/ (needs the key)
```

Requirements: Python ≥ 3.11, `make`. Docker is required from the midterm on.

## PostgreSQL

Planned schemas: `raw` (JSONB payloads + ingestion metadata), `staging` (typed,
flattened), `curated` (facts and dimensions), `meta` (pipeline runs,
data-quality results). DDL will live in `sql/`. *(midterm)*

## Docker

`docker compose up -d` will start PostgreSQL, the orchestrator and the pipeline
image on one network with health checks and a named volume. *(midterm)*

## Workflow Orchestration

Candidate: Dagster (daily partitions ⇒ backfills and reruns per ingestion date).
Evaluation and decision: [ADR-002](docs/adr/ADR-002-workflow-orchestrator.md). *(midterm)*

## Transformation

SQL transformations from `raw` → `staging` → `curated`, executed by the
orchestrator. First justified transformations: `fact_match` and
`fact_team_match_form` (rolling last-5 form computed only from matches finished
*before* the match in question). *(midterm)*

## Google Cloud Architecture

Ingestion writes raw JSON directly to a GCS bucket
(`raw/source=…/endpoint=…/ingestion_date=…/run_id.json`); BigQuery loads staging
tables from GCS and builds curated tables with `MERGE`. *(final)*

## Terraform

Provisions the GCS bucket, the BigQuery dataset, a service account and IAM
bindings. *(final)*

## Google Cloud Storage

Raw data lake, Hive-style partitioned by source, endpoint and ingestion date. *(final)*

## BigQuery

Curated tables partitioned by `match_date` / `snapshot_date` and clustered by
team/match ids – justification follows the expected query patterns
("matches of team X in period Y", "snapshot of match Z N days before"). *(final)*

## Data Model

Grains are listed under [Data Product](#data-product); a dedicated ADR with
facts, dimensions and keys follows once the real schema is known.

## Data Quality

SQL checks after each stage (not null, unique business keys, home ≠ away, valid
status, referential integrity, row counts, plausibility). Critical violations
fail the run; results are persisted. *(midterm)*

## Reproducibility

Everything a peer team needs is in this repository: `.env.example`, `Makefile`,
pinned dependencies (`pyproject.toml`), CI running lint and tests on every push.
Docker Compose and verification steps are added for the midterm and tested in a
clean environment by the other team member before submission.

## Verification

Currently: `make test` (28 tests) and `make lint`. `make verify` with
database checks follows with the midterm.

## Analytics / Machine Learning

Optional and last: availability analysis over snapshots; baseline HOME/DRAW/AWAY
classifier with a time-based split on snapshot features only.

## Streamlit Application

Optional thin viewer over the curated tables (fixture picker → match
intelligence). It never calls external APIs.

## Architecture Evolution

* v0.1 – initial pitch (this state): [`docs/architecture/architecture-v0.1.md`](docs/architecture/architecture-v0.1.md)
* v0.2 – midterm: lessons learned, changed decisions *(to be written)*
* final – complete cloud solution and evolution *(to be written)*

## Known Limitations

* For **11 of the 36** league-phase clubs the free tier carries no domestic
  league, so their form rests on Champions League matches alone. Form features
  carry the number of matches behind them.
* The API's own aggregates are inconsistent (`resultSet` win/draw/loss counts do
  not sum to the match count; `standings.form` is null) → all form figures are
  computed from individual match rows.
* The competition format changed in 2024/25 (groups → single league phase), so
  `group` is null for current seasons and populated for older ones.
* No line-ups, injuries, player or match statistics → recorded as `NOT_AVAILABLE`.
* Weather forecasts only ≤ 16 days ahead (reliable ≤ 7) → `NOT_YET_AVAILABLE`.
* Venue coordinates come from a hand-maintained reference file.
* The API is not reachable from every corporate/cloud network; run `make explore`
  from a normal internet connection.

## Project Status

| Milestone | Deadline | Status |
|---|---|---|
| Milestone 1 – initial pitch | week 3 (pitch) | **complete** – use case, verified data sources, Architecture v0.1, ADRs, backlog |
| Midterm – local pipeline | 22 Oct 2026 15:30 | not started |
| Final – cloud pipeline | 10 Dec 2026 20:00 | not started |

Rubric coverage: [`docs/rubric-checklist.md`](docs/rubric-checklist.md).

## Project Backlog

[`docs/project-backlog.md`](docs/project-backlog.md) – epics, MUST/SHOULD/COULD
priorities, milestones, timeline and division of responsibilities.

## Repository Layout

```text
.
├── README.md
├── .env.example              # configuration template – copy to .env, never commit .env
├── Makefile                  # setup · test · lint · format · explore
├── pyproject.toml            # package metadata, dependencies, ruff/pytest config
├── .github/workflows/ci.yml  # lint + tests on every push
├── src/deng/
│   ├── config.py             # validated settings from environment
│   └── ingestion/
│       └── football_data_client.py
├── scripts/
│   └── explore_football_api.py   # Phase-12 API exploration (writes data/sample/)
├── tests/
├── data/sample/              # small committed API samples (test fixtures)
└── docs/
    ├── use-case.md
    ├── data-sources.md
    ├── rubric-checklist.md
    ├── project-backlog.md
    ├── architecture/architecture-v0.1.md
    └── adr/
```

Folders for `sql/`, `orchestration/`, `terraform/` and `app/` are created when
the corresponding code arrives.

## Authors

* Elias Martinelli
* *Student B – to be added*
