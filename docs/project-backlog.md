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
| 1.3 | Register free key, run `scripts/explore_football_api.py`, commit small samples to `data/sample/` | MUST | M1 | [x] `data/sample/football-data/` (8 payloads) |
| 1.4 | Document schema, business keys, null behaviour from real payloads (`docs/evidence/api-exploration.md`) | MUST | M1 | [x] evidence doc + 13 contract tests |
| 1.5 | Confirm/refute "current season only" and head2head behaviour; set ADR-001 to ACCEPTED | MUST | M1 | [x] refuted – history IS served; ADR-001 ACCEPTED |
| 1.6 | Stadium coordinates per club (lat, lon, tz) | MUST | MIDTERM | [x] OpenStreetMap is a pipeline source now: `src/deng/sources/openstreetmap.py` → `raw.osm_venues` → `sql/transform/305_staging_venues.sql`; `make venues` = `ingest --only openstreetmap`; 34/36 league-phase clubs resolved, evidence weather §2 |
| 1.7 | ClubElo as cross-season strength signal | COULD | FINAL | [ ] (lower value now that the API serves history) |
| 1.8 | Probe how far back seasons are actually served (test 2015, 2005, 1995) | SHOULD | MIDTERM | [~] 2023/24 (125 matches) and 2024/25 (189) ingested; the API lists 47 seasons, older ones untested |
| 1.9 | Decide how many past seasons to ingest, and document the reason | MUST | MIDTERM | [x] the decision is a setting: `FOOTBALL_DATA_SEASONS` in `src/deng/config.py` (start years, comma-separated; empty = current season only), one matches + one teams request per season. With 2023 and 2024: 458 matches, 60 clubs, 332 with a label, 664 form rows, 24/24 DQ checks pass |
| 1.10 | Bookmaker odds source evaluated and decided (The Odds API, ADR-005) | SHOULD | FINAL | [x] `docs/data-sources.md` §2b, `src/deng/sources/the_odds_api.py` |
| 1.11 | Decide how many seasons the final model needs, and measure what they cost (one request per season and endpoint) | MUST | FINAL | [ ] |

## EPIC 2 – Local batch ingestion

| # | Task | Prio | Milestone | Status |
|---|---|---|---|---|
| 2.1 | API client with auth, error classification, rate-limit headers | MUST | M1 | [x] `src/deng/sources/football_data.py`, shared errors in `sources/http.py`, tests |
| 2.2 | Throttling on `X-Requests-Available-Minute`; retry with back-off on 429/5xx | MUST | MIDTERM | [x] `sources/football_data.py` (`MIN_SECONDS_BETWEEN_REQUESTS`, `_get_with_retry`) |
| 2.3 | Extract jobs: competition, teams, matches, standings | MUST | MIDTERM | [x] `DAILY_ENDPOINTS`, plus `season_endpoints()` for past seasons, both in `sources/football_data.py` |
| 2.4 | ~~Extract job: team matches (form across competitions)~~ | SHOULD | MIDTERM | dropped – ADR-004 (Champions League only) |
| 2.5 | Extract job: head2head for upcoming matches – first retest with a pairing known to have met | COULD | FINAL | [ ] |
| 2.6 | Weather extract: forecast for matches ≤ 16 days ahead | MUST | MIDTERM | [x] `sources/open_meteo.py`; first live forecast 28 Sep |
| 2.7 | Weather extract: archive actuals for finished matches | SHOULD | FINAL | [ ] |
| 2.8 | Minimal raw validation (top-level keys, non-empty lists, required ids) – fail fast | MUST | MIDTERM | [ ] |
| 2.9 | Full vs. incremental decision per endpoint, documented in README | MUST | MIDTERM | [x] table in README, rationale in code |
| 2.10 | Structured run logging (run_id, rows, duration, status) into `meta.pipeline_runs` | SHOULD | MIDTERM | [x] `database/run_log.py`, evidence §4 |
| 2.11 | One ingestion for all five sources: ask every source, store every answer, transform afterwards | MUST | MIDTERM | [x] `src/deng/sources/` (one file per source) + `src/deng/ingestion/runner.py`; CLI `ingest [--only …]` |
| 2.12 | Layering rule: ingestion reads the APIs, `data/` and the raw zone – never staging, never curated | MUST | MIDTERM | [x] `tests/test_layering.py`; the planning views `raw.match_calendar`, `raw.team_catalog` (009) and `raw.venue_coordinates` (010) replace the curated reads |

