# Project Backlog and Plan

Priority: **MUST** (rubric requirement), **SHOULD** (clearly raises quality or
defensibility), **COULD** (only after all MUSTs of the milestone are done).
Milestone: **M1** (initial pitch, week 3), **MIDTERM** (repo deadline
22 Oct 2026 15:30), **FINAL** (repo deadline 10 Dec 2026 20:00).
Status: `[ ]` open · `[~]` in progress · `[x]` done with evidence.

## Timeline

| Week | Dates (2026) | Goal |
|---|---|---|
| 2 | 21–25 Sep | M1 foundation (this repo state), API exploration with real key, venues reference file |
| 3 | 28 Sep – 2 Oct | **Initial pitch (10 min)**; ingestion of fixtures/teams/standings into Postgres raw |
| 4 | 5–9 Oct | orchestrator spike + decision (ADR-002), Docker Compose stack, staging + curated `fact_match` |
| 5 | 12–16 Oct | weather ingestion, `fact_team_match_form`, data-quality checks, backfill + idempotency tests, evidence |
| 6 | 19–22 Oct | **freeze Tue 20 Oct**, clean-environment test by the other student, Architecture v0.2, README; **submit Thu 22 Oct 15:30** |
| 7 | 26–30 Oct | midterm defence; start peer reviews (due 12 Nov) |
| 8–9 | 2–13 Nov | Terraform (bucket, dataset, IAM), GCS raw writer, cloud ingestion path |
| 10–11 | 16–27 Nov | BigQuery staging + curated model, partitioning/clustering, `fact_match_snapshot`, cloud DQ |
| 12 | 30 Nov – 4 Dec | safe reruns in the cloud, verification queries, evidence, final architecture + evolution, optional Streamlit/ML |
| 13 | 7–10 Dec | **freeze Mon 7 Dec**, clean-environment test, docs; **submit Thu 10 Dec 20:00** |
| 14 | 14–18 Dec | final defence; peer reviews due 31 Dec |

Buffer rule: each milestone has two full days between feature freeze and
submission reserved for the clean-environment test, bug fixes and documentation.

## EPIC 1 – Data sources

| # | Task | Prio | Milestone | Status |
|---|---|---|---|---|
| 1.1 | Evaluate football and weather APIs, document per-source facts | MUST | M1 | [x] `docs/data-sources.md` |
| 1.2 | Availability timeline per attribute group | MUST | M1 | [x] `docs/data-sources.md` §5 |
| 1.3 | Register free key, run `scripts/explore_football_api.py`, commit small samples to `data/sample/` | MUST | M1 | [ ] |
| 1.4 | Document schema, business keys, null behaviour from real payloads (`docs/evidence/api-exploration.md`) | MUST | M1 | [ ] |
| 1.5 | Confirm/refute "current season only" and head2head behaviour; set ADR-001 to ACCEPTED | MUST | M1 | [ ] |
| 1.6 | Create `data/reference/venues.csv` for the 36 league-phase clubs (lat, lon, tz) | MUST | MIDTERM | [ ] |
| 1.7 | ClubElo as cross-season strength signal | COULD | FINAL | [ ] |

## EPIC 2 – Local batch ingestion

| # | Task | Prio | Milestone | Status |
|---|---|---|---|---|
| 2.1 | API client with auth, error classification, rate-limit headers | MUST | M1 | [x] `src/deng/ingestion/football_data_client.py`, tests |
| 2.2 | Throttling on `X-Requests-Available-Minute`; retry with back-off on 429/5xx | MUST | MIDTERM | [ ] |
| 2.3 | Extract jobs: competition, teams, matches, standings | MUST | MIDTERM | [ ] |
| 2.4 | Extract job: team matches (form across competitions) | SHOULD | MIDTERM | [ ] |
| 2.5 | Extract job: head2head for upcoming matches | COULD | FINAL | [ ] |
| 2.6 | Weather extract: forecast for matches ≤ 16 days ahead | MUST | MIDTERM | [ ] |
| 2.7 | Weather extract: archive actuals for finished matches | SHOULD | FINAL | [ ] |
| 2.8 | Minimal raw validation (top-level keys, non-empty lists, required ids) – fail fast | MUST | MIDTERM | [ ] |
| 2.9 | Full vs. incremental decision per endpoint, documented in README | MUST | MIDTERM | [ ] |
| 2.10 | Structured run logging (run_id, rows, duration, status) into `meta.pipeline_runs` | SHOULD | MIDTERM | [ ] |

