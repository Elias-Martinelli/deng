# Use Case

## Project title

**Champions League Match Intelligence Data Platform**

A reproducible batch data pipeline that integrates fixture, result, standings and
weather data for the UEFA Champions League into a curated, point-in-time-correct
pre-match dataset.

## Problem statement

Information about an upcoming Champions League match is scattered across several
sources and changes daily: the fixture list is published months ahead, standings
and team form change after every matchday, weather forecasts only become
meaningful in the last two weeks before kick-off, and line-ups appear an hour
before the game. Anyone who wants a consistent pre-match overview – or wants to
build a prediction model on top of it – has to stitch these sources together,
re-query them repeatedly and take care not to mix in information that was not
yet known at the time.

## End user

* **Primary:** football analysts and football-interested users who want a
  structured, trustworthy pre-match overview for upcoming Champions League
  fixtures (e.g. "FC Barcelona vs Arsenal FC, 22 Oct 2026, 21:00 CEST").
* **Secondary:** data scientists who need a *leakage-free* feature table to
  train and evaluate match-outcome models.

## Data product

A curated dataset with three layers:

| Layer | Content | Refresh |
|-------|---------|---------|
| `fact_match` | one row per Champions League match: teams, kick-off (UTC), stage, matchday, venue, status, final score | daily |
| `fact_team_match_form` | one row per team per match: rolling form of the *last 5 completed matches before that match* (wins/draws/losses, goals for/against, home/away form, days since last match) | daily |
| `fact_match_snapshot` | one row per upcoming match per pipeline run date: everything known about the match **on that day** – form, standings, weather forecast (or `NOT_YET_AVAILABLE`), data-freshness flags | daily until kick-off |

Plus dimensions `dim_team`, `dim_venue` (with coordinates), `dim_date`.

## Analytical use case

The curated tables answer questions such as:

1. *Pre-match overview* – "What do we know about match X today?" (form,
   standings, head-to-head, weather).
2. *Availability analysis* – "How many days before kick-off does a reliable
   weather forecast become available? How often does a fixture's kick-off time
   or venue change after publication?"
3. *Model development* – train a baseline HOME/DRAW/AWAY classifier on
   `fact_match_snapshot` rows taken *N days before kick-off*, which guarantees
   that only information available at that point in time is used
   (data-leakage prevention by construction).

The optional Streamlit app is a thin viewer on top of layer 1–3; it never calls
external APIs itself.

## Project question

> How can heterogeneous football and contextual data be integrated through a
> reproducible, availability-aware batch pipeline to provide a curated,
> point-in-time-correct pre-match dataset for upcoming Champions League matches?

## Why is this a data-engineering problem?

* **Heterogeneous sources** with different formats, keys and update cadences
  (football API: nested JSON, per competition; weather API: time series per
  coordinate) must be integrated on a common key (`match_id`, `team_id`, kick-off
  date + venue coordinates).
* **Time matters twice:** data must be ingested in batches on a schedule *and*
  the moment of ingestion must be recorded, because the same fixture yields
  different information on different days. That is exactly what the snapshot
  table captures.
* **Raw data must be kept** because the football API's free tier only exposes
  the current season – our raw zone becomes the only archive we own and the
  basis for backfills and re-processing.
* **Idempotency and reruns** are non-trivial: fixtures get rescheduled, scores
  get corrected, forecasts are overwritten. Loads must upsert on business keys
  and snapshots must be keyed by run date.
* **Data quality is real:** kick-off times can be `TBD`, venues can be missing
  for neutral finals, teams from leagues outside the API's free tier have no
  domestic form data, and forecasts beyond 16 days do not exist.

## Expected output (per milestone)

| Milestone | Output |
|-----------|--------|
| Milestone 1 (Week 3) | Use case, data-source analysis, Architecture v0.1, backlog, project skeleton |
| Midterm (22 Oct 2026) | Local Docker Compose stack: orchestrated daily batch ingestion of fixtures, standings, teams and weather into PostgreSQL (`raw` → `staging` → `curated`), at least `fact_match` and `fact_team_match_form`, verification queries, reruns and backfills demonstrated |
| Final (10 Dec 2026) | Cloud pipeline: ingestion to a GCS raw zone, transformation to partitioned/clustered BigQuery tables incl. `fact_match_snapshot`, Terraform-provisioned infrastructure, data-quality checks, final architecture and evolution |

## Limitations (known up front)

* **Historical depth:** football-data.org's free tier exposes the current season
  only. Team form is therefore built from the *current* season (Champions League
  plus domestic matches for clubs from the 11 other free-tier competitions).
  Multi-season history accumulates only from the day our ingestion starts.
* **No line-ups, injuries or match statistics** on the free tier. The snapshot
  table records these as `NOT_AVAILABLE`; the schema leaves room for them if a
  paid tier or another source is added later.
* **Weather forecasts** exist only ~16 days ahead; earlier snapshots carry
  `NOT_YET_AVAILABLE` instead of an invented value.
* **Venue coordinates** are not delivered by the football API; they come from a
  small, versioned reference file (`data/reference/venues.csv`) that must be
  maintained when new clubs qualify.
* **Rate limits** (10 requests/minute) make the daily batch small by design –
  roughly 40–60 API calls per day – which is sufficient for the use case but
  rules out player-level data.
