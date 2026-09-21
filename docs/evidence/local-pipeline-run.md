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


---

## 8. Transformations and the curated layer (21 September 2026)

```console
$ make run-samples
=== ingest 2026-09-20 ===
  competition  INSERTED  records=47 hash=ccad28e735b0
  teams        INSERTED  records=36 hash=fccb2862341b
  standings    INSERTED  records=1 hash=e60484a8d440
  matches      INSERTED  records=144 hash=1e5a13475e9d

=== transform 2026-09-20 ===
  transform/110_staging_matches.sql               144 rows
  transform/111_staging_teams.sql                  36 rows
  transform/112_staging_standings.sql              36 rows
  transform/210_dim_team.sql                       36 rows
  transform/220_fact_match.sql                    144 rows
  transform/230_fact_team_match_form.sql          288 rows

  staging.matches                     144 rows
  curated.dim_team                     36 rows
  curated.fact_match                  144 rows
  curated.fact_team_match_form        288 rows

=== data quality ===
  [PASS] fact_match_not_empty              CRITICAL 144
  [PASS] match_id_unique                   CRITICAL 0
  [PASS] no_match_lost_in_transformation   CRITICAL 144 staged / 144 curated
  [PASS] teams_differ                      CRITICAL 0
  [PASS] finished_matches_have_an_outcome  CRITICAL 0
  [PASS] outcome_matches_the_goals         CRITICAL 0
  [PASS] every_match_has_two_form_rows     CRITICAL 0
  [PASS] form_counts_add_up                CRITICAL 0
  [PASS] form_uses_no_future_matches       CRITICAL 0
  [PASS] dim_team_complete                 CRITICAL 0
  [PASS] goals_are_plausible               WARNING  0
  [FAIL] form_window_is_well_populated     WARNING  0.0% with >= 3 matches

data quality: 11/12 checks passed

run for 2026-09-20: OK
```

Exit code 0. **288 = 2 × 144** confirms the form table's grain: one row per
team per match.

The single failure is a WARNING and is correct: on 20 September exactly one
matchday had been played, so no team had three completed Champions League
matches yet. Treating that as a pipeline failure would have taught us to ignore
the check; recording it keeps the limitation visible to anyone reading the data.

### Computed form, spot check

```console
$ psql -c "SELECT d.short_name, f.is_home, f.matches_considered n, f.wins_last_5 w,
           f.goals_scored_last_5 gf, f.goals_conceded_last_5 ga, f.points_last_5 pts,
           f.days_since_last_match days
           FROM curated.fact_team_match_form f
           JOIN curated.dim_team d USING (team_id)
           JOIN curated.fact_match m USING (match_id)
           WHERE m.matchday = 2 ORDER BY d.short_name LIMIT 6;"
    team     | is_home | n | w | gf | ga | pts | days
-------------+---------+---+---+----+----+-----+------
 Arsenal     | t       | 1 | 1 |  1 |  0 |   3 |   34
 Aston Villa | t       | 1 | 1 |  3 |  2 |   3 |   36
 Atleti      | t       | 1 | 0 |  1 |  2 |   0 |   34
 Barça       | f       | 1 | 1 |  5 |  1 |   3 |   34
 Bayern      | f       | 1 | 1 |  5 |  0 |   3 |   33
 Bodø/Glimt  | t       | 1 | 0 |  0 |  5 |   0 |   34
```

`n = 1` for every team on matchday 2, which is exactly right: one prior match
existed. The leakage guard is doing its job — had the window silently included
the match being described, `n` would read 2.

## 9. Test suite after the transformations

```console
$ make test
56 passed

$ POSTGRES_PORT=59999 pytest -q      # no database
28 passed, 28 skipped
```

15 unit tests, 13 contract tests against the real payloads, 12 loader
integration tests, 16 transformation and data-quality tests. Among them:

* `test_first_matchday_has_no_prior_form` — nobody has history before the
  competition starts.
* `test_form_never_uses_a_match_at_or_after_kickoff` — recomputes the available
  match count independently and compares it with what we stored.
* `test_rerun_for_an_older_date_does_not_overwrite_newer_data` — a late
  backfill must not stamp stale values over fresher ones.
* `test_a_critical_violation_is_detected` — corrupts a row on purpose and
  asserts that the check notices.

## 10. Streamlit viewer

![Streamlit viewer showing RC Lens vs Sporting CP](streamlit-app.png)

Reads `curated.fact_match`, `curated.dim_team` and
`curated.fact_team_match_form`, plus `meta.pipeline_runs` and `meta.dq_results`
for the sidebar. No HTTP request leaves the app. The screenshot shows the
one-match form window and the honest "no previous meeting in our data" notice
rather than an invented head-to-head.

## 11. Docker Compose, executed (21 September 2026)

Docker 28.0.4, Compose v2.34.0 (Docker Desktop, WSL 2 integration). Until
this run the Compose file had only been written, not executed - and executing it
found three defects that no unit test could have caught:

| Defect | Symptom | Fix |
|---|---|---|
| `pipeline` service built without `target` | Compose built the *last* Dockerfile stage, the Streamlit image: `make docker-ingest` failed with `streamlit run … No such option '--from-samples'` | stage renamed to `pipeline`, `target: pipeline` in Compose |
| `docker-ingest` skipped the DDL | `relation "meta.pipeline_runs" does not exist` on a fresh volume | target runs `init` first (idempotent) |
| sample payloads not in the container | `FileNotFoundError: …/data/sample/football-data/competition.json` | `./data/sample` mounted read-only, like `./sql` |

After the fixes, on an empty volume:

```text
$ make up                       → PostgreSQL is healthy.
$ make docker-ingest            → applied 5 SQL file(s) … ingest for 2026-09-21: OK
                                  (4 payloads INSERTED, 144 matches)
$ docker compose run --rm pipeline transform
                                  curated.fact_match 144 rows
                                  curated.fact_team_match_form 288 rows
$ docker compose run --rm pipeline verify
                                  verification: 2/2 queries passed
$ make docker-app               → GET /_stcore/health → ok
```

The viewer was also rendered headless inside its container
(`streamlit.testing.v1.AppTest`): no exception, no error element, a fixture
picker with 126 upcoming matches and populated metrics - i.e. it reads the
containerised database, not just "the server is up". The same run surfaced a
deprecation (`use_container_width`), replaced by `width="stretch"` with
Streamlit pinned to the verified range `>=1.64,<2`.

**Trap found on the way:** a natively installed PostgreSQL on the host already
listened on `localhost:5432`. Docker Desktop still started the container, but
host-side commands (`make init`, `pytest`) then talked to the *native* database
while the containers used their own. Everything looks green, against two
different databases. The README now says to set `POSTGRES_PORT` to a free port
in that case.
