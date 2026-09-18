# Rubric Checklist

Translation of the official DENG HS26 project description
(`DENG_HS26_Project_Description.pdf`) into technical requirements. A row is
**DONE** only when technical evidence exists in the repository; plans are TODO.

Status values: TODO · IN PROGRESS · DONE · NOT APPLICABLE

## General requirements (§1.1, §1.4)

| Requirement | Milestone | Status | Implementation | Evidence | Open Tasks |
|---|---|---|---|---|---|
| Use case with problem, end user and data product; transformations linked to it | M1 | DONE | `docs/use-case.md` | document present, transformations listed per table | refine after API exploration |
| Documented data source: provenance, access, format, schema, update frequency, volume, DQ risks | M1 | IN PROGRESS | `docs/data-sources.md` | comparison tables incl. limits and volume | real payload schema (backlog 1.3–1.5) |
| Modular batch ingestion; full vs. incremental, frequency and failure behaviour justified | MIDTERM | IN PROGRESS | `src/deng/ingestion/football_data_client.py` | 15 unit tests pass (`pytest`) | extract jobs, loader, decision table |
| PostgreSQL locally | MIDTERM | TODO | – | – | schemas, DDL, Compose service |
| Cloud storage + warehouse (GCS, BigQuery) in the final solution | FINAL | TODO | – | – | EPIC 9, 10 |
| Transformations justified in README | MIDTERM | TODO | – | – | EPIC 6 |
| Orchestration: schedule, dependencies, reruns, retries, backfills | MIDTERM | TODO | ADR-002 (PROPOSED) | – | EPIC 5 |
| Terraform for GCP resources; no hard-coded secrets | FINAL | TODO | `.env.example`, `.gitignore` rules for tfstate/keys | secrets scan of repo clean | EPIC 11 |
| Reproducibility: clone → README → run assessed stages | MIDTERM / FINAL | TODO | `Makefile` (`setup`, `test`, `lint`, `explore`) | `make test` passes in CI | Docker Compose, verification steps |
| Repository: code, config, diagrams, setup, verification, known limitations | all | IN PROGRESS | `README.md`, `docs/architecture/`, `docs/use-case.md` §Limitations | – | keep current |

## Milestone 1 – initial pitch (§1.5, §2.2 – 10 points)

| Requirement | Milestone | Status | Implementation | Evidence | Open Tasks |
|---|---|---|---|---|---|
| Selected dataset and source system | M1 | DONE | `docs/data-sources.md`, ADR-001 | comparison of 3 football + 3 weather sources | ACCEPT ADR-001 after exploration |
| User / stakeholder and analytics or ML use case | M1 | DONE | `docs/use-case.md` | – | – |
| Expected output / data product | M1 | DONE | `docs/use-case.md` §Data product | table list with grain | – |
| Data characteristics, risks, challenges | M1 | DONE | `docs/data-sources.md` (risks, limits), `docs/use-case.md` §Limitations | – | add real volume numbers from samples |
| Initial ingestion and storage strategy | M1 | DONE | `docs/architecture/architecture-v0.1.md` §2, ADR-003 | – | – |
| Architecture v0.1 incl. division of responsibilities | M1 | DONE | `docs/architecture/architecture-v0.1.md` (Mermaid, §6) | – | fill in second student's name |
| Initial README | M1 | DONE | `README.md` | – | – |
| Short project plan / backlog | M1 | DONE | `docs/project-backlog.md` | – | – |
| Pitch (10 min): feasibility, source understanding, ingestion/storage reasoning | M1 | TODO | – | – | rehearse with question bank |

## Midterm (§1.6, §2.3 – 40 points)

| Requirement | Milestone | Status | Implementation | Evidence | Open Tasks |
|---|---|---|---|---|---|
| Modular batch-ingestion script loading source data into storage (4 pts) | MIDTERM | IN PROGRESS | client done; extract/load TODO | unit tests | EPIC 2, 3 |
| Local PostgreSQL with loaded, queryable data (2 pts) | MIDTERM | TODO | – | – | EPIC 3, verification queries |
| Docker Compose with required services on a common network (3 pts) | MIDTERM | TODO | – | – | EPIC 4 |
| Orchestrator runs and schedules ingestion, supports reruns/backfills (3 pts) | MIDTERM | TODO | – | – | EPIC 5 |
| ≥ 1 justified transformation supporting the use case | MIDTERM | TODO | – | – | 6.2, 6.3 |
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
| Analytical data model; grain stated per final table; facts/dimensions identified | FINAL | TODO | `docs/use-case.md` lists planned grains | – | ADR data model |
| Partitioning and clustering justified by query patterns | FINAL | TODO | initial idea in architecture v0.1 §3 | – | ADR |
| Data-quality checks, failure handling, safe reruns (2 pts) | FINAL | TODO | – | – | EPIC 7, 41 |
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
