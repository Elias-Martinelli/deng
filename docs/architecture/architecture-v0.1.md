# Architecture v0.1 (Milestone 1 – initial pitch)

Status: **initial proposal, 18 Sep 2026.** Everything marked *PROPOSED* is
decided in an ADR after a technical spike; see [`docs/adr/`](../adr/README.md).
Changes and lessons learned will be recorded in `architecture-v0.2.md` (midterm)
and `architecture-final.md` (final).

## 1. Conceptual view

The GUI never talks to external APIs. Everything flows through one batch
pipeline that writes raw data first and derives curated data from it.

```mermaid
flowchart TB
    subgraph SRC["External data sources"]
        FD["football-data.org v4<br/>fixtures · results · standings · teams · head-to-head"]
        OM["Open-Meteo<br/>16-day forecast · historical archive"]
        REF["Reference file<br/>venues.csv (coordinates, time zone)"]
    end

    subgraph ING["Batch ingestion (Python, daily)"]
        EX["extract<br/>API clients · retries · rate limiting"]
        VAL["validate raw<br/>schema + required fields"]
        LD["load raw<br/>payload as-is + run metadata"]
        EX --> VAL --> LD
    end

    SRC --> EX

    subgraph STORE["Storage"]
        RAW[("RAW zone<br/>immutable API payloads<br/>partitioned by ingestion date")]
        STG[("STAGING<br/>typed, flattened tables")]
        CUR[("CURATED<br/>fact_match · fact_team_match_form<br/>fact_match_snapshot · dim_*")]
    end

    LD --> RAW
    RAW -->|"transform (SQL)"| STG -->|"transform (SQL)"| CUR

    subgraph ORCH["Workflow orchestration (PROPOSED: Dagster)"]
        SCH["daily schedule · dependencies · retries<br/>reruns · backfills by date partition"]
    end
    ORCH -.controls.-> ING
    ORCH -.controls.-> STORE

    subgraph DQ["Data quality"]
        CHK["checks after each stage<br/>not null · unique keys · referential integrity · plausibility"]
    end
    STORE -.-> DQ

    subgraph OUT["Consumers"]
        AN["Analytics / ML<br/>leakage-free features from snapshots"]
        ST["Streamlit viewer (optional)<br/>select fixture → match intelligence"]
    end
    CUR --> AN
    CUR --> ST
```

## 2. Local / midterm view (Docker Compose)

Goal of the midterm: the complete pipeline runs locally with one command,
PostgreSQL holds raw, staging and curated schemas, the orchestrator schedules
the daily batch and supports reruns and backfills.

```mermaid
flowchart LR
    subgraph EXT["Internet"]
        FD["football-data.org"]
        OM["Open-Meteo"]
    end

    subgraph DC["Docker Compose network: deng"]
        subgraph ORCH["orchestrator container(s)<br/>PROPOSED: Dagster webserver + daemon"]
            JOB["daily_batch job<br/>ingest_fixtures → ingest_standings → ingest_teams<br/>→ ingest_team_matches → ingest_weather<br/>→ transform_staging → transform_curated → dq_checks"]
        end
        subgraph PG["postgres container (PostgreSQL 16)"]
            RAW[("schema raw<br/>*_payload tables: JSONB + ingestion metadata")]
            STG[("schema staging<br/>typed tables, 1 row per entity")]
            CUR[("schema curated<br/>facts + dimensions")]
            META[("schema meta<br/>pipeline_runs, dq_results")]
        end
        VOL[["named volume<br/>pgdata"]]
        PG --- VOL
    end

    DEV["developer / peer reviewer<br/>make up · make ingest · make verify"] --> DC
    FD --> JOB
    OM --> JOB
    JOB --> RAW --> STG --> CUR
    JOB --> META
```

Key properties:

* **Raw first.** Every API response is stored unchanged (JSONB) together with
  `source`, `endpoint`, `request_params`, `ingested_at`, `run_id`. Staging and
  curated tables can always be rebuilt from raw – that is what makes backfills
  and schema fixes cheap.
* **Idempotent loads.** Staging/curated tables have business keys
  (`match_id`, `team_id`, `(match_id, team_id)`, `(match_id, snapshot_date)`)
  with unique constraints; loads are `INSERT … ON CONFLICT DO UPDATE`.
  Running the same day twice yields identical row counts.
* **Backfill = rerun for a date partition.** Each run is parameterised by a
  logical date; a backfill for `2026-10-01 … 2026-10-10` replays the
  transformation from the raw payloads of those days (raw is re-fetched only
  for data the API still serves).
* **One network, health checks, env-file configuration.** The orchestrator waits
  for PostgreSQL's health check; no credentials in images.

## 3. Final / cloud view (Google Cloud)

The production ingestion writes straight from the API to Google Cloud Storage –
no local file is a required intermediate step. Local storage remains for
development, tests and caching.