## EPIC 3 – PostgreSQL

| # | Task | Prio | Milestone | Status |
|---|---|---|---|---|
| 3.1 | Schemas `raw`, `staging`, `curated`, `meta`; DDL under `sql/` | MUST | MIDTERM | [x] `sql/schema/001..011` |
| 3.2 | Raw tables (JSONB + metadata, unique key per source/endpoint/params/date) | MUST | MIDTERM | [x] one per source: `raw.football_data`, `raw.open_meteo`, `raw.odds_api`, `raw.team_crests`, `raw.osm_venues` |
| 3.3 | Idempotent raw loader (`ON CONFLICT`) | MUST | MIDTERM | [x] `raw_loader.py`, evidence §2 |
| 3.4 | Verification queries (`sql/verify/*.sql`) | MUST | MIDTERM | [x] 14 checks in 3 files, `make verify` |
| 3.5 | Grain documentation for every curated table | MUST | MIDTERM | [x] `docs/data-model.md` + `COMMENT ON TABLE` |

## EPIC 4 – Docker

| # | Task | Prio | Milestone | Status |
|---|---|---|---|---|
| 4.1 | `docker-compose.yml`: postgres (healthcheck, volume), orchestrator, pipeline image, one network | MUST | MIDTERM | [x] + Dagster webserver/daemon, evidence §12 |
| 4.2 | `Dockerfile` for pipeline code (pinned base image, non-root) | MUST | MIDTERM | [x] python:3.12-slim-bookworm, uid 1000 |
| 4.3 | `docker compose up -d` starts everything; `make up/down/logs` | MUST | MIDTERM | [x] `make up`, `docker-ingest`, `docker-app` executed, evidence §11 |
| 4.4 | Clean-environment test on a second machine, documented | MUST | MIDTERM | [ ] |

## EPIC 5 – Workflow orchestration

| # | Task | Prio | Milestone | Status |
|---|---|---|---|---|
| 5.1 | Spike Dagster in Compose (schedule, partition, backfill); decide ADR-002 | MUST | MIDTERM | [x] ADR-002 ACCEPTED |
| 5.2 | Daily job with dependencies extract → validate → load → transform → dq | MUST | MIDTERM | [~] `daily_pipeline` ingest → transform → dq; validate step waits for 2.8 |
| 5.3 | Retry policies (transient only) | MUST | MIDTERM | [x] `TRANSIENT_RETRY` + `run_step`, tested |
| 5.4 | Daily partitions; backfill for a date range tested and documented | MUST | MIDTERM | [x] CLI (§3) and Dagster (§12) |
| 5.5 | Rerun test: run twice, compare counts (evidence) | MUST | MIDTERM | [x] evidence §2 + integration test |
| 5.6 | Failure-behaviour matrix implemented (API down, 429, invalid JSON, DB down, missing weather) | MUST | MIDTERM | [ ] |

## EPIC 6 – Transformations

