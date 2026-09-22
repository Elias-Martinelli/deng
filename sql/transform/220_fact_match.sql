-- fact_match from staging.matches.
--
-- Two derivations that belong here rather than in staging:
--
-- is_upcoming: derived from the kick-off time, not from `status`. The source's
-- status vocabulary is unreliable for this purpose (?status=SCHEDULED returns
-- rows stored as TIMED), and a time comparison cannot drift with the API's
-- vocabulary.
--
-- outcome: HOME_WIN / DRAW / AWAY_WIN computed from the goals rather than
-- copied from score.winner, so the label is always consistent with the numbers
-- the same row carries.

INSERT INTO curated.fact_match AS f (
    match_id, season_id, utc_kickoff, match_date, stage, matchday, status,
    is_finished, is_upcoming, home_team_id, away_team_id,
    home_goals, away_goals, goal_difference, outcome
)
SELECT
    m.match_id,
    m.season_id,
    m.utc_kickoff,
    -- The UTC calendar day, explicitly: a bare ::date would use the session's
    -- time zone (UTC in the container, often Europe/Zurich on a laptop) and
    -- give a late kick-off a different date depending on where the job runs.
    (m.utc_kickoff AT TIME ZONE 'UTC')::date,
    m.stage,
    m.matchday,
    m.status,
    m.status = 'FINISHED',
    m.status <> 'FINISHED' AND m.utc_kickoff > now(),
    m.home_team_id,
    m.away_team_id,
    m.home_goals,
    m.away_goals,
    CASE WHEN m.home_goals IS NOT NULL AND m.away_goals IS NOT NULL
         THEN m.home_goals - m.away_goals END,
    CASE
        WHEN m.home_goals IS NULL OR m.away_goals IS NULL THEN NULL
        WHEN m.home_goals > m.away_goals THEN 'HOME_WIN'
        WHEN m.home_goals < m.away_goals THEN 'AWAY_WIN'
        ELSE 'DRAW'
    END
FROM staging.matches m
-- Referential integrity by construction: a match whose team is unknown to
-- dim_team would violate the foreign key. Filtering here turns that into a
-- reported gap (data-quality check) instead of an aborted run.
WHERE EXISTS (SELECT 1 FROM curated.dim_team d WHERE d.team_id = m.home_team_id)
  AND EXISTS (SELECT 1 FROM curated.dim_team d WHERE d.team_id = m.away_team_id)
ON CONFLICT (match_id) DO UPDATE SET
    season_id = EXCLUDED.season_id,
    utc_kickoff = EXCLUDED.utc_kickoff,
    match_date = EXCLUDED.match_date,
    stage = EXCLUDED.stage,
    matchday = EXCLUDED.matchday,
    status = EXCLUDED.status,
    is_finished = EXCLUDED.is_finished,
    is_upcoming = EXCLUDED.is_upcoming,
    home_goals = EXCLUDED.home_goals,
    away_goals = EXCLUDED.away_goals,
    goal_difference = EXCLUDED.goal_difference,
    outcome = EXCLUDED.outcome,
    updated_at = now();
