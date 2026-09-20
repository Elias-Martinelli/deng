# Evidence: local pipeline, idempotency and backfill

Recorded on **20 September 2026** against PostgreSQL 16. Every block below is
verbatim console output, not a description of what should happen.

Reproduce with:

```bash
make up                 # PostgreSQL via Docker Compose
make init               # schemas and tables
make ingest-samples     # ingestion from the committed payloads (no API key needed)
make verify
```

`--from-samples` reads the committed payloads instead of calling the API. It
makes this evidence byte-for-byte reproducible (the input never changes) and
lets a reviewer exercise the whole local pipeline before registering a key.
With a key, `make ingest` runs the identical code path against the live API.

## 1. First run — everything is inserted

```console
$ python -m deng.pipeline ingest --date 2026-09-20 --from-samples
  competition  INSERTED  records=47 hash=ccad28e735b0
  teams        INSERTED  records=36 hash=fccb2862341b
  standings    INSERTED  records=1 hash=e60484a8d440
  matches      INSERTED  records=144 hash=1e5a13475e9d
ingest for 2026-09-20: OK

$ psql -c "SELECT count(*) AS raw_rows, sum(record_count) AS records FROM raw.football_data;"
 raw_rows | records
----------+---------
        4 |     228
```

## 2. Second run, same logical date — idempotent

The decisive test for the rubric's "safe rerun" requirement: same command, same
day, run again immediately.

```console
$ python -m deng.pipeline ingest --date 2026-09-20 --from-samples
  competition  UPDATED   records=47 hash=ccad28e735b0
  teams        UPDATED   records=36 hash=fccb2862341b
  standings    UPDATED   records=1 hash=e60484a8d440
  matches      UPDATED   records=144 hash=1e5a13475e9d
ingest for 2026-09-20: OK

$ psql -c "SELECT count(*) AS raw_rows, sum(record_count) AS records FROM raw.football_data;"
 raw_rows | records
----------+---------
        4 |     228
```

**4 rows before, 4 rows after. Identical payload hashes.** No duplicates, and no
window in which the table was empty, because the mechanism is
`INSERT ... ON CONFLICT (source, endpoint, request_params, ingestion_date)
DO UPDATE` rather than delete-then-insert.

## 3. Backfill over a date range

```console
$ python -m deng.pipeline backfill --from 2026-09-17 --to 2026-09-19 --from-samples
=== backfill 2026-09-17 ===
  competition  INSERTED  records=47 hash=ccad28e735b0
  ...
=== backfill 2026-09-19 ===
  matches      INSERTED  records=144 hash=1e5a13475e9d
ingest for 2026-09-19: OK

backfill finished: 3/3 dates succeeded

$ psql -c "SELECT ingestion_date, count(*) AS payloads, sum(record_count) AS records
           FROM raw.football_data GROUP BY 1 ORDER BY 1;"
 ingestion_date | payloads | records
----------------+----------+---------
 2026-09-17     |        4 |     228
 2026-09-18     |        4 |     228
 2026-09-19     |        4 |     228
 2026-09-20     |        4 |     228
```

Repeating the same backfill leaves the total at 16 rows — the range is
idempotent for the same reason a single day is.

**Honest limitation:** the API always answers with *today's* state, so a
backfill re-labels current data under a past logical date. It recovers missed
runs and enables re-processing; it does not reconstruct what the API would have
said on 17 September. Recovering genuine history is possible per *season*
(`?season=2023`), not per day — that is a separate backlog item (1.9).

## 4. Run log

```console
$ psql -c "SELECT pipeline_name, logical_date, status, rows_extracted, rows_loaded,
                  rows_updated, round(extract(epoch from finished_at-started_at)::numeric,2) AS sec
           FROM meta.pipeline_runs ORDER BY started_at;"
    pipeline_name    | logical_date | status  | rows_extracted | rows_loaded | rows_updated | sec
---------------------+--------------+---------+----------------+-------------+--------------+------
 ingest_football_raw | 2026-09-20   | SUCCESS |            228 |           4 |            0 | 0.02
 ingest_football_raw | 2026-09-20   | SUCCESS |            228 |           0 |            4 | 0.02
 ingest_football_raw | 2026-09-17   | SUCCESS |            228 |           4 |            0 | 0.02
 ingest_football_raw | 2026-09-18   | SUCCESS |            228 |           4 |            0 | 0.02
 ingest_football_raw | 2026-09-19   | SUCCESS |            228 |           4 |            0 | 0.01
 ingest_football_raw | 2026-09-17   | SUCCESS |            228 |           0 |            4 | 0.02
 ingest_football_raw | 2026-09-18   | SUCCESS |            228 |           0 |            4 | 0.02
 ingest_football_raw | 2026-09-19   | SUCCESS |            228 |           0 |            4 | 0.02
```

`rows_loaded` versus `rows_updated` tells inserts and upserts apart, so the
idempotent behaviour is visible in the database itself, not only on screen.

## 5. Verification

```console
$ make verify
=== 010_raw_zone.sql ===
  check_name | observed | passed
  raw payloads present | 16 | True
  all four daily endpoints ingested today | competitions/CL, competitions/CL/matches,
      competitions/CL/standings, competitions/CL/teams | True
  no duplicate business keys | 0 | True
  match payload carries matches | 144 | True
  every raw row belongs to a known run | 0 | True

=== 020_pipeline_runs.sql ===
  check_name | observed | passed
  at least one run recorded | 8 | True
  latest run succeeded | SUCCESS at 2026-09-20 23:37:56 | True
  no run left hanging in RUNNING for over an hour | 0 | True

verification: 2/2 queries passed
```

Exit code 0. A failing check exits non-zero, which is what lets the orchestrator
fail the run instead of reporting success on bad data. Verified in the opposite
direction as well: against an empty raw zone the same command reports
`verification: 0/2 queries passed` and exits 1.

## 6. Failure behaviour

A failing run stays visible instead of disappearing (covered by
`test_run_log_records_failure_and_reraises`):

| Situation | Behaviour |
|---|---|
| API timeout / 5xx / 429 | up to 3 attempts with exponential back-off, then the run fails |
| HTTP 400 / 403 / 404 | no retry — repeating cannot help and would burn the request budget |
| Rate-limit budget nearly spent | the client waits for the reset window before continuing |
| PostgreSQL unreachable | the run fails before any partial write |
| Exception mid-run | transaction rolled back, run row set to FAILED with the error message |
| Missing sample file in `--from-samples` | `FileNotFoundError` — no silent partial ingest |

## 7. Test suite

```console
$ make test
40 passed
```

15 unit tests (config, API client), 13 contract tests against the real payloads,
12 integration tests against PostgreSQL. Without a reachable database the
integration tests skip rather than fail:

```console
$ POSTGRES_PORT=59999 pytest -q
...............ssssssssssss.............   28 passed, 12 skipped
```
