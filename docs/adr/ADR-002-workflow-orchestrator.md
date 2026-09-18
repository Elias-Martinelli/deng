# ADR-002 – Workflow orchestrator

Status: **PROPOSED** (2026-09-18). Decision after a one-day spike at the start
of the midterm sprint: run the fixture ingestion as a scheduled, partitioned job
in the candidate and check that reruns and backfills work inside Docker Compose.

## Context

The rubric requires an orchestrator that schedules the pipeline, models
dependencies and supports retries, reruns and backfills – locally in Docker
Compose (midterm) and against Google Cloud (final). We are two students; the
tool must be explainable in a 10-minute defence and must not dominate the
Docker footprint.

## Decision (proposed)

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
* Orchestrator metadata lives in a separate `dagster` schema/database inside the
  same Postgres container, so `docker compose down -v` resets everything.
