-- Verification: does the raw zone contain what a successful run should produce?
--
-- Convention: every verification query exposes a boolean column `passed`.
-- `python -m deng.pipeline verify` fails when any row reports false.

SELECT
    'raw payloads present'                        AS check_name,
    count(*)::text                                AS observed,
    count(*) > 0                                  AS passed
FROM raw.football_data

UNION ALL

SELECT
    'all four daily endpoints ingested today',
    string_agg(DISTINCT endpoint, ', ' ORDER BY endpoint),
    count(DISTINCT endpoint) >= 4
FROM raw.football_data
WHERE ingestion_date = (SELECT max(ingestion_date) FROM raw.football_data)

UNION ALL

SELECT
    'no duplicate business keys',
    count(*)::text,
    count(*) = 0
FROM (
    SELECT source, endpoint, request_params, ingestion_date
    FROM raw.football_data
    GROUP BY 1, 2, 3, 4
    HAVING count(*) > 1
) AS duplicates

UNION ALL

SELECT
    'match payload carries matches',
    coalesce(max(record_count)::text, 'none'),
    coalesce(max(record_count), 0) > 0
FROM raw.football_data
WHERE endpoint LIKE '%/matches'

UNION ALL

SELECT
    'every raw row belongs to a known run',
    count(*)::text,
    count(*) = 0
FROM raw.football_data r
LEFT JOIN meta.pipeline_runs p USING (run_id)
WHERE p.run_id IS NULL;
