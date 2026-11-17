# Architecture Decision Records

We record only decisions that shape the architecture and that we must be able to
defend orally. Small implementation choices live in code comments and the README.

Format per ADR: Context → Decision → Alternatives Considered → Advantages →
Disadvantages → Consequences. Status is one of **PROPOSED**, **ACCEPTED**,
**SUPERSEDED** (with a link to the superseding ADR).

| ADR | Title | Status | Date |
|---|---|---|---|
| [ADR-001](ADR-001-football-data-source.md) | Football and weather data sources | ACCEPTED | 2026-09-20 |
| [ADR-002](ADR-002-workflow-orchestrator.md) | Workflow orchestrator | ACCEPTED (Dagster) | 2026-09-21 |
| [ADR-003](ADR-003-raw-data-storage.md) | Raw data storage strategy | ACCEPTED | 2026-09-20 |
| [ADR-004](ADR-004-champions-league-scope.md) | Scope: Champions League matches only, free tier only | ACCEPTED | 2026-09-21 |
| [ADR-005](ADR-005-bookmaker-odds-source.md) | Bookmaker odds: The Odds API, fetched by the pipeline under a credit budget | ACCEPTED | 2026-09-22 |
| [ADR-007](ADR-007-cloud-raw-zone-and-warehouse.md) | Cloud path: raw zone mirrored to GCS, read in BigQuery as an external table | PROPOSED | 2026-11-17 |

Planned (not yet written because the decision is not yet due): transformation
approach (SQL files vs. dbt), analytical data model and grain, cloud compute
placement. BigQuery partitioning and clustering are decided in ADR-007.

- [ADR-006 — multi-league training product](ADR-006-multi-league-training-product.md): accepted; supersedes ADR-004.
