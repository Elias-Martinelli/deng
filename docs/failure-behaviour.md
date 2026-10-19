# Failure Behaviour

What the pipeline does when something goes wrong, case by case, and the test
that proves it. The rule behind every row: **a failure is visible, never
silent, and a rerun is always safe.** Visible means a `FAILED` row in
`meta.pipeline_runs` with the error message, a non-zero exit code for `make` and
CI, and a failed Dagster run. Safe means the raw load is an upsert and every
transformation is one transaction (see [Reruns](#reruns-after-a-failure)).

Two questions decide each row:

1. **Can the same request succeed later?** Then it is *transient* and retried:
   by the client a few seconds apart, then by Dagster's `TRANSIENT_RETRY` after
   1, 2 and 4 minutes. Otherwise it is *permanent* and fails at once, because
   repeating a 403 only spends the request budget.
2. **Does everything else rest on it?** The football data does, so its failure
   fails the run. Crests and odds are extras (`best_effort` in
   [`runner.py`](../src/deng/ingestion/runner.py)): their failure is recorded
   but the run goes on.

## The matrix

| # | What happens | Kind | Behaviour | Where | Proven by |
|---|---|---|---|---|---|
| 1 | **API down**: timeout, DNS, connection reset | transient | `RetryableApiError(0, …)`. The client tries 3 times, 6.5 s then 13 s apart. If it still fails, the day's partial writes are rolled back, the run row says `FAILED`, and Dagster retries after 1 → 2 → 4 min | [`football_data.py`](../src/deng/sources/football_data.py) `FootballDataClient.get`, `_get_with_retry` | `test_network_failure_is_retryable`, `test_run_step_lets_transient_errors_through_for_the_retry_policy` |
| 2 | **HTTP 429** rate limit, **5xx** server error | transient | as #1. The client also paces itself (6.5 s per request) and waits for the counter reset when `X-Requests-Available-Minute` ≤ 1, so a normal run never sees a 429 | `_pace`, `MIN_SECONDS_BETWEEN_REQUESTS` | `test_transient_errors_are_retryable`, `test_rate_limit_headers_tolerate_garbage` |
| 3 | **HTTP 400 / 403 / 404**: wrong key, competition not in the plan, bad path | permanent | `ApiError`, no retry at any level. Rolled back, run `FAILED`, Dagster `Failure(allow_retries=False)` | `FootballDataClient.get`, `run_step` | `test_client_errors_are_not_retryable`, `test_run_step_forbids_retries_for_permanent_errors`, `test_a_permanent_error_fails_the_run_without_retrying` |
| 4 | **Invalid JSON**: a 200 with an HTML proxy page or a truncated body | permanent | `ApiError`, not retried: a changed API or a proxy is something a person has to look at | football, Open-Meteo and The Odds API clients | `test_invalid_json_is_an_api_error`, `test_a_200_that_is_not_json_is_a_permanent_error`, `test_a_non_list_payload_is_rejected` |
| 5 | **Schema drift**: the answer is valid JSON, but a field the SQL reads is missing, null or of another type | permanent | `ContractError` (an `ApiError`) is raised **before** the write, listing every missing field (`matches[7] (id 575330).score.fullTime.home missing`). The day's earlier answers are rolled back, so the raw zone never holds a payload the transformation cannot read. New or missing *optional* fields pass | [`contracts.py`](../src/deng/sources/contracts.py), called in `football_data.ingest` and `open_meteo.ingest_weather` | `tests/test_contracts.py` (21 tests), incl. `test_drift_fails_the_run_and_stores_nothing_of_the_day`, `test_new_and_missing_optional_fields_are_tolerated`, `test_run_step_forbids_retries_for_schema_drift` |
| 6 | **No football API key** | configuration | `ERROR: FOOTBALL_DATA_API_KEY is not set` plus the hint to use `--from-samples`; exit 1, no traceback. In Dagster the run fails without retry | `Settings.require_football_api_key`, `pipeline.command_ingest` | `test_missing_api_key_gives_actionable_error` |
| 7 | **PostgreSQL down** or restarting | transient | `psycopg.OperationalError`. Nothing is written, so nothing is half-written. The CLI exits 1; Dagster retries after 1 → 2 → 4 min, which covers a database container that is still starting | `TRANSIENT_ERRORS` in [`definitions.py`](../src/deng/orchestration/definitions.py) | `test_run_step_lets_a_database_outage_through_for_the_retry_policy` |
| 8 | **Process killed** mid-run (container stopped, power loss) | — | The run row was committed as `RUNNING` before any work, and the data was not committed yet, so it stays `RUNNING`. `make verify` flags any run left in `RUNNING` for over an hour. Rerunning the date is safe (#13) | [`run_log.py`](../src/deng/database/run_log.py), [`sql/verify/020_pipeline_runs.sql`](../sql/verify/020_pipeline_runs.sql) | `make verify` check *no run left hanging in RUNNING for over an hour* |
| 9 | **Weather missing** | expected | Never an error, always a stated reason per match in `curated.fact_match_weather.weather_status`: `NOT_YET_AVAILABLE` (beyond the 16-day horizon, never asked), `NOT_CAPTURED` (match already played, a forecast cannot be fetched afterwards), `VENUE_UNKNOWN` (no verified stadium). A backfill for a past date fetches no weather and says so | [`330_fact_match_weather.sql`](../sql/transform/330_fact_match_weather.sql), `ingest_weather` | `test_every_match_gets_exactly_one_status`, `test_no_forecast_for_a_past_logical_date`, `test_a_forecast_fetched_after_kickoff_is_never_used` |
| 10 | **Open-Meteo refuses a request** (400 out of range) | permanent | `ApiError`; the weather step fails the run, because it means our horizon arithmetic is wrong, which is a bug in our code | `fetch_forecast` | `test_out_of_range_is_a_permanent_error` |
| 11 | **Stadium not found** on OpenStreetMap | expected | Stored as `NOT_AVAILABLE` with the reason (no result, no venue name, manually excluded). The club gets `VENUE_UNKNOWN` weather and a WARNING check. A guessed location would be worse than a gap | `openstreetmap._resolve` | data-quality check `every_team_has_a_venue_row` |
| 12 | **Crest download fails** | best effort | Counted, logged, run continues; the viewer shows the three-letter code instead. The next run fetches only what is still missing. A non-image or a file over 1 MB is refused | [`club_crests.py`](../src/deng/sources/club_crests.py) | `test_stores_images_and_survives_a_bad_answer`; check `every_team_has_a_crest` (WARNING) |
| 13 | **Odds: no key, quota exhausted, invalid key** | best effort | No key: the step skips itself and says so. Near the quota reserve: fetching pauses except one probe a day. A 401 (bad key *or* exhausted quota, the API does not distinguish) is recorded as failed, the run continues | [`the_odds_api.py`](../src/deng/sources/the_odds_api.py) `plan_fetch` | `test_without_a_key_the_step_skips_and_says_so`, `test_the_quota_reserve_pauses_fetching_and_keeps_the_last_state`, `test_an_exhausted_quota_or_bad_key_is_a_permanent_error` |
| 14 | **A transformation statement fails** | permanent | Each chain (football, weather, odds) is one transaction: rolled back as a whole, the curated tables keep yesterday's complete state, run `FAILED` | [`transformation/runner.py`](../src/deng/transformation/runner.py) | `test_transformation_is_idempotent` (the same transaction boundary); no test injects a broken statement |
| 15 | **A CRITICAL data-quality check fails** | permanent | Results are persisted to `meta.dq_results` first, then `make run` / `make dq` exits 1 and the Dagster run fails without retry. A WARNING is recorded and shown, nothing more | [`quality/checks.py`](../src/deng/quality/checks.py) | `test_a_critical_violation_is_detected`, `test_run_step_fails_on_a_non_zero_exit_code` |

## Reruns after a failure

Every row above ends the same way: fix the cause, then rerun the same date.

* **Raw zone:** an upsert on `(source, endpoint, request_params, ingestion_date)`.
  A second run on the same day updates the row, it does not add one
  (`test_second_run_same_day_does_not_duplicate`).
* **Staging and curated:** upserts that never overwrite newer data with older
  (`test_rerun_for_an_older_date_does_not_overwrite_newer_data`).
* **Backfill:** one date at a time; a failing date is counted and the range goes
  on (`command_backfill`), so one bad day cannot block nine good ones.

## What is not covered

* **Schema drift in the side sources.** The contracts cover football-data.org
  (every endpoint) and Open-Meteo. The Odds API is best effort and its payload
  is only checked to be a list. OpenStreetMap answers are stored as-is and
  judged by the venue checks.
* **A failure inside one transformation statement is not injected by a test**
  (#14). The transaction boundary is tested by the idempotency tests, not by
  breaking a statement on purpose.
* **Alerting.** A failure is visible in the run log, the exit code and the
  Dagster UI, but nobody is notified. For a daily batch with a person looking
  at it, that is enough; in the cloud version a failed run should page.
