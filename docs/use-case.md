# Use Case

## Project title

**Champions League Match Intelligence Data Platform**

A reproducible batch data pipeline that collects UEFA Champions League fixtures,
results, standings and weather every day and assembles them into a curated,
point-in-time-correct dataset - the foundation on which a model can later
predict who wins a match.

## Goal in one sentence

Build the **data pipeline**, not the model: every day, record what was known
about every Champions League match *on that day*, so that a prediction model
can later be trained and tested without seeing information from the future.

The model itself ("who wins on matchday X?") is the downstream use of the data,
not a deliverable of this project. The Streamlit viewer is a preview of the
data, not the product.

## Problem statement

Information about a Champions League match is scattered and changes daily: the
fixture list is published months ahead, kick-off times move, standings and team
form change after every matchday, and weather forecasts only exist in the last
two weeks before kick-off. The source APIs always answer with **today's** state
- what was known last week is gone unless someone stored it.

Whoever wants to train a match-outcome model therefore has two problems: the
data has to be integrated from several sources on common keys, and every
feature must be reconstructable *as it was before kick-off*. A model trained on
form or weather that already includes the match it predicts looks excellent in
testing and fails in reality (data leakage).

## End user

* **Primary: a data scientist or analyst** who wants to build and evaluate a
  match-outcome model (HOME_WIN / DRAW / AWAY_WIN). They need a clean,
  documented, leakage-free table - one row per match, features known before
  kick-off, the result as label - and they need to trust how it was produced.
* **Secondary: football-interested users** who look at an upcoming fixture in
  the Streamlit viewer. It shows what the pipeline holds (form, weather state,
  data freshness, quality results); it adds no data of its own.

## Data product

| Table | One row represents | Role for the model | Status |
|---|---|---|---|
| `curated.fact_match` | one Champions League match | label: `outcome`, derived from the goals | implemented |
| `curated.fact_team_match_form` | one team going into one match | features: form over the last ≤ 5 matches finished *before* kick-off, rest days | implemented |
| `curated.fact_match_weather` | one match | features: forecast for the kick-off hour, fetched *before* kick-off, or the reason it is missing | implemented |
| `curated.dim_team`, `curated.dim_venue` | one team / one home venue | descriptive attributes, coordinates | implemented |
| `staging.standings` | one team's table position on one day | features: league position as it was on a given day | implemented (history kept) |
| `curated.fact_match_snapshot` | **one upcoming match on one pipeline run date** | **the training table**: everything known about the match on that day, with an availability state per attribute group | planned |

Details, grains and keys: [`docs/data-model.md`](data-model.md).

## Analytical use case

1. **Model development** - train a baseline HOME/DRAW/AWAY classifier on
   features taken *N days before kick-off* and evaluate it with a time-based
   split (train on earlier matchdays, test on later ones). The pipeline makes
   this possible by construction: every feature row only contains what was
   known at that point.
2. **Availability analysis** - how many days before kick-off does a usable
   weather forecast exist? How often does a kick-off time change after
   publication? The daily snapshots answer this directly.
3. **Data preview** - inspect a fixture in the Streamlit viewer: the features
   the model would see, their window sizes and states, the freshness of the
   data and the latest quality-check results.

## Project question

> How do we collect football and weather data every day in a reproducible way
> and assemble it so that a match-outcome model can be trained on exactly what
> was known before each kick-off?

## Why is this a data-engineering problem?

* **Heterogeneous sources** with different formats, keys and update cadences
  (football API: nested JSON per competition; weather API: hourly time series
  per coordinate; venues: a reference file) must be integrated on common keys
  (`match_id`, `team_id`, kick-off hour + venue coordinates).
* **Time matters twice:** data is ingested on a daily schedule *and* the moment
  of ingestion is recorded, because the same match yields different information
  on different days. Leakage prevention is a property of the pipeline, not of
  the model.
* **Raw data must be kept.** The APIs only ever return today's state - a
  forecast is overwritten, a kick-off time changes in place. The history of what
  was known when exists only if we store every answer (raw zone, one row per
  source, endpoint and day). It is also the basis for backfills and for
  rebuilding staging and curated after a bug.
* **Idempotency and reruns** are non-trivial: fixtures get rescheduled, scores
  get corrected, forecasts change. Loads upsert on business keys, and a rerun
  of an older day must not overwrite newer data.

## Expected output (per milestone)

| Milestone | Output |
|-----------|--------|
| Milestone 1 (Week 3) | Use case, data-source analysis, Architecture v0.1, backlog, project skeleton |
| Midterm (22 Oct 2026) | Local Docker Compose stack: Dagster-orchestrated daily ingestion of fixtures, standings, teams and weather into PostgreSQL (`raw` → `staging` → `curated`), point-in-time form and weather, data-quality checks, verification queries, reruns and backfills demonstrated |
| Final (10 Dec 2026) | Cloud pipeline: ingestion to a GCS raw zone, transformation to partitioned/clustered BigQuery tables incl. `fact_match_snapshot` as the training table, Terraform-provisioned infrastructure, data-quality checks, final architecture and evolution |

## Limitations (known up front)

* **Training volume:** one league phase has 144 matches - too few to train a
  model on. Past seasons *are* served by the API (2023/24 fetched in full, 47
  seasons listed), so loading several seasons is the lever (backlog 1.9). The
  competition format changed in 2024/25 (groups → single league phase), which a
  model has to account for.
* **Champions League only:** form, rest days and results use Champions League
  matches for every club ([ADR-004](adr/ADR-004-champions-league-scope.md)) -
  the free tier covers the domestic league of only 25 of 36 clubs, and two
  definitions of form in one column would not be comparable. Form features
  carry the number of matches behind them.
* **The API's own aggregates are unreliable** (`resultSet.wins/draws/losses` do
  not sum to the match count; `standings.form` is null), so all form figures are
  computed from individual match rows.
* **No line-ups, injuries or match statistics** on the free tier - features a
  strong model would want. The snapshot table will record them as
  `NOT_AVAILABLE` rather than pretend they are missing at random.
* **Weather forecasts** exist only ~16 days ahead; earlier states are
  `NOT_YET_AVAILABLE`, never an invented value. Forecasts cannot be fetched
  after the fact, so matches played before the pipeline ran have none.
* **Venue coordinates** are not delivered by the football API; they come from
  `data/reference/venues.csv`, built from OpenStreetMap and reviewed, which must
  be updated when new clubs qualify.
* **Rate limits** (10 requests/minute) keep the daily batch small by design:
  4 football requests plus at most ~18 weather requests (one per venue with a
  match in the next 16 days).
