# ADR-003 – Raw data storage strategy

Status: **PROPOSED** (2026-09-18). Becomes ACCEPTED with the first raw load into
PostgreSQL.

## Context

The football API's free tier serves the current season only and overwrites
fixture attributes (kick-off time, status, score) in place. Weather forecasts
change daily. If we only kept the latest transformed state, we could neither
rebuild tables after a bug, nor analyse what was known when, nor backfill. The
rubric asks for raw and processed data to be stored appropriately locally and in
the cloud.

## Decision

Store **every API response unchanged**, together with ingestion metadata, in an
append-only raw zone, and derive all other tables from it.

| Environment | Raw zone | Layout |
|---|---|---|
| Local (midterm) | PostgreSQL schema `raw`, one table per endpoint family, payload as `JSONB` | columns: `raw_id`, `run_id`, `ingestion_date`, `ingested_at`, `source`, `endpoint`, `request_params JSONB`, `payload JSONB`, `payload_hash` |
| Cloud (final) | Google Cloud Storage bucket | `raw/source=<src>/endpoint=<ep>/ingestion_date=YYYY-MM-DD/<run_id>.json` (Hive-style partitions readable by BigQuery external tables) |

Deduplication: a `UNIQUE (source, endpoint, request_params, ingestion_date)`
constraint locally; in GCS the object name is deterministic per run and
partition, so a rerun overwrites the same object instead of creating a new one.

## Alternatives considered

| Alternative | Why not |
|---|---|
| Transform on the fly, store only typed tables | no reprocessing, no audit trail, no backfill once the API stops serving the data |
| Raw JSON files on the local disk (midterm) | works, but a second storage system to document and a Compose volume to manage; Postgres JSONB gives SQL access to raw data for debugging and keeps the midterm stack to one database |
| Flatten raw into many columns | brittle under schema drift – a new nested field would break the load; JSONB tolerates additive changes |
| Parquet in GCS | more compact and columnar, but requires a conversion step in the ingestion path; raw JSON stays closest to the source; Parquet is a good *staging* format later if volume grows |

## Advantages

* Full reproducibility: staging and curated tables can be truncated and rebuilt.
* Schema drift is detected in transformation, not during ingestion; ingestion
  keeps succeeding.
* Point-in-time analyses ("what did the API say on 1 Oct?") are possible.
* Identical mental model locally and in the cloud (partition by ingestion date).

## Disadvantages

* Storage grows linearly with days × endpoints (≈ 2 MB/day → < 1 GB per season;
  acceptable).
* Querying JSONB is slower than typed columns → never serve analytics from raw.
* Reruns for the same date must be made idempotent explicitly (hash/unique key).

## Consequences

* Ingestion code is deliberately "dumb": fetch, validate minimal structure,
  store. All business logic lives in SQL transformations that read from raw.
* Backfill semantics: for past dates we replay *transformations* from stored raw
  payloads; re-fetching is only meaningful for data the API still serves
  (current-season fixtures and results).
* At 100× volume the layout still works; we would switch the staging layer to
  Parquet and load BigQuery from it instead of JSON external tables.
