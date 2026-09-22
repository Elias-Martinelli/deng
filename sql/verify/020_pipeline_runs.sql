-- Verification: did the pipeline actually run, and did it finish cleanly?
-- Reads meta.pipeline_runs, the run log every command writes (see run_log.py).

SELECT
    'at least one run recorded'                   AS check_name,
    count(*)::text                                AS observed,
    count(*) > 0                                  AS passed
FROM meta.pipeline_runs

UNION ALL

SELECT
    'latest run succeeded',
    coalesce(
        (SELECT status || ' at ' || coalesce(finished_at::text, 'still running')
           FROM meta.pipeline_runs ORDER BY started_at DESC LIMIT 1),
        'no runs'),
    coalesce((SELECT status = 'SUCCESS' FROM meta.pipeline_runs
               ORDER BY started_at DESC LIMIT 1), false)

UNION ALL

-- A run that was killed (container stopped, power loss) never reaches its
-- UPDATE to SUCCESS/FAILED and stays RUNNING. No daily run takes an hour, so
-- anything older than that is a crash that should be looked at.
SELECT
    'no run left hanging in RUNNING for over an hour',
    count(*)::text,
    count(*) = 0
FROM meta.pipeline_runs
WHERE status = 'RUNNING' AND started_at < now() - interval '1 hour';