## EPIC 3 – PostgreSQL

| # | Task | Prio | Milestone | Status |
|---|---|---|---|---|
| 3.1 | Schemas `raw`, `staging`, `curated`, `meta`; DDL under `sql/` | MUST | MIDTERM | [ ] |
| 3.2 | Raw tables (JSONB + metadata, unique key per source/endpoint/params/date) | MUST | MIDTERM | [ ] |
| 3.3 | Idempotent raw loader (`ON CONFLICT`) | MUST | MIDTERM | [ ] |
| 3.4 | Verification queries (`sql/verify/*.sql`) | MUST | MIDTERM | [ ] |
| 3.5 | Grain documentation for every curated table | MUST | MIDTERM | [ ] |

## EPIC 4 – Docker

| # | Task | Prio | Milestone | Status |
|---|---|---|---|---|
| 4.1 | `docker-compose.yml`: postgres (healthcheck, volume), orchestrator, pipeline image, one network | MUST | MIDTERM | [ ] |
| 4.2 | `Dockerfile` for pipeline code (pinned base image, non-root) | MUST | MIDTERM | [ ] |
| 4.3 | `docker compose up -d` starts everything; `make up/down/logs` | MUST | MIDTERM | [ ] |
| 4.4 | Clean-environment test on a second machine, documented | MUST | MIDTERM | [ ] |

## EPIC 5 – Workflow orchestration

| # | Task | Prio | Milestone | Status |
|---|---|---|---|---|
| 5.1 | Spike Dagster in Compose (schedule, partition, backfill); decide ADR-002 | MUST | MIDTERM | [ ] |
| 5.2 | Daily job with dependencies extract → validate → load → transform → dq | MUST | MIDTERM | [ ] |
| 5.3 | Retry policies (transient only) | MUST | MIDTERM | [ ] |
| 5.4 | Daily partitions; backfill for a date range tested and documented | MUST | MIDTERM | [ ] |
| 5.5 | Rerun test: run twice, compare counts (evidence) | MUST | MIDTERM | [ ] |
| 5.6 | Failure-behaviour matrix implemented (API down, 429, invalid JSON, DB down, missing weather) | MUST | MIDTERM | [ ] |

## EPIC 6 – Transformations

| # | Task | Prio | Milestone | Status |
|---|---|---|---|---|
| 6.1 | staging: typed `matches`, `teams`, `standings`, `weather_forecast` from raw JSONB | MUST | MIDTERM | [ ] |
| 6.2 | curated `fact_match` (grain: one CL match) | MUST | MIDTERM | [ ] |
| 6.3 | curated `fact_team_match_form` – last-5 form, home/away form, days since last match (point-in-time correct) | MUST | MIDTERM | [ ] |
| 6.4 | curated `dim_team`, `dim_venue` | MUST | MIDTERM | [ ] |
| 6.5 | curated `fact_match_snapshot` (grain: one upcoming match per snapshot date) with availability states | SHOULD | MIDTERM (basic) / FINAL (full) | [ ] |
| 6.6 | `dim_date` | SHOULD | FINAL | [ ] |
| 6.7 | Head-to-head aggregates | COULD | FINAL | [ ] |

## EPIC 7 – Data quality

| # | Task | Prio | Milestone | Status |
|---|---|---|---|---|
| 7.1 | SQL checks: not null, unique keys, home ≠ away, valid status, referential integrity, row count > 0 | MUST | MIDTERM | [ ] |
| 7.2 | Plausibility: temperature range, goals ≥ 0, match date within season | SHOULD | MIDTERM | [ ] |
| 7.3 | Results persisted in `meta.dq_results`; critical failures fail the run | MUST | MIDTERM | [ ] |
| 7.4 | Schema-drift handling: required-field validation with clear error, optional fields tolerant | MUST | MIDTERM | [ ] |
| 7.5 | Same checks against BigQuery | MUST | FINAL | [ ] |

