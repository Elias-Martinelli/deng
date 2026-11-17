-- fact_match from staging_matches. BigQuery port of sql/transform/220_fact_match.sql.
--
-- is_upcoming: from the kick-off time against @pipeline_now - the pipeline's
-- clock (deng.clock): the wall clock, or the replayed moment of a sample run,
-- as meta.pipeline_now() is in PostgreSQL. Not from `status`, whose vocabulary
-- mixes SCHEDULED and TIMED.
--
-- outcome: computed from the goals, so the label always matches the numbers
-- in the same row. NULL (not a draw) before the match.
--
-- Only matches whose two clubs are in dim_team: PostgreSQL enforces that with
-- a foreign key, BigQuery does not, so the filter keeps the guarantee and the
-- verification query reports what it dropped.
--
-- Parameter: @pipeline_now (TIMESTAMP).

MERGE `{{project}}.{{dataset}}.fact_match` AS target
USING (
    SELECT
        m.match_id,
        m.season_id,
        m.utc_kickoff,
        -- The UTC calendar day, explicitly - independent of any session time zone.
        DATE(m.utc_kickoff, 'UTC') AS match_date,
        m.stage,
        m.matchday,
        m.status,
        m.status = 'FINISHED' AS is_finished,
        m.status != 'FINISHED' AND m.utc_kickoff > @pipeline_now AS is_upcoming,
        m.home_team_id,
        m.away_team_id,
        m.home_goals,
        m.away_goals,
        m.home_goals - m.away_goals AS goal_difference,   -- NULL if either is NULL
        CASE
            WHEN m.home_goals IS NULL OR m.away_goals IS NULL THEN NULL
            WHEN m.home_goals > m.away_goals THEN 'HOME_WIN'
            WHEN m.home_goals < m.away_goals THEN 'AWAY_WIN'
            ELSE 'DRAW'
        END AS outcome
    FROM `{{project}}.{{dataset}}.staging_matches` AS m
    WHERE m.home_team_id IN (SELECT team_id FROM `{{project}}.{{dataset}}.dim_team`)
      AND m.away_team_id IN (SELECT team_id FROM `{{project}}.{{dataset}}.dim_team`)
) AS source
ON target.match_id = source.match_id
WHEN MATCHED THEN UPDATE SET
    season_id = source.season_id,
    utc_kickoff = source.utc_kickoff,
    match_date = source.match_date,
    stage = source.stage,
    matchday = source.matchday,
    status = source.status,
    is_finished = source.is_finished,
    is_upcoming = source.is_upcoming,
    home_team_id = source.home_team_id,
    away_team_id = source.away_team_id,
    home_goals = source.home_goals,
    away_goals = source.away_goals,
    goal_difference = source.goal_difference,
    outcome = source.outcome,
    updated_at = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN INSERT (
    match_id, season_id, utc_kickoff, match_date, stage, matchday, status,
    is_finished, is_upcoming, home_team_id, away_team_id, home_goals, away_goals,
    goal_difference, outcome, updated_at
) VALUES (
    source.match_id, source.season_id, source.utc_kickoff, source.match_date, source.stage,
    source.matchday, source.status, source.is_finished, source.is_upcoming,
    source.home_team_id, source.away_team_id, source.home_goals, source.away_goals,
    source.goal_difference, source.outcome, CURRENT_TIMESTAMP()
);
