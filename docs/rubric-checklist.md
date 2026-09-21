# Rubric Checklist

Translation of the official DENG HS26 project description
(`DENG_HS26_Project_Description.pdf`) into technical requirements. A row is
**DONE** only when technical evidence exists in the repository; plans are TODO.

Status values: TODO · IN PROGRESS · DONE · NOT APPLICABLE

## General requirements (§1.1, §1.4)

| Requirement | Milestone | Status | Implementation | Evidence | Open Tasks |
|---|---|---|---|---|---|
| Use case with problem, end user and data product; transformations linked to it | M1 | DONE | `docs/use-case.md` | document present, transformations listed per table | refine after API exploration |
| Documented data source: provenance, access, format, schema, update frequency, volume, DQ risks | M1 | DONE | `docs/data-sources.md`, `docs/evidence/api-exploration.md` | 8 real payloads committed; 13 contract tests pass; measured volumes and rate limits | how far back seasons go (backlog 1.8) |
| Modular batch ingestion; full vs. incremental, frequency and failure behaviour justified | MIDTERM | DONE | `src/deng/ingestion/{football_data_client,extract}.py`, `src/deng/pipeline.py` | 40 tests pass; `docs/evidence/local-pipeline-run.md` §1–§6 | weather ingestion |
| PostgreSQL locally | MIDTERM | DONE | `sql/raw/001..003`, `src/deng/database/` | 16 raw rows loaded and queried, evidence §1–§5 | staging + curated schemas |
| Cloud storage + warehouse (GCS, BigQuery) in the final solution | FINAL | TODO | – | – | EPIC 9, 10 |
| Transformations justified in README | MIDTERM | DONE | `sql/transform/`, README §Transformation | 6 steps, per-step justification; 16 tests | weather transformations |
| Orchestration: schedule, dependencies, reruns, retries, backfills | MIDTERM | IN PROGRESS | retries + reruns + backfills implemented and evidenced | evidence §2, §3, §6 | scheduling via Dagster (ADR-002) |
| Terraform for GCP resources; no hard-coded secrets | FINAL | TODO | `.env.example`, `.gitignore` rules for tfstate/keys | secrets scan of repo clean | EPIC 11 |
| Reproducibility: clone → README → run assessed stages | MIDTERM / FINAL | IN PROGRESS | `setup.sh`, `Makefile` (20 targets), `--from-samples` lets a reviewer run without an API key | `make test` in CI; evidence reproducible | clean-environment test on a second machine |
| Repository: code, config, diagrams, setup, verification, known limitations | all | IN PROGRESS | `README.md`, `docs/architecture/`, `docs/use-case.md` §Limitations | – | keep current |

## Milestone 1 – initial pitch (§1.5, §2.2 – 10 points)

| Requirement | Milestone | Status | Implementation | Evidence | Open Tasks |
|---|---|---|---|---|---|
| Selected dataset and source system | M1 | DONE | `docs/data-sources.md`, ADR-001 (ACCEPTED) | comparison of 3 football + 3 weather sources; verified against the live API | – |
| User / stakeholder and analytics or ML use case | M1 | DONE | `docs/use-case.md` | – | – |
| Expected output / data product | M1 | DONE | `docs/use-case.md` §Data product | table list with grain | – |
| Data characteristics, risks, challenges | M1 | DONE | `docs/data-sources.md`, `docs/use-case.md` §Limitations, evidence §5–§11 | measured: 144 matches, 11 of 36 clubs without domestic data, inconsistent API aggregates | – |
| Initial ingestion and storage strategy | M1 | DONE | `docs/architecture/architecture-v0.1.md` §2, ADR-003 | – | – |
| Architecture v0.1 incl. division of responsibilities | M1 | DONE | `docs/architecture/architecture-v0.1.md` (Mermaid, §6) | – | fill in second student's name |
| Initial README | M1 | DONE | `README.md` | – | – |
| Short project plan / backlog | M1 | DONE | `docs/project-backlog.md` | – | – |
| Pitch (10 min): feasibility, source understanding, ingestion/storage reasoning | M1 | TODO | – | – | rehearse with question bank |

## Midterm (§1.6, §2.3 – 40 points)

| Requirement | Milestone | Status | Implementation | Evidence | Open Tasks |
|---|---|---|---|---|---|
| Modular batch-ingestion script loading source data into storage (4 pts) | MIDTERM | DONE | client + extract + raw loader + CLI | evidence §1, 40 tests | weather source |
| Local PostgreSQL with loaded, queryable data (2 pts) | MIDTERM | DONE | `raw.football_data`, `meta.pipeline_runs` | `make verify` 2/2 passed, evidence §5 | curated tables |
| Docker Compose with required services on a common network (3 pts) | MIDTERM | IN PROGRESS | `docker-compose.yml`, `Dockerfile` | executed on an empty volume: postgres, pipeline image, app image (evidence §11) | add orchestrator service |
| Orchestrator runs and schedules ingestion, supports reruns/backfills (3 pts) | MIDTERM | IN PROGRESS | CLI parameterised by logical date; reruns and backfills proven | evidence §2, §3 | scheduler itself (ADR-002 spike) |
| ≥ 1 justified transformation supporting the use case | MIDTERM | DONE | `fact_match`, `fact_team_match_form` | point-in-time form; leakage guard tested | – |
| Architecture v0.2 reflecting implementation experience | MIDTERM | TODO | – | – | 14.4 |
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
| Analytical data model; grain stated per final table; facts/dimensions identified | FINAL | IN PROGRESS | `docs/data-model.md`; grains also as COMMENT ON TABLE | 3 curated tables live | BigQuery version, dim_date/dim_venue |
| Partitioning and clustering justified by query patterns | FINAL | TODO | initial idea in architecture v0.1 §3 | – | ADR |
| Data-quality checks, failure handling, safe reruns (2 pts) | FINAL | IN PROGRESS | 12 checks persisted to `meta.dq_results`; transactional transform | evidence; CI smoke test | same checks against BigQuery |
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