| # | Task | Prio | Milestone | Status |
|---|---|---|---|---|
| 6.1 | staging: typed `matches`, `teams`, `standings` from raw JSONB | MUST | MIDTERM | [x] `sql/transform/110–112`; staging for the other sources too: 305 venues, 310 weather, 410 odds (13 files in total) |
| 6.2 | curated `fact_match` (grain: one CL match) | MUST | MIDTERM | [x] derived outcome; 144 rows for the current league phase, 458 with the seasons 2023 and 2024 |
| 6.3 | curated `fact_team_match_form` – last-5 form, home/away form, days since last match (point-in-time correct); must carry `matches_considered` because 11 of 36 clubs have no domestic data | MUST | MIDTERM | [x] CL-only by ADR-004, leakage check + `matches_considered` |
| 6.4 | curated `dim_team` (+ `dim_venue` with the weather work) | MUST | MIDTERM | [x] `dim_team`, `dim_venue`, `fact_match_weather` |
| 6.5 | curated `fact_match_snapshot` (grain: one upcoming match per snapshot date) with availability states – the table a model is actually trained on | SHOULD | MIDTERM (basic) / FINAL (full) | [ ] today `curated.model_features` (6.8) gives one row per match; the snapshot adds one row per match **per day** |
| 6.6 | `dim_date` | SHOULD | FINAL | [ ] |
| 6.7 | Head-to-head aggregates | COULD | FINAL | [ ] |
| 6.8 | `curated.model_features`: one row per match, the label plus the features known before kick-off | SHOULD | MIDTERM | [x] `sql/schema/011_model_features.sql`; what a model would read, and what the dashboard (13.6) shows |

## EPIC 7 – Data quality

| # | Task | Prio | Milestone | Status |
|---|---|---|---|---|
| 7.1 | SQL checks: not null, unique keys, home ≠ away, valid status, referential integrity, row count > 0 | MUST | MIDTERM | [x] `quality/checks.py`, 24 checks in total (football, form, weather, venue, forecast, odds, crests) |
| 7.2 | Plausibility: goals in range (temperature with the weather work) | SHOULD | MIDTERM | [x] `goals_are_plausible`, `weather_values_plausible` |
| 7.3 | Results persisted in `meta.dq_results`; critical failures fail the run | MUST | MIDTERM | [x] persisted per run, CRITICAL exits non-zero |
| 7.4 | Schema-drift handling: required-field validation with clear error, optional fields tolerant | MUST | MIDTERM | [ ] |
| 7.5 | Same checks against BigQuery | MUST | FINAL | [ ] |

## EPIC 8 – Testing

| # | Task | Prio | Milestone | Status |
|---|---|---|---|---|
| 8.1 | Unit tests: config, API client | MUST | M1 | [x] 16 tests (`test_config.py`, `test_football_data_client.py`); 137 tests in total, CI |
| 8.1b | Contract tests against the real samples (schema, keys, referential integrity) | SHOULD | M1 | [x] 13 tests in `tests/test_sample_payloads.py` |
| 8.2 | Tests for parsing and transformations against Postgres, also in CI | MUST | MIDTERM | [x] 18 transformation tests; CI has a Postgres service |
| 8.3 | Idempotency test (load twice) | MUST | MIDTERM | [x] `test_second_run_same_day_does_not_duplicate` |
| 8.4 | Data-quality check tests incl. a deliberately broken row | SHOULD | MIDTERM | [x] `test_a_critical_violation_is_detected` |
| 8.5 | GitHub Actions: lint + tests on every push | SHOULD | M1 | [x] `.github/workflows/ci.yml` |
| 8.6 | Separate test database, so `make test` does not empty the local pipeline data | SHOULD | MIDTERM | [ ] `tests/conftest.py` truncates raw, staging and curated, so a test run costs the ingested seasons and the odds credits already spent |
| 8.7 | Architecture rule as a test: ingestion never reads staging or curated | MUST | MIDTERM | [x] `tests/test_layering.py` (see 2.12) |

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
| 12.1 | Notebook: exploration of the curated layer incl. independent leakage check | SHOULD | FINAL | [x] `notebooks/01_explore_curated_data.ipynb` |
| 12.2 | Baseline HOME/DRAW/AWAY model with time-based split on snapshot features | COULD | FINAL | [~] `form-poisson-v1` in SQL as the comparison baseline (`240_fact_match_prediction.sql`); evaluation against results open |
| 12.3 | Live model updated with the match state, so an in-play comparison with live odds is honest | COULD | later | [ ] until then the app labels in-play forecasts as pre-match |