## EPIC 8 – Testing

| # | Task | Prio | Milestone | Status |
|---|---|---|---|---|
| 8.1 | Unit tests: config, API client | MUST | M1 | [x] 15 tests, CI |
| 8.2 | Unit tests: parsing of sample payloads, transformations (pure SQL tested against Postgres in CI service) | MUST | MIDTERM | [ ] |
| 8.3 | Idempotency test (load twice) | MUST | MIDTERM | [ ] |
| 8.4 | Data-quality check tests | SHOULD | MIDTERM | [ ] |
| 8.5 | GitHub Actions: lint + tests on every push | SHOULD | M1 | [x] `.github/workflows/ci.yml` |

## EPIC 9 – Google Cloud Storage

| # | Task | Prio | Milestone | Status |
|---|---|---|---|---|
| 9.1 | Raw writer abstraction: Postgres JSONB locally, GCS object in cloud, same interface | MUST | FINAL | [ ] |
| 9.2 | Object layout `raw/source=/endpoint=/ingestion_date=/run_id.json`; deterministic names for safe reruns | MUST | FINAL | [ ] |
| 9.3 | Production path source → GCS without local intermediate file | MUST | FINAL | [ ] |

## EPIC 10 – BigQuery

| # | Task | Prio | Milestone | Status |
|---|---|---|---|---|
| 10.1 | Load/external staging tables from GCS | MUST | FINAL | [ ] |
| 10.2 | Curated tables via `MERGE`; grain documented | MUST | FINAL | [ ] |
| 10.3 | Partitioning (match_date / snapshot_date) and clustering (team ids, match_id) with justification | MUST | FINAL | [ ] |
| 10.4 | Verification queries | MUST | FINAL | [ ] |

## EPIC 11 – Terraform

| # | Task | Prio | Milestone | Status |
|---|---|---|---|---|
| 11.1 | Bucket, dataset, service account, IAM bindings; variables, outputs | MUST | FINAL | [ ] |
| 11.2 | Documented init/validate/plan/apply/destroy and required permissions | MUST | FINAL | [ ] |
| 11.3 | Remote state in GCS bucket | COULD | FINAL | [ ] |

## EPIC 12 – Analytics / ML

| # | Task | Prio | Milestone | Status |
|---|---|---|---|---|
| 12.1 | Notebook/SQL: availability analysis from snapshots | SHOULD | FINAL | [ ] |
| 12.2 | Baseline HOME/DRAW/AWAY model with time-based split on snapshot features | COULD | FINAL | [ ] |

## EPIC 13 – Streamlit

| # | Task | Prio | Milestone | Status |
|---|---|---|---|---|
| 13.1 | Fixture picker → match intelligence page reading curated tables only | COULD | FINAL | [ ] |

## EPIC 14 – Documentation and reproducibility

| # | Task | Prio | Milestone | Status |
|---|---|---|---|---|
| 14.1 | README skeleton with all rubric sections | MUST | M1 | [x] |
| 14.2 | Use case, data sources, Architecture v0.1, ADRs, backlog | MUST | M1 | [x] `docs/` |
| 14.3 | Rubric checklist kept current | SHOULD | all | [~] `docs/rubric-checklist.md` |
| 14.4 | Architecture v0.2 with lessons learned | MUST | MIDTERM | [ ] |
| 14.5 | Setup / execution / verification instructions tested by the other student | MUST | MIDTERM | [ ] |
| 14.6 | Evidence folder: run logs, verification output, rerun/backfill proof | MUST | MIDTERM | [ ] |
| 14.7 | Final architecture and evolution v0.1 → v0.2 → final | MUST | FINAL | [ ] |
| 14.8 | Known limitations section honest and current | MUST | all | [~] |
| 14.9 | Oral-defence question bank with both students' answers | SHOULD | MIDTERM/FINAL | [ ] |

## Division of responsibilities

See [Architecture v0.1 §6](architecture/architecture-v0.1.md#6-division-of-responsibilities-proposal).
Rule: nobody merges their own pull request; the reviewer must be able to explain
the change in the defence.
