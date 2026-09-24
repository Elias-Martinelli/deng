# Initial pitch - Champions League Match Intelligence

One `##` heading per slide. Speaker notes in German:
[`speaker-notes.md`](speaker-notes.md).

---

## 1 - Champions League Match Intelligence

**A data pipeline that records, every day, what was known about a match -
so a model can later predict who wins.**

HSLU · DENG Data Engineering · HS26
Elias Martinelli · Noah Rodriguez
Repository: `github.com/Elias-Martinelli/deng`

---

## 2 - The question

> Who wins the match on matchday X - and can we answer that fairly?

A model that predicts a match must only use what was known **before kick-off**.
That is hard, because the sources only ever answer with **today's** state:

* the fixture list exists months ahead, kick-off times still move;
* form and the table change after every matchday;
* a weather forecast exists at most 16 days ahead and is overwritten;
* bookmaker odds move by the minute.

What was known last week is gone unless somebody stores it. **That storing is
the project.** The model is what the data is for, not part of this project.

---

## 3 - End user and data product

**Primary user: a data scientist** who wants to train and test a match-outcome
model and needs data they can trust.

| What they get | One row is | Why it matters |
|---|---|---|
| `fact_match` | one match | the label: home win / draw / away win |
| `fact_team_match_form` | one team in one match | form from matches finished **before** that kick-off |
| `fact_match_weather` | one match | the forecast for the kick-off hour, fetched **before** kick-off |
| `fact_bookmaker_odds` | one match, bookmaker, snapshot | what the market thought, as a benchmark |
| `fact_match_snapshot` *(planned)* | one match on one day | the training table: everything known that day |

Secondary: an analysis dashboard on the same tables, so a human can see what the
model would see.

---

## 4 - Data sources

| Source | What we take | Access | Cost control |
|---|---|---|---|
| **football-data.org** v4 | fixtures, results, teams, standings, club crests | free tier, API key | 10 requests/minute; 4 requests a day |
| **Open-Meteo** | hourly forecast for the kick-off hour | free, no key | one request per stadium, only for matches ≤ 16 days away |
| **The Odds API** v4 | 1X2 odds of ~25 EU bookmakers | free plan, API key | 500 credits a month; the pipeline decides per tick whether to spend one |
| **OpenStreetMap** (Nominatim) | stadium coordinates | free, fair-use | once per season, 1 request/second |

All four are documented, free and reachable without scraping. Details and the
rejected alternatives: [`docs/data-sources.md`](../data-sources.md).

---

## 5 - What the data looks like (measured, not assumed)

* **Volume is small, history is deep.** The current league phase has 144
  matches; the 2025/26 season has 189 including the knockout rounds; the API
  lists **47 seasons**. One season is one request of ~212 KB.
* **Formats differ:** football data is nested JSON per competition, weather is
  columnar arrays per coordinate, odds are one document per bookmaker snapshot.
* **The format changed in 2024/25:** group stage → single league phase. Older
  seasons are still usable, but a model has to know which is which.
* **Availability differs per attribute:** fixtures months ahead, standings after
  matchday 1, weather ≤ 16 days, odds days before, the result minutes after.

---

## 6 - Risks and challenges we already measured

| Finding | Consequence for the design |
|---|---|
| `?status=SCHEDULED` returns rows stored as `TIMED` | upcoming matches are selected by kick-off time, never by the status text |
| the API's own aggregates do not add up, `standings.form` is null | every form figure is computed by us from single matches |
| `group` is null since the 2024/25 format change | no group dimension is modelled |
| 11 of 36 clubs have no domestic league in the free tier | scope decision: Champions League matches only, so form is comparable |
| the free tiers are metered (10/min, 500 credits/month) | pacing, retry rules and a credit budget are part of the pipeline |
| forecasts and odds are overwritten at the source | every answer is stored with the day it was fetched - our archive is the only history |

The biggest risk is not technical: **data leakage**. A model that sees the match
it predicts looks brilliant and is worthless.

---

## 7 - Ingestion and storage strategy

**Ingest everything first, transform afterwards.**

1. **Ingest** - ask every source, store the answer **unchanged** as JSON in the
   `raw` schema, with who answered, to which question, on which day.
   *One row per (source, endpoint, parameters, day)* - running the same day
   twice overwrites that row instead of adding a copy, so a rerun is safe.
2. **Transform** - only SQL, from `raw` to typed `staging` tables to `curated`
   facts and dimensions, all in one transaction.
3. **Serve** - the curated tables are the data product.

| Source | Strategy | Why |
|---|---|---|
| football fixtures/results/teams/standings | full reload per day | small payload, self-healing, one request |
| past seasons | once per season, one request each | the training data; they never change |
| weather | per stadium, only inside the 16-day horizon | a forecast beyond it does not exist |
| odds | on a budget, more often close to kick-off | 500 credits a month |
| stadium coordinates | once per season | they do not move |

Storage: **PostgreSQL** locally (four schemas: `raw`, `staging`, `curated`,
`meta`), Google Cloud Storage + BigQuery in the final milestone.

---

## 8 - Architecture v0.1 - the three stages

![Overview](../architecture-overview.svg)

Three stages, and each one is a folder in the repository:

* **Ingest** - one small Python module per source, all with the same shape;
* **Transform** - numbered SQL files, run in order inside one transaction;
* **Data product** - curated tables, read by the dashboard and later by a model.

The run log records every run with its outcome, so "did yesterday work?" is a
query, not a search through logs.

---

## 9 - What runs today

![Detail](../architecture-detail.svg)

Local Docker Compose: PostgreSQL, the orchestrator (Dagster, daily at 06:00,
with reruns and backfills) and the dashboard. Everything in this picture exists
in the repository and can be run with `make up && make run-samples`.

---

## 10 - Where it goes, and who does what

![Target](../architecture-target.svg)

**Final milestone:** the same code writes the raw zone to Google Cloud Storage
and the curated tables to BigQuery, with Terraform provisioning both. The local
path stays for development.

| Area | Owner | Reviewer |
|---|---|---|
| Football ingestion, raw model | Elias | Noah |
| Weather, stadium reference data | Noah | Elias |
| Transformations, data model | Noah | Elias |
| Orchestration, Docker, CI | Elias | Noah |
| Odds, forecast baseline | Elias | Noah |
| Dashboard, notebook | Noah | Elias |
| Cloud (Terraform, GCS, BigQuery) | shared | - |

Milestones: midterm 22 Oct (local pipeline), final 10 Dec (cloud pipeline).
Plan: [`docs/project-backlog.md`](../project-backlog.md).
