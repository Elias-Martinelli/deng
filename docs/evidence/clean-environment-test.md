# Evidence: clean-environment reproducibility test

Recorded on **18 October 2026** in a fresh Linux container (Python 3.13,
Docker 29.8, no project state, no API keys) by following the README top to
bottom, the way a peer reviewer would (§2.6 of the project description). Commit
under test: `992e47f`, then `7eca786` with the two fixes below.

## Result per step

| Step (README order) | Result | Note |
|---|---|---|
| `git clone` + `./setup.sh` | PASS | picked Python 3.13, `Ready. 2 warning(s).` (no API keys) |
| `make doctor` | PASS | `Ready.` |
| `make test` without PostgreSQL | PASS | 77 passed, 51 skipped; 128 collected, because the orchestration module skips as one item without the extra |
| `make up` | PASS | `PostgreSQL is healthy.` |
| `make init` | PASS | 11 SQL files applied |
| `make run-samples` | PASS | `run for 2026-10-18: OK`, `data quality: 21/24 checks passed`, exit 0 |
| `make run-samples` again | PASS | raw and curated row counts unchanged (idempotent) |
| `make verify` | PASS | `verification: 3/3 queries passed` |
| `make docker-ingest` | PASS | `ingest for 2026-10-18: OK` inside the pipeline image |
| `make orchestrator` | PASS | postgres, dagster-webserver and dagster-daemon healthy, UI answers on :3000 |
| `make dagster-backfill FROM=2026-10-15 TO=2026-10-16` | **FAIL → fixed** | see finding 1 |
| `make setup-orchestrator` + `make test` with PostgreSQL | **FAIL → fixed** | 134 passed, 3 failed; see finding 2. After the fix: `137 passed` |
| `make lint` | PASS | exit 0 |

## Findings

**1. Dagster could not launch any run (code, fixed in `7eca786`).** A fresh
install resolves SQLAlchemy 2.1, which maps `postgresql://` to psycopg 3
instead of psycopg2. dagster-postgres then fails on its own
`NOTIFY run_events, %(notify_id)s` with `syntax error at or near "$1"`, so every
run launch, the backfill included, failed. The September evidence still passed
on SQLAlchemy 2.0. The orchestrator extra now pins `sqlalchemy>=2.0,<2.1`.
After the pin, both backfill partitions finished `SUCCESS` with
`INGEST_SOURCE=samples`. Without that setting they fail cleanly with
`FOOTBALL_DATA_API_KEY is not set`, as the README says.

**2. Three integration tests depended on today's date (code, fixed in
`18b90a4`).** The weather fixture's forecasts were stamped `now()` while its
matches kick off on 13/14 October, so after that date the leakage guard rightly
discarded them. The odds test asserted `is_pre_match is True`, which holds only
before match 575341 kicks off. CI on `main` turned red on 18 October for this
reason alone. The tests now stamp the fetch with the logical date and compare
the flag against the kick-off.

**3. The sample run is not fully offline (documentation or code, open).**
`make run-samples` still downloads crests from `crests.football-data.org`.
Without that host, all 36 fail and `every_team_has_a_crest` turns into a
WARNING. The README says the whole sample path works offline.

**4. The expected data-quality count depends on the date (documentation,
open).** The README expects `23/24` with the current season. On 18 October the
sample run gives `21/24`: the crest WARNING (finding 3) and
`no_forecast_missing_inside_horizon`, because 17 upcoming matches fall inside
the 16-day horizon but only one sample forecast exists. Both are WARNINGs, so
the exit code stays 0.

**5. Known and documented:** `make test` empties the pipeline tables, so run
`make run-samples` again after it.

## Environment-specific, not a repository problem

This container reaches the internet through a TLS-inspecting proxy, so
`docker build` first failed to verify pypi.org. The images were built with the
proxy's CA injected through a local copy of the Dockerfile that was not
committed. On a normal network the unchanged Dockerfile applies.

## Follow-up, 19 October 2026

The two open documentation findings are fixed in the README:

* **Finding 3 (crests):** the README no longer says the sample path works
  offline. *Local Development* now says that crests are the one part that
  needs the network, what happens without it (36 failed, run still `OK`,
  WARNING `every_team_has_a_crest`), and that the next run fetches only the
  missing ones.
* **Finding 4 (expected DQ count):** *Verification* now gives the expected
  count per case: `22/24` with network, `21/24` offline. It also names the
  WARNING checks that fail on a sample run and why. The sample fixture list
  is from matchday 1, so `form_window_is_well_populated` always fails there.

Re-checked on 19 October in a fresh database (`make init`, `make run-samples`,
`make verify`), with crest downloads blocked by the network:
`data quality: 21/24 checks passed`, `run for 2026-10-19: OK`,
`verification: 3/3 queries passed`.
