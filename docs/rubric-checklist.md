# Rubric Checklist

Translation of the official DENG HS26 project description
(`DENG_HS26_Project_Description.pdf`) into technical requirements. A row is
**DONE** only when technical evidence exists in the repository; plans are TODO.

Status values: TODO · IN PROGRESS · DONE · NOT APPLICABLE

## General requirements (§1.1, §1.4)

| Requirement | Milestone | Status | Implementation | Evidence | Open Tasks |
|---|---|---|---|---|---|
| Use case with problem, end user and data product; transformations linked to it | M1 | DONE | `docs/use-case.md` | document present, transformations listed per table | refine after API exploration |
| Documented data source: provenance, access, format, schema, update frequency, volume, DQ risks | M1 | DONE | `docs/data-sources.md`, `docs/evidence/api-exploration.md`, ADR-001, ADR-005 | five sources (football-data.org, Open-Meteo, The Odds API, OpenStreetMap, crest images); real payloads committed per source; 13 contract tests; measured volumes and rate limits | seasons older than 2023 untested (1.8) |
| Modular batch ingestion; full vs. incremental, frequency and failure behaviour justified | MIDTERM | DONE | one file per source in `src/deng/sources/`, one runner in `src/deng/ingestion/runner.py`, one CLI command `ingest [--only …]` | 137 tests pass, incl. `tests/test_layering.py`: ingestion reads the APIs, `data/` and the raw zone – never staging or curated; `docs/evidence/local-pipeline-run.md` §1–§6, `docs/evidence/weather.md` | raw validation (2.8), failure matrix (5.6) |
| PostgreSQL locally | MIDTERM | DONE | `sql/schema/001..011`, `src/deng/database/` | one raw table per source (`football_data`, `open_meteo`, `odds_api`, `team_crests`, `osm_venues`) plus staging and curated; 458 matches and 60 clubs curated with the seasons 2023 + 2024; evidence §1–§5 | – |
| Cloud storage + warehouse (GCS, BigQuery) in the final solution | FINAL | TODO | – | – | EPIC 9, 10 |
| Transformations justified in README | MIDTERM | DONE | `sql/transform/` (13 files), README §Transformation | football 110–112/210–240, venues 305, weather 310–330, odds 410–420, plus the view `curated.model_features` (011); per-step justification; transformation, weather and odds tests | – |
| Orchestration: schedule, dependencies, reruns, retries, backfills | MIDTERM | DONE | Dagster `daily_pipeline` + schedule, transient-only retries | evidence §2, §3, §6, §12; `tests/test_orchestration.py` | validate step (2.8), failure matrix (5.6) |
| Terraform for GCP resources; no hard-coded secrets | FINAL | TODO | `.env.example`, `.gitignore` rules for tfstate/keys | secrets scan of repo clean | EPIC 11 |
| Reproducibility: clone → README → run assessed stages | MIDTERM / FINAL | IN PROGRESS | `setup.sh`, `Makefile`, `--from-samples` lets a reviewer run without an API key – including the OpenStreetMap answers in `data/sample/openstreetmap/` | `make run-samples`; 137 tests in CI; evidence reproducible | clean-environment test on a second machine (4.4); separate test database, because `make test` empties the pipeline tables (8.6) |
| Repository: code, config, diagrams, setup, verification, known limitations | all | IN PROGRESS | `README.md`, `docs/architecture/`, `docs/use-case.md` §Limitations; new diagrams `docs/architecture-overview.svg`, `-detail.svg`, `-target.svg` | – | the written Architecture v0.2 (14.4); clean-environment test (4.4) |

## Milestone 1 – initial pitch (§1.5, §2.2 – 10 points)

| Requirement | Milestone | Status | Implementation | Evidence | Open Tasks |
|---|---|---|---|---|---|
| Selected dataset and source system | M1 | DONE | `docs/data-sources.md`, ADR-001 (ACCEPTED) | comparison of 3 football + 3 weather sources; verified against the live API | – |
| User / stakeholder and analytics or ML use case | M1 | DONE | `docs/use-case.md` | – | – |
| Expected output / data product | M1 | DONE | `docs/use-case.md` §Data product | table list with grain | – |
| Data characteristics, risks, challenges | M1 | DONE | `docs/data-sources.md`, `docs/use-case.md` §Limitations, evidence §5–§11 | measured: 144 matches, 11 of 36 clubs without domestic data, inconsistent API aggregates | – |
| Initial ingestion and storage strategy | M1 | DONE | `docs/architecture/architecture-v0.1.md` §2, ADR-003 | – | – |
| Architecture v0.1 incl. division of responsibilities | M1 | DONE | `docs/architecture/architecture-v0.1.md` (Mermaid, §6), rendered as `docs/architecture-overview.svg` / `-detail.svg` / `-target.svg` | §6 names both students per area with the other as reviewer; the same table is slide 10 of the pitch | – |
| Initial README | M1 | DONE | `README.md` | – | – |
| Short project plan / backlog | M1 | DONE | `docs/project-backlog.md` | – | – |
| Pitch (10 min): feasibility, source understanding, ingestion/storage reasoning, answers to questions | M1 | IN PROGRESS | `docs/pitch/slides.md` (10 slides, one per §1.5 requirement), `docs/pitch/speaker-notes.md` (German, per slide) | timing table for two speakers, 16 expected questions with short answers incl. full vs. incremental, behaviour at 100× data, Dagster vs. Airflow, data quality and licences; `docs/code-walkthrough.md` for questions that go past the slides | rehearse out loud, both speakers, once against the clock |

