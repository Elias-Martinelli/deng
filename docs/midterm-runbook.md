# Midterm runbook

## Updated demonstration — 15 October 2026

Use the latest training-ready-2026-10-15 export. Show 143 matches with real odds across eight competitions, the single remaining horizon weather gap, and the chronological baseline evaluation. Explain the two DQ warnings and why suspicious quotes are excluded. See [current coverage and limitations](training-data-gaps.md) and [baseline](model-baseline.md).

## Demonstration sequence

1. Explain the end user: a data scientist needs one row per match to predict the
   90-minute result. The deliverable is the pipeline and dataset.
2. Show raw API payloads with source, request parameters, hash and receipt time.
3. Show staging types/deduplication and the one-match grain.
4. Open Curated Dataset. Filter leagues, show 292 columns, labels, history sizes
   and missing squad/value/weather fields.
5. Explain three-hour history availability and why today's coach cannot label 2023.
6. Run tests, DQ and export; show the dictionary, coverage and checksum.
7. Explain how daily schedules, retries, historical caching and reruns work.

## Run without API keys

```bash
./setup.sh
make up
make init
make run-samples
make test
make lint
make verify
make export
```

Expect 144 sample fixtures. Use a separate demo database if live data already
exists. For scheduled samples set INGEST_SOURCE=samples and
FOOTBALL_DATA_COMPETITIONS=CL in the demonstration environment, then
`make orchestrator`. The schedule is 06:00 Europe/Zurich.

## Live multi-league run

Configure the eight competition codes and historical years from README.
`make dataset` produces the large football-derived training product.
`make run` additionally refreshes optional sources according to configuration.
It may report warnings for unavailable weather/venues/crests. All critical
checks must pass. No historical market value is claimed without source evidence.

## Questions both students should answer

- Why store raw responses? Rebuild and inspect without spending API requests again.
- Why full current reload but cached history? Small bounded current endpoints
  change; completed seasons rarely change and can be explicitly refreshed.
- Why not join the final standings? They contain the target match and later games.
- Why separate targets and inputs? Goals/labels would leak the answer.
- Why is a historical squad often empty? Today's observation was not known then.
- What does missing rest coverage mean? Cups or unconfigured competitions may be absent.
- What happens after a failed source? The run records failure; core errors prevent transform.
- Does failed DQ roll back everything? No, it fails the run; prior stage commits remain.
- How do you prove reruns are safe? Key constraints, regression tests and stable row counts.
- Why is PostgreSQL sufficient now? Measured local volume; cloud is a later milestone.
- How is the data scientist protected? A documented target, feature list, temporal rules
  and coverage report, plus chronological evaluation guidance.

## Remaining human and final-milestone work

Independent peer reproduction, oral rehearsal by both students, meaningful
individual contributions and submission of repository/commit via ILIAS remain.
The existing rubric records the midterm deadline as 22 October 2026 at 15:30;
confirm course announcements. No submission/tag/push was performed automatically.
GCS, BigQuery, Terraform and fixed-horizon snapshot training data remain final work.

## Existing local PostgreSQL versus Docker

A machine can already run PostgreSQL in WSL while Docker Desktop exposes
another instance. Confirm the configured host/port before comparing counts.
CLI runs use .env's connection; Compose services use the postgres service on the
container network. The container smoke test creates its own temporary database.
Do not assume two databases with the same name contain the same data.
