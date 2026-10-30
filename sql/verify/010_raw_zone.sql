-- Verification: does the raw zone contain what a successful run should produce?
--
-- Convention: every verification query exposes a boolean column `passed`.
-- `python -m deng.pipeline verify` fails when any row reports false.
--
-- One query, several checks glued with UNION ALL: each SELECT returns one row
-- (check_name, observed, passed), so the output reads like a checklist. These
-- files run without bound parameters, hence a single % in LIKE here - unlike
-- the transformation files, which need %%.
--
-- Difference to the data-quality checks: those judge the *curated* data after
-- every run; these let a reviewer confirm by hand that the *ingestion* worked.

SELECT
    'raw payloads present'                        AS check_name,
    count(*)::text                                AS observed,
    count(*) > 0                                  AS passed
FROM raw.football_data

UNION ALL

-- Every observed competition has all four current endpoints on the latest day.
SELECT
    'four current endpoints per competition',
    count(*)::text || ' complete competition/source groups',
    count(*) > 0 AND bool_and(endpoint_count = 4)
FROM (
    SELECT source, split_part(endpoint, '/', 2) AS competition,
           count(DISTINCT endpoint) AS endpoint_count
    FROM raw.football_data
    WHERE ingestion_date = (SELECT max(ingestion_date) FROM raw.football_data)
      AND request_params = '{}'::jsonb
      AND endpoint ~ '^competitions/[^/]+(/teams|/matches|/standings)?$'
    GROUP BY source, split_part(endpoint, '/', 2)
) latest_competitions

UNION ALL

-- The idempotency claim, measured: no business key appears twice. The UNIQUE
-- constraint makes this impossible; the check proves the constraint exists.
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

-- Lineage: every payload can be traced to the run that wrote it (anti-join via
-- LEFT JOIN ... IS NULL counts orphans).
SELECT
    'every raw row belongs to a known run',
    count(*)::text,
    count(*) = 0
FROM raw.football_data r
LEFT JOIN meta.pipeline_runs p USING (run_id)
WHERE p.run_id IS NULL;
