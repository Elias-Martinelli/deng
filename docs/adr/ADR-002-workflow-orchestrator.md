# ADR-002 – Workflow orchestrator

Status: **ACCEPTED** (2026-09-21, after the spike below). Proposed 2026-09-18
with the condition: run the ingestion as a scheduled, partitioned job and check
that reruns and backfills work inside Docker Compose within one day.

## Context

The rubric requires an orchestrator that schedules the pipeline, models
dependencies and supports retries, reruns and backfills – locally in Docker
Compose (midterm) and against Google Cloud (final). We are two students; the
tool must be explainable in a 10-minute defence and must not dominate the
Docker footprint.

## Decision

**Dagster** (open-source, `dagster` + `dagster-webserver` + `dagster-daemon`,
PostgreSQL as Dagster storage – reusing our existing Postgres container).

## Alternatives considered

| Criterion | Dagster | Prefect 3 | Apache Airflow 3 | Kestra |
|---|---|---|---|---|
| Complexity in Docker Compose | 2 containers (webserver, daemon) + code location; Postgres reused | server + worker + Postgres | api-server, scheduler, dag-processor, triggerer, Redis/Celery or LocalExecutor; heaviest | single Java container + Postgres |
| Learning curve | medium – asset/job concepts | low – plain Python decorators | medium–high – DAG authoring plus operator zoo | low – YAML flows |
| Scheduling | cron schedules on jobs/assets | deployments with schedules | cron / timetables | cron triggers |
| Retries | per-op `RetryPolicy` (max retries, delay, back-off) | `@task(retries, retry_delay_seconds)` | per-task `retries`, exponential back-off | per-task retry blocks |
| Backfills | **first-class**: daily partitions, backfill any date range from the UI or CLI, partition status visible | manual: loop over dates / parametrised flow runs | `airflow backfill` + `catchup` | backfill via executions API |
| Dependencies | explicit op/asset graph | implicit via Python calls | explicit DAG edges | flow YAML |
| Logging / observability | structured run logs per op, asset lineage | good run logs | task logs | good UI |
| Local development | `dagster dev` single process | `prefect server start` | heavy | Java runtime |
| Cloud compatibility | runs anywhere Python runs; GCS/BigQuery resources | same | same, GCP operators | plugins |
| Explainability in a defence | assets map 1:1 to our tables; partitions map 1:1 to ingestion days | very simple, but backfill logic is "our loop" | industry standard, but a lot of moving parts | YAML instead of Python code |

## Advantages (Dagster)

* Daily **partitions** are exactly our mental model: one partition = one
  ingestion date = one raw folder = one snapshot date. Backfills and reruns are
  UI-visible, not hand-written loops.
* Asset graph doubles as data lineage (raw → staging → curated tables).
* Moderate Docker footprint; Postgres already exists.
* Same code runs locally and in the cloud; resources swap Postgres for
  GCS/BigQuery.

## Disadvantages

* Higher conceptual overhead than Prefect (assets vs. ops vs. jobs); the team
  must be able to explain the difference.
* Dagster versions move fast; pin versions in `pyproject.toml`.
* Dagster daemon must be running for schedules – one more component to health-check.

## Consequences

* If the spike shows that partitions/backfills do not behave as expected inside
  Compose within one day, fall back to **Prefect 3** with an explicit
  `backfill(start_date, end_date)` flow – documented as SUPERSEDED here.
* Orchestrator metadata lives in the `public` schema of the project database
  (see spike result), so `docker compose down -v` resets everything.

## Spike result (2026-09-21)

Every acceptance criterion was met in one session, so the Prefect fallback is
not needed. Evidence: [`docs/evidence/local-pipeline-run.md` §12](../evidence/local-pipeline-run.md#12-dagster-orchestration-21-september-2026).

| Criterion | Result |
|---|---|
| Runs inside Compose | `dagster-webserver` + `dagster-daemon`, one image (`orchestrator` stage on top of the pipeline image), both with health checks |
| Schedule | `daily_pipeline_schedule`, 06:00 Europe/Zurich, RUNNING by default; a tick on 21 Sep targets partition `2026-09-21` (unit-tested) |
| Dependencies | asset graph raw → staging → curated → dq; a failed ingest does not start the transform (tested) |
| Retries | `RetryPolicy` (3×, 60 s, exponential, jitter) for transient errors only; permanent ones raise `Failure(allow_retries=False)` (tested: no retry event) |
| Backfill | `make dagster-backfill FROM=… TO=…` → one run per day, executed one at a time |
| Rerun | re-materialising a partition leaves 4 raw rows for that date (tested) |
| No duplicated logic | assets call `deng.pipeline.command_*` / `run_checks` - the CLI remains the source of truth |

Implementation choices made during the spike, and why:

* **Assets, not ops.** One asset per table, so the UI's lineage graph is our
  data model. Staging and curated are one `multi_asset` because they run in one
  transaction; splitting them would break that guarantee.
* **Daily partitions with `end_offset=1`.** Dagster's last partition is
  yesterday by default; the 06:00 run would then store today's API state under
  yesterday's `ingestion_date`.
* **`max_concurrent_runs: 1`.** All runs write the same curated tables; parallel
  backfill runs would only wait on each other's row locks.
* **Backfilling old dates is safe.** Staging upserts only overwrite when the
  incoming `ingestion_date` is at least as new, so a backfill cannot roll the
  curated state back (measured: 504 rows written for an old date vs. 684 for
  today - the difference is exactly the 144 matches + 36 teams left untouched).
* **Dagster metadata in `public` of the same database**, not a separate
  database: a second database would need an init script, and Postgres only runs
  those on an empty volume - existing setups would break silently.
* **`INGEST_SOURCE=samples`** lets a reviewer without an API key run schedules
  and backfills; UI backfills cannot take per-run config, so an environment
  setting is the only option that works everywhere. It is explicit, never a
  fallback.

Costs observed: the orchestrator image is 501 MB (pipeline image 235 MB), and
Dagster pins had to be one minor release wide (`>=1.13,<1.14`).
