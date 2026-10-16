# Architecture v0.2 — multi-league training product

Status: implemented locally, 3 October 2026. Supersedes v0.1's CL-only scope.
Cloud deployment remains planned for the final milestone.

## Data flow and responsibilities

1. Python source modules obtain football JSON, venue responses, forecast JSON,
   bookmaker responses, crest images and optional dated team CSVs.
2. Raw tables preserve source payloads with hashes, requests, receipt times and run IDs.
   CSV imports are immutable by content hash; football responses are daily upserts.
3. SQL stages type/deduplicate matches, teams and TOTAL standings. Competition
   code and season determine scope; shared clubs have one stable provider team ID.
4. Curated match facts and indexed team appearances derive history. The context
   stage joins the last eligible squad, coach and valuation separately.
5. A view assembles one wide row per canonical fixture. Quality checks independently
   measure grain, labels and timestamp rules.
6. CSV plus machine-readable contract/coverage serves the data scientist.
   Streamlit queries the database and pages through 500 fixtures at a time.

## Why this design changed

The initial 458-match CL dataset had too little history. Eight competitions and
three prior seasons produced 10,103 matches. Domestic and CL fixtures now both
contribute to overall form; same-competition and home/away form remain separate.
This avoids pretending every club has complete domestic coverage.

Current dimensions are descriptions, not historical squad evidence. Raw team
payloads now create observed snapshots and individual player rows. Only current
team endpoints supply new squad observations: a season parameter cannot prove
current membership. A dated CSV supports licensed historical valuations.

Full-time goals may include extra time. Training labels explicitly prefer
regularTime scores; when an extra-time fixture has no regularTime score, its
label is NULL. It still counts as workload.

## Runtime boundaries

The CLI builds football, weather, odds, then context/training in separate logged
transactions. Dagster includes a training asset after football and weather, with
DQ dependent on it. Odds refresh is a separate unpartitioned job. The daily
ingestion step also obtains optional odds under the existing budget.

Multi-statement transformation files use psycopg ClientCursor for safe parameter
adaptation. No hand-built date strings or semicolon splitting are used.
Indexes on team/time, competition/season, venue and opponent support bounded
history lookups. Cumulative season measures avoid one full scan per feature.
Export uses a server cursor and repeatable read.

## Failure and rerun semantics

- Core API errors roll back that source ingestion and record failure.
- Retries are limited to transient errors; a forbidden competition needs a plan/config fix.
- Completed historical payloads are reused. An explicit refresh flag requests corrections.
- Feature intermediates rebuild within a transaction; corrections propagate on rerun.
- DQ failure stops the pipeline, but earlier committed stages remain inspectable.
- Export refuses an existing destination and only publishes a complete folder.
- Tests create a unique temporary database and never truncate the live warehouse.

## Time semantics and limitations

The reconstructed history cutoff is kickoff minus a three-hour completion buffer.
It does not certify when an old API result was published or later corrected.
Observed enrichments require observation time < kickoff plus validity bounds.
No current roster, coach or valuation is retrospectively assigned to old games.
Fixed T-24h snapshots, historical injuries/line-ups, cloud infrastructure and a
trained classifier remain outside the implemented midterm scope.

Original architecture diagrams describe the initial implementation.
This document and the README diagram describe the current data product.

Stadium requests commit independently and retry transient failures up to three
times; a rerun resumes missing clubs after a partial outage. Forecast requests
also retry transient failures up to three times. Permanent API errors are not retried.
