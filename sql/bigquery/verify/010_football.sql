-- Verification and data-quality checks on the BigQuery tables (backlog 7.5,
-- 10.4). The same promises PostgreSQL keeps with constraints, which BigQuery
-- does not enforce: unique keys, home != away, a finished match has a score,
-- every fact's clubs are in dim_team - checked here instead.
--
-- Convention (src/deng/warehouse/bigquery.py): one row per check with the
-- number of violating rows in `failures`; any value above 0 fails the command.
-- Parameter: @logical_date (DATE).

SELECT 'raw_answers_present_for_the_day' AS check_name,
       IF(COUNT(*) = 0, 1, 0) AS failures
  FROM `{{project}}.{{dataset}}.raw_answers`
 WHERE source IN ('football-data.org', 'football-data.org-sample')
   AND ingestion_date = @logical_date

UNION ALL
SELECT 'staging_matches_unique_match_id', COUNT(*) - COUNT(DISTINCT match_id)
  FROM `{{project}}.{{dataset}}.staging_matches`

UNION ALL
SELECT 'fact_match_not_empty', IF(COUNT(*) = 0, 1, 0)
  FROM `{{project}}.{{dataset}}.fact_match`

UNION ALL
SELECT 'fact_match_unique_match_id', COUNT(*) - COUNT(DISTINCT match_id)
  FROM `{{project}}.{{dataset}}.fact_match`

UNION ALL
SELECT 'fact_match_home_differs_from_away', COUNTIF(home_team_id = away_team_id)
  FROM `{{project}}.{{dataset}}.fact_match`

UNION ALL
SELECT 'fact_match_finished_has_score',
       COUNTIF(is_finished AND (home_goals IS NULL OR away_goals IS NULL))
  FROM `{{project}}.{{dataset}}.fact_match`

UNION ALL
SELECT 'fact_match_goals_plausible',
       COUNTIF(home_goals NOT BETWEEN 0 AND 20 OR away_goals NOT BETWEEN 0 AND 20)
  FROM `{{project}}.{{dataset}}.fact_match`

UNION ALL
SELECT 'fact_match_outcome_matches_goals',
       COUNTIF(outcome IS DISTINCT FROM CASE
                   WHEN home_goals IS NULL OR away_goals IS NULL THEN NULL
                   WHEN home_goals > away_goals THEN 'HOME_WIN'
                   WHEN home_goals < away_goals THEN 'AWAY_WIN'
                   ELSE 'DRAW' END)
  FROM `{{project}}.{{dataset}}.fact_match`

UNION ALL
SELECT 'fact_match_clubs_in_dim_team', COUNT(*)
  FROM `{{project}}.{{dataset}}.fact_match` AS f
  LEFT JOIN `{{project}}.{{dataset}}.dim_team` AS h ON h.team_id = f.home_team_id
  LEFT JOIN `{{project}}.{{dataset}}.dim_team` AS a ON a.team_id = f.away_team_id
 WHERE h.team_id IS NULL OR a.team_id IS NULL

-- Every staged match whose clubs are known reached the fact table: a MERGE
-- that silently skipped rows would show up here.
UNION ALL
SELECT 'fact_match_covers_staging', COUNT(*)
  FROM `{{project}}.{{dataset}}.staging_matches` AS m
 WHERE m.home_team_id IN (SELECT team_id FROM `{{project}}.{{dataset}}.dim_team`)
   AND m.away_team_id IN (SELECT team_id FROM `{{project}}.{{dataset}}.dim_team`)
   AND m.match_id NOT IN (SELECT match_id FROM `{{project}}.{{dataset}}.fact_match`)
