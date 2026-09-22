-- fact_team_match_form: each team's form going into each match.
--
-- The point-in-time rule, and the reason this table exists at all: a row for
-- match M and team T may only use matches that were *finished before M's
-- kick-off*. Nothing from M itself, nothing from later. That is what makes the
-- table usable as ML features without leaking the result we want to predict.
--
-- Scope: Champions League matches only, for every club (ADR-004) - one
-- definition of form that is comparable across all 36. Early in a season that means
-- matches_considered is frequently 0 or 1 - which is precisely why the column
-- exists instead of silently presenting a 1-match form as "form".

WITH appearances AS (
    -- One row per team per match: a match seen from each side.
    SELECT match_id, utc_kickoff, is_finished,
           home_team_id AS team_id, away_team_id AS opponent_team_id, TRUE AS is_home,
           home_goals AS goals_for, away_goals AS goals_against
      FROM curated.fact_match
    UNION ALL
    SELECT match_id, utc_kickoff, is_finished,
           away_team_id, home_team_id, FALSE,
           away_goals, home_goals
      FROM curated.fact_match
)
INSERT INTO curated.fact_team_match_form AS f (
    match_id, team_id, is_home, opponent_team_id,
    matches_considered, wins_last_5, draws_last_5, losses_last_5,
    goals_scored_last_5, goals_conceded_last_5, goal_difference_last_5,
    points_last_5, days_since_last_match
)
SELECT
    a.match_id,
    a.team_id,
    a.is_home,
    a.opponent_team_id,
    COALESCE(w.matches_considered, 0),
    COALESCE(w.wins, 0),
    COALESCE(w.draws, 0),
    COALESCE(w.losses, 0),
    COALESCE(w.goals_for, 0),
    COALESCE(w.goals_against, 0),
    COALESCE(w.goals_for, 0) - COALESCE(w.goals_against, 0),
    COALESCE(w.wins, 0) * 3 + COALESCE(w.draws, 0),
    CASE WHEN w.last_kickoff IS NOT NULL
         THEN EXTRACT(DAY FROM a.utc_kickoff - w.last_kickoff)::int END
FROM appearances a
LEFT JOIN LATERAL (
    SELECT
        count(*)                                                        AS matches_considered,
        count(*) FILTER (WHERE p.goals_for > p.goals_against)           AS wins,
        count(*) FILTER (WHERE p.goals_for = p.goals_against)           AS draws,
        count(*) FILTER (WHERE p.goals_for < p.goals_against)           AS losses,
        sum(p.goals_for)                                                AS goals_for,
        sum(p.goals_against)                                            AS goals_against,
        max(p.utc_kickoff)                                              AS last_kickoff
    FROM (
        SELECT prior.goals_for, prior.goals_against, prior.utc_kickoff
          FROM appearances prior
         WHERE prior.team_id = a.team_id
           AND prior.is_finished
           -- strictly before this match: the leakage guard
           AND prior.utc_kickoff < a.utc_kickoff
           AND prior.goals_for IS NOT NULL
           AND prior.goals_against IS NOT NULL
         ORDER BY prior.utc_kickoff DESC
         LIMIT 5
    ) AS p
) AS w ON TRUE
ON CONFLICT (match_id, team_id) DO UPDATE SET
    is_home = EXCLUDED.is_home,
    opponent_team_id = EXCLUDED.opponent_team_id,
    matches_considered = EXCLUDED.matches_considered,
    wins_last_5 = EXCLUDED.wins_last_5,
    draws_last_5 = EXCLUDED.draws_last_5,
    losses_last_5 = EXCLUDED.losses_last_5,
    goals_scored_last_5 = EXCLUDED.goals_scored_last_5,
    goals_conceded_last_5 = EXCLUDED.goals_conceded_last_5,
    goal_difference_last_5 = EXCLUDED.goal_difference_last_5,
    points_last_5 = EXCLUDED.points_last_5,
    days_since_last_match = EXCLUDED.days_since_last_match,
    computed_at = now();