## Midterm (§1.6, §2.3 – 40 points)

| Requirement | Milestone | Status | Implementation | Evidence | Open Tasks |
|---|---|---|---|---|---|
| Modular batch-ingestion script loading source data into storage (4 pts) | MIDTERM | DONE | five sources + one ingestion runner + raw loader + CLI | evidence §1, weather evidence §3; `ingest --only openstreetmap` replaced the hand-run `scripts/build_venues.py` | – |
| Local PostgreSQL with loaded, queryable data (2 pts) | MIDTERM | DONE | five raw tables, `meta.pipeline_runs`, staging and curated | `make verify`: 14 checks in 3 files, evidence §5 | – |
| Docker Compose with required services on a common network (3 pts) | MIDTERM | DONE | `docker-compose.yml`, `Dockerfile` | executed on an empty volume: postgres, Dagster webserver + daemon, pipeline and app images (evidence §11, §12) | clean-environment test (4.4) |
| Orchestrator runs and schedules ingestion, supports reruns/backfills (3 pts) | MIDTERM | DONE | Dagster in Compose, daily partitions, schedule RUNNING | evidence §12, ADR-002 | – |
| ≥ 1 justified transformation supporting the use case | MIDTERM | DONE | `fact_match`, `fact_team_match_form`, `fact_match_weather`, `fact_match_prediction`, `fact_bookmaker_odds`, view `model_features` | point-in-time form; leakage guard tested and recomputed from the tables in the dashboard | – |
| Architecture v0.2 reflecting implementation experience | MIDTERM | IN PROGRESS | `docs/architecture-overview.svg` (ingest → transform → data product), `-detail.svg` (sources, raw/staging/curated, platform), `-target.svg` (local today vs. cloud for the final) | diagrams match the code after the restructure | the written v0.2 with lessons learned (14.4) |
| Complete setup, execution, verification instructions | MIDTERM | TODO | – | – | 14.5 |
| Peer reproducibility (5 pts): independent execution by peers | MIDTERM | TODO | – | – | 4.4 clean-environment test |
| Oral defence (18 pts): architecture, ingestion/storage decisions, orchestration, reliability, evidence | MIDTERM | TODO | ADRs, evidence folder | – | question bank, both students |
| Submit repo link + commit hash/tag via ILIAS by **22 Oct 2026 15:30** | MIDTERM | TODO | – | – | tag `midterm` |

## Final (§1.7, §2.4 – 50 points)

| Requirement | Milestone | Status | Implementation | Evidence | Open Tasks |
|---|---|---|---|---|---|
| Terraform provisions GCS bucket + BigQuery dataset (3 pts) | FINAL | TODO | – | – | EPIC 11 |
| Orchestrated, schedulable pipeline source → cloud data lake; production path must not depend on local storage (3 pts) | FINAL | TODO | – | – | EPIC 9 |
| Transformation pipeline data lake → curated BigQuery tables (3 pts, with warehouse design) | FINAL | TODO | – | – | EPIC 10 |
| Analytical data model; grain stated per final table; facts/dimensions identified | FINAL | IN PROGRESS | `docs/data-model.md`; grains also as COMMENT ON TABLE | 7 curated tables live (2 dimensions, 5 facts) plus views, incl. `curated.model_features`: one row per match, label + the features known before kick-off | `fact_match_snapshot` as the training table (6.5), BigQuery version, `dim_date` |
| Partitioning and clustering justified by query patterns | FINAL | TODO | initial idea in architecture v0.1 §3 | – | ADR |
| Data-quality checks, failure handling, safe reruns (2 pts) | FINAL | IN PROGRESS | 24 checks persisted to `meta.dq_results`; transactional transform | 24/24 pass with the seasons 2023 + 2024 ingested; evidence; CI smoke test | schema-drift handling (7.4), same checks against BigQuery (7.5) |
| Documentation, configuration examples, verification queries, known limitations (2 pts) | FINAL | TODO | `.env.example` | – | – |
| Final architecture + evolution from v0.1 | FINAL | TODO | v0.1 exists | – | 14.7 |
| Peer reproducibility (5 pts) | FINAL | TODO | – | – | clean-environment test |
| Oral defence (27 pts) | FINAL | TODO | – | – | question bank |
| Submit via ILIAS by **10 Dec 2026 20:00** | FINAL | TODO | – | – | tag `final` |

## Cross-cutting conditions (§1.2, §1.3, §2.7)

| Requirement | Milestone | Status | Implementation | Evidence | Open Tasks |
|---|---|---|---|---|---|
| Both students contribute; Git history shows meaningful contributions | all | IN PROGRESS | branch + PR workflow, conventional commits | – | second student's commits |
| Both students understand the complete architecture | all | TODO | ADRs, question bank | – | mutual reviews |
| Credentials never committed; `.env.example` provided; permissions documented | all | DONE (for current state) | `.env.example`, `.gitignore` | no secrets in history (checked) | GCP permissions doc |
| Large datasets not committed; acquisition instructions instead | all | DONE (for current state) | `data/raw/` ignored, `make explore` fetches samples | – | keep samples < 1 MB |
| Known limitations documented honestly | all | IN PROGRESS | `docs/use-case.md` §Limitations | – | README section |
| Peer reviews of two other teams (5 pts each milestone) | MIDTERM / FINAL | TODO | – | – | due 12 Nov / 31 Dec |