```mermaid
flowchart LR
    subgraph EXT["Internet"]
        FD["football-data.org"]
        OM["Open-Meteo"]
    end

    subgraph GCP["Google Cloud project (Terraform-provisioned)"]
        subgraph LAKE["Cloud Storage – raw data lake"]
            GCS[("gs://&lt;bucket&gt;/raw/source=football-data/endpoint=matches/ingestion_date=YYYY-MM-DD/run_id.json<br/>gs://&lt;bucket&gt;/raw/source=open-meteo/…")]
        end
        subgraph BQ["BigQuery dataset cl_intelligence"]
            BQS[("staging tables<br/>external / loaded from GCS")]
            BQC[("curated tables<br/>fact_match (partition: match_date, cluster: home_team_id, away_team_id)<br/>fact_team_match_form (partition: match_date, cluster: team_id)<br/>fact_match_snapshot (partition: snapshot_date, cluster: match_id)<br/>dim_team · dim_venue · dim_date")]
        end
        DQ["data-quality checks<br/>(SQL, fail the run)"]
    end

    subgraph RUN["Pipeline runtime"]
        ORCH["orchestrator (same code as local)<br/>schedule · retries · backfills"]
    end

    FD --> ORCH
    OM --> ORCH
    ORCH -->|"write raw JSON directly"| GCS
    GCS -->|"load / external tables"| BQS -->|"SQL transformations (MERGE)"| BQC
    BQC --> DQ

    subgraph OUT["Consumers"]
        AN["Analytics / ML notebooks"]
        ST["Streamlit (optional)"]
    end
    BQC --> AN
    BQC --> ST

    TF["Terraform<br/>bucket · dataset · service account · IAM"] -.provisions.-> GCP
```

*Where the orchestrator runs in the cloud (Cloud Run job vs. a VM vs. local
Docker with cloud credentials) is deliberately open – see the backlog. The
rubric requires infrastructure for storage and warehouse via Terraform; compute
placement is a secondary decision to be made after the midterm.*

## 4. Data flow per daily run (both environments)

```mermaid
sequenceDiagram
    autonumber
    participant O as Orchestrator (daily 06:00 Europe/Zurich)
    participant F as football-data.org
    participant W as Open-Meteo
    participant R as RAW (Postgres JSONB / GCS)
    participant C as STAGING + CURATED (Postgres / BigQuery)

    O->>F: GET competitions/CL/matches, /standings, /teams
    F-->>O: JSON (≤ 10 req/min, retry on 429/5xx)
    O->>R: store payloads + run metadata (idempotent per run_id)
    O->>F: GET teams/{id}/matches (36×)
    F-->>O: JSON
    O->>R: store payloads
    O->>R: read upcoming matches ≤ 16 days ahead + venue coordinates
    O->>W: GET forecast (lat, lon, kickoff date)
    W-->>O: JSON or nothing (outside horizon → NOT_YET_AVAILABLE)
    O->>R: store payloads
    O->>C: transform raw → staging → curated (UPSERT / MERGE)
    O->>C: append fact_match_snapshot rows for snapshot_date = run date
    O->>C: run data-quality checks → fail run on critical violations
```

## 5. Milestone-1 decisions and open points

| Topic | Decision | Status |
|---|---|---|
| Football source | football-data.org free tier | PROPOSED → [ADR-001](../adr/ADR-001-football-data-source.md) |
| Weather source | Open-Meteo | PROPOSED → [ADR-001](../adr/ADR-001-football-data-source.md) |
| Raw storage | keep unchanged payloads; JSONB locally, JSON objects on GCS | PROPOSED → [ADR-003](../adr/ADR-003-raw-data-storage.md) |
| Orchestrator | Dagster favoured (partitions = backfills), spike before midterm sprint | PROPOSED → [ADR-002](../adr/ADR-002-workflow-orchestrator.md) |
| Transformation tool | SQL files executed by the orchestrator (no dbt for now) | open – evaluated with ADR-002 spike |
| Batch frequency | once per day (data changes at most a few times per day; forecast models update 1–6 h) | PROPOSED |
| Snapshot table | included from the midterm on – one extra append step per run | PROPOSED |
| Cloud compute | open (Cloud Run job vs. local runner with cloud credentials) | open |

## 6. Division of responsibilities (proposal)

Both students must be able to explain the whole architecture. Ownership below
means "drives the implementation and writes the docs", not "only person who
understands it". Every pull request is reviewed by the other student.

| Area | Owner | Reviewer |
|---|---|---|
| Football ingestion, API client, raw model | Elias Martinelli | Noah Rodriguez |
| Weather ingestion, venue reference data | Noah Rodriguez | Elias Martinelli |
| PostgreSQL schemas, SQL transformations, data quality | Noah Rodriguez | Elias Martinelli |
| Orchestration, Docker Compose, Makefile, CI | Elias Martinelli | Noah Rodriguez |
| Terraform, GCS, BigQuery model, partitioning | shared – pair session, then split by table | – |
| Documentation, architecture evolution, evidence | shared – each documents what they built | – |
| Peer reviews of other teams | both, independently, then merged | – |
