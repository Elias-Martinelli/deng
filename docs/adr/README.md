# Architecture Decision Records

We record only decisions that shape the architecture and that we must be able to
defend orally. Small implementation choices live in code comments and the README.

Format per ADR: Context → Decision → Alternatives Considered → Advantages →
Disadvantages → Consequences. Status is one of **PROPOSED**, **ACCEPTED**,
**SUPERSEDED** (with a link to the superseding ADR).

| ADR | Title | Status | Date |
|---|---|---|---|
| [ADR-001](ADR-001-football-data-source.md) | Football and weather data sources | PROPOSED | 2026-09-18 |
| [ADR-002](ADR-002-workflow-orchestrator.md) | Workflow orchestrator | PROPOSED | 2026-09-18 |
| [ADR-003](ADR-003-raw-data-storage.md) | Raw data storage strategy | PROPOSED | 2026-09-18 |

Planned (not yet written because the decision is not yet due): transformation
approach (SQL files vs. dbt), analytical data model and grain, BigQuery
partitioning/clustering, cloud compute placement.