## EPIC 13 – Streamlit

| # | Task | Prio | Milestone | Status |
|---|---|---|---|---|
| 13.1 | Fixture picker → match intelligence page reading curated tables only | COULD | FINAL | [x] `app/streamlit_app.py`, screenshot in evidence; now the second half of the dashboard (13.6) |
| 13.3 | Club crests stored in the database, shown in the viewer | COULD | FINAL | [x] `raw.team_crests`, evidence weather §5 |
| 13.2 | Responsive layout for phones (iPhone, Android) instead of native apps | COULD | FINAL | [x] `app/components.py`, evidence §13; real-device check open |
| 13.4 | Model forecast vs. bookmaker odds: named platforms, h2h, both timestamps, change history, chart; odds fetched only by the pipeline under a credit budget | COULD | FINAL | [x] ADR-005, `sources/the_odds_api.py`, `transformation/odds_matching.py`, `sql/transform/240/410/420`, `app/odds_view.py`; first live fetch with a real key open |
| 13.5 | Evidence of a real odds fetch (key registered, `make odds`, quota headers, first unmatched-event alias) | SHOULD | FINAL | [ ] |
| 13.6 | Analysis dashboard for the model data: dataset size per season, feature coverage with the reason a feature is absent, leakage guarantees recomputed from the tables | COULD | FINAL | [x] `app/dataset_view.py` over `curated.model_features`; curated tables only, no API call |

## EPIC 14 – Documentation and reproducibility

| # | Task | Prio | Milestone | Status |
|---|---|---|---|---|
| 14.1 | README skeleton with all rubric sections | MUST | M1 | [x] |
| 14.2 | Use case, data sources, Architecture v0.1, ADRs, backlog | MUST | M1 | [x] `docs/` |
| 14.3 | Rubric checklist kept current | SHOULD | all | [~] `docs/rubric-checklist.md` |
| 14.4 | Architecture v0.2 with lessons learned (five sources, one ingestion, the layering rule) | MUST | MIDTERM | [~] the three new diagrams exist (`docs/architecture-overview.svg`, `-detail.svg`, `-target.svg`); the written document is open |
| 14.5 | Setup / execution / verification instructions tested by the other student | MUST | MIDTERM | [ ] |
| 14.6 | Evidence folder: run logs, verification output, rerun/backfill proof | MUST | MIDTERM | [ ] |
| 14.7 | Final architecture and evolution v0.1 → v0.2 → final | MUST | FINAL | [ ] |
| 14.8 | Known limitations section honest and current | MUST | all | [~] |
| 14.9 | Oral-defence question bank with both students' answers | SHOULD | MIDTERM/FINAL | [ ] |
| 14.10 | README points at the three new diagrams; delete the outdated `docs/architecture.svg` (it predates the odds source, OpenStreetMap and the restructure) | MUST | MIDTERM | [x] README shows all three; `docs/architecture.svg` deleted |
| 14.11 | Documentation drift after the restructure: `README.md`, `docs/data-model.md`, `docs/data-sources.md`, ADR-001, architecture v0.1 and one DQ description still name the deleted `data/reference/venues.csv`, and none of them mentions `raw.osm_venues`, the raw planning views or `curated.model_features` | MUST | MIDTERM | [x] no document presents `venues.csv` or `scripts/build_venues.py` as current (only as history); `raw.osm_venues`, the three raw planning views and `curated.model_features` are in `docs/data-model.md` and the README; ADR-001 and architecture v0.1 carry a note saying what changed |

## Division of responsibilities

Elias Martinelli and Noah Rodriguez — see
[README](../README.md#contributing-and-branch-strategy) and
[Architecture v0.1 §6](architecture/architecture-v0.1.md#6-division-of-responsibilities-proposal).
Rule: nobody merges their own pull request; the reviewer must be able to explain
the change in the defence.
