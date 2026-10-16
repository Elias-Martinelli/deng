-- Rebuild within the runner transaction, so corrections propagate and readers
-- see one consistent version. Two indexed rows per match replace repeated scans
-- of a UNION view. Bounded lookbacks, a 30-day workload range, and cumulative
-- history/season aggregates keep each feature extraction small.
TRUNCATE curated.team_match_features, curated.match_team_history;

INSERT INTO curated.match_team_history (
    match_id, team_id, opponent_team_id, competition_code, season_id, is_home,
    utc_kickoff, result_available_at, is_finished, goals_for, goals_against, points,
    completed_matches_to_date, first_completed_kickoff,
    season_matches_to_date, season_wins_to_date, season_draws_to_date, season_losses_to_date, season_points_to_date, season_goals_for_to_date, season_goals_against_to_date, season_goal_difference_to_date
)
WITH appearances AS (
    SELECT m.match_id, m.competition_code, m.season_id, m.utc_kickoff,
           m.status = 'FINISHED' AS is_finished, t.team_id, t.opponent_team_id,
           t.is_home, t.goals_for, t.goals_against,
           CASE WHEN t.goals_for > t.goals_against THEN 3
                WHEN t.goals_for = t.goals_against THEN 1
                WHEN t.goals_for < t.goals_against THEN 0 END AS points
      FROM staging.matches m
      JOIN curated.fact_match f USING (match_id)
      CROSS JOIN LATERAL (VALUES
          (m.home_team_id, m.away_team_id, true, m.home_goals_90min, m.away_goals_90min),
          (m.away_team_id, m.home_team_id, false, m.away_goals_90min, m.home_goals_90min)
      ) t(team_id, opponent_team_id, is_home, goals_for, goals_against)
)
SELECT match_id, team_id, opponent_team_id, competition_code, season_id, is_home,
       utc_kickoff, utc_kickoff + interval '3 hours', is_finished,
       goals_for, goals_against, points,
       count(*) FILTER (WHERE is_finished) OVER history_window,
       min(utc_kickoff) FILTER (WHERE is_finished) OVER history_window,
       count(*) FILTER (WHERE is_finished AND points IS NOT NULL) OVER season_window,
       count(*) FILTER (WHERE is_finished AND points = 3) OVER season_window,
       count(*) FILTER (WHERE is_finished AND points = 1) OVER season_window,
       count(*) FILTER (WHERE is_finished AND points = 0) OVER season_window,
       COALESCE(sum(points) FILTER (WHERE is_finished) OVER season_window, 0),
       COALESCE(sum(goals_for) FILTER (WHERE is_finished AND points IS NOT NULL) OVER season_window, 0),
       COALESCE(sum(goals_against) FILTER (WHERE is_finished AND points IS NOT NULL) OVER season_window, 0),
       COALESCE(sum(goals_for - goals_against) FILTER (WHERE is_finished AND points IS NOT NULL) OVER season_window, 0)
  FROM appearances
WINDOW history_window AS (PARTITION BY team_id ORDER BY utc_kickoff RANGE UNBOUNDED PRECEDING),
       season_window AS (PARTITION BY team_id, competition_code, season_id
                         ORDER BY utc_kickoff RANGE UNBOUNDED PRECEDING);

ANALYZE curated.match_team_history;

INSERT INTO curated.team_match_features (
    match_id, team_id,
    history_matches,
    history_first_kickoff,
    history_last_kickoff,
    history_last_available_at,
    rest_days,
    played_last_7_days,
    played_last_14_days,
    played_last_30_days,
    matches_last_3,
    wins_last_3,
    draws_last_3,
    losses_last_3,
    points_last_3,
    goals_for_last_3,
    goals_against_last_3,
    goal_difference_last_3,
    clean_sheets_last_3,
    failed_to_score_last_3,
    both_teams_scored_last_3,
    over_2_5_last_3,
    goals_for_per_match_last_3,
    goals_against_per_match_last_3,
    points_per_match_last_3,
    win_rate_last_3,
    matches_last_5,
    wins_last_5,
    draws_last_5,
    losses_last_5,
    points_last_5,
    goals_for_last_5,
    goals_against_last_5,
    goal_difference_last_5,
    clean_sheets_last_5,
    failed_to_score_last_5,
    both_teams_scored_last_5,
    over_2_5_last_5,
    goals_for_per_match_last_5,
    goals_against_per_match_last_5,
    points_per_match_last_5,
    win_rate_last_5,
    matches_last_10,
    wins_last_10,
    draws_last_10,
    losses_last_10,
    points_last_10,
    goals_for_last_10,
    goals_against_last_10,
    goal_difference_last_10,
    clean_sheets_last_10,
    failed_to_score_last_10,
    both_teams_scored_last_10,
    over_2_5_last_10,
    goals_for_per_match_last_10,
    goals_against_per_match_last_10,
    points_per_match_last_10,
    win_rate_last_10,
    venue_matches_last_5,
    venue_points_last_5,
    venue_wins_last_5,
    venue_goals_for_last_5,
    venue_goals_against_last_5,
    venue_clean_sheets_last_5,
    venue_points_per_match_last_5,
    competition_matches_last_5,
    competition_points_last_5,
    competition_wins_last_5,
    competition_goals_for_last_5,
    competition_goals_against_last_5,
    competition_clean_sheets_last_5,
    competition_points_per_match_last_5,
    season_matches,
    season_wins,
    season_draws,
    season_losses,
    season_points,
    season_goals_for,
    season_goals_against,
    season_goal_difference,
    season_points_per_match,
    h2h_matches_last_5,
    h2h_wins_last_5,
    h2h_draws_last_5,
    h2h_losses_last_5,
    h2h_points_last_5,
    h2h_goals_for_last_5,
    h2h_goals_against_last_5,
    h2h_points_per_match_last_5
)
SELECT a.match_id, a.team_id,
       COALESCE(h.completed_matches_to_date, 0),
       h.first_completed_kickoff, h.utc_kickoff, h.result_available_at,
       round(EXTRACT(epoch FROM a.utc_kickoff - h.utc_kickoff)::numeric / 86400, 3),
       load.played_last_7_days,
       load.played_last_14_days,
       load.played_last_30_days,
       form.matches_last_3,
       form.wins_last_3,
       form.draws_last_3,
       form.losses_last_3,
       form.points_last_3,
       form.goals_for_last_3,
       form.goals_against_last_3,
       form.goal_difference_last_3,
       form.clean_sheets_last_3,
       form.failed_to_score_last_3,
       form.both_teams_scored_last_3,
       form.over_2_5_last_3,
       form.goals_for_per_match_last_3,
       form.goals_against_per_match_last_3,
       form.points_per_match_last_3,
       form.win_rate_last_3,
       form.matches_last_5,
       form.wins_last_5,
       form.draws_last_5,
       form.losses_last_5,
       form.points_last_5,
       form.goals_for_last_5,
       form.goals_against_last_5,
       form.goal_difference_last_5,
       form.clean_sheets_last_5,
       form.failed_to_score_last_5,
       form.both_teams_scored_last_5,
       form.over_2_5_last_5,
       form.goals_for_per_match_last_5,
       form.goals_against_per_match_last_5,
       form.points_per_match_last_5,
       form.win_rate_last_5,
       form.matches_last_10,
       form.wins_last_10,
       form.draws_last_10,
       form.losses_last_10,
       form.points_last_10,
       form.goals_for_last_10,
       form.goals_against_last_10,
       form.goal_difference_last_10,
       form.clean_sheets_last_10,
       form.failed_to_score_last_10,
       form.both_teams_scored_last_10,
       form.over_2_5_last_10,
       form.goals_for_per_match_last_10,
       form.goals_against_per_match_last_10,
       form.points_per_match_last_10,
       form.win_rate_last_10,
       venue.matches,
       venue.points,
       venue.wins,
       venue.goals_for,
       venue.goals_against,
       venue.clean_sheets,
       venue.points_per_match,
       competition.matches,
       competition.points,
       competition.wins,
       competition.goals_for,
       competition.goals_against,
       competition.clean_sheets,
       competition.points_per_match,
       COALESCE(season.season_matches_to_date, 0),
       COALESCE(season.season_wins_to_date, 0),
       COALESCE(season.season_draws_to_date, 0),
       COALESCE(season.season_losses_to_date, 0),
       COALESCE(season.season_points_to_date, 0),
       COALESCE(season.season_goals_for_to_date, 0),
       COALESCE(season.season_goals_against_to_date, 0),
       COALESCE(season.season_goal_difference_to_date, 0),
       round(season.season_points_to_date::numeric / NULLIF(season.season_matches_to_date, 0), 4),
       h2h.matches,
       h2h.wins,
       h2h.draws,
       h2h.losses,
       h2h.points,
       h2h.goals_for,
       h2h.goals_against,
       h2h.points_per_match
  FROM curated.match_team_history a
  LEFT JOIN LATERAL (
      SELECT p.*
        FROM curated.match_team_history p
       WHERE p.team_id = a.team_id AND p.is_finished
         AND p.utc_kickoff < a.utc_kickoff - interval '3 hours'
       ORDER BY p.utc_kickoff DESC, p.match_id DESC LIMIT 1
  ) h ON true
  LEFT JOIN LATERAL (
      SELECT count(*) FILTER (WHERE p.utc_kickoff >= a.utc_kickoff - interval '7 days') AS played_last_7_days,
             count(*) FILTER (WHERE p.utc_kickoff >= a.utc_kickoff - interval '14 days') AS played_last_14_days,
             count(*) FILTER (WHERE p.utc_kickoff >= a.utc_kickoff - interval '30 days') AS played_last_30_days
        FROM curated.match_team_history p
       WHERE p.team_id = a.team_id AND p.is_finished
         AND p.utc_kickoff < a.utc_kickoff - interval '3 hours'
         AND p.utc_kickoff >= a.utc_kickoff - interval '30 days'
  ) load ON true
  LEFT JOIN LATERAL (
      SELECT count(*) FILTER (WHERE p.rn <= 3) AS matches_last_3,
             count(*) FILTER (WHERE p.rn <= 3 AND p.goals_for > p.goals_against) AS wins_last_3,
             count(*) FILTER (WHERE p.rn <= 3 AND p.goals_for = p.goals_against) AS draws_last_3,
             count(*) FILTER (WHERE p.rn <= 3 AND p.goals_for < p.goals_against) AS losses_last_3,
             COALESCE(sum(p.points) FILTER (WHERE p.rn <= 3), 0) AS points_last_3,
             COALESCE(sum(p.goals_for) FILTER (WHERE p.rn <= 3), 0) AS goals_for_last_3,
             COALESCE(sum(p.goals_against) FILTER (WHERE p.rn <= 3), 0) AS goals_against_last_3,
             (COALESCE(sum(p.goals_for) FILTER (WHERE p.rn <= 3), 0) - COALESCE(sum(p.goals_against) FILTER (WHERE p.rn <= 3), 0)) AS goal_difference_last_3,
             count(*) FILTER (WHERE p.rn <= 3 AND p.goals_against = 0) AS clean_sheets_last_3,
             count(*) FILTER (WHERE p.rn <= 3 AND p.goals_for = 0) AS failed_to_score_last_3,
             count(*) FILTER (WHERE p.rn <= 3 AND p.goals_for > 0 AND p.goals_against > 0) AS both_teams_scored_last_3,
             count(*) FILTER (WHERE p.rn <= 3 AND p.goals_for + p.goals_against > 2) AS over_2_5_last_3,
             round(sum(p.goals_for) FILTER (WHERE p.rn <= 3)::numeric / NULLIF(count(*) FILTER (WHERE p.rn <= 3), 0), 4) AS goals_for_per_match_last_3,
             round(sum(p.goals_against) FILTER (WHERE p.rn <= 3)::numeric / NULLIF(count(*) FILTER (WHERE p.rn <= 3), 0), 4) AS goals_against_per_match_last_3,
             round(sum(p.points) FILTER (WHERE p.rn <= 3)::numeric / NULLIF(count(*) FILTER (WHERE p.rn <= 3), 0), 4) AS points_per_match_last_3,
             round(count(*) FILTER (WHERE p.rn <= 3 AND p.goals_for > p.goals_against)::numeric / NULLIF(count(*) FILTER (WHERE p.rn <= 3), 0), 4) AS win_rate_last_3,
             count(*) FILTER (WHERE p.rn <= 5) AS matches_last_5,
             count(*) FILTER (WHERE p.rn <= 5 AND p.goals_for > p.goals_against) AS wins_last_5,
             count(*) FILTER (WHERE p.rn <= 5 AND p.goals_for = p.goals_against) AS draws_last_5,
             count(*) FILTER (WHERE p.rn <= 5 AND p.goals_for < p.goals_against) AS losses_last_5,
             COALESCE(sum(p.points) FILTER (WHERE p.rn <= 5), 0) AS points_last_5,
             COALESCE(sum(p.goals_for) FILTER (WHERE p.rn <= 5), 0) AS goals_for_last_5,
             COALESCE(sum(p.goals_against) FILTER (WHERE p.rn <= 5), 0) AS goals_against_last_5,
             (COALESCE(sum(p.goals_for) FILTER (WHERE p.rn <= 5), 0) - COALESCE(sum(p.goals_against) FILTER (WHERE p.rn <= 5), 0)) AS goal_difference_last_5,
             count(*) FILTER (WHERE p.rn <= 5 AND p.goals_against = 0) AS clean_sheets_last_5,
             count(*) FILTER (WHERE p.rn <= 5 AND p.goals_for = 0) AS failed_to_score_last_5,
             count(*) FILTER (WHERE p.rn <= 5 AND p.goals_for > 0 AND p.goals_against > 0) AS both_teams_scored_last_5,
             count(*) FILTER (WHERE p.rn <= 5 AND p.goals_for + p.goals_against > 2) AS over_2_5_last_5,
             round(sum(p.goals_for) FILTER (WHERE p.rn <= 5)::numeric / NULLIF(count(*) FILTER (WHERE p.rn <= 5), 0), 4) AS goals_for_per_match_last_5,
             round(sum(p.goals_against) FILTER (WHERE p.rn <= 5)::numeric / NULLIF(count(*) FILTER (WHERE p.rn <= 5), 0), 4) AS goals_against_per_match_last_5,
             round(sum(p.points) FILTER (WHERE p.rn <= 5)::numeric / NULLIF(count(*) FILTER (WHERE p.rn <= 5), 0), 4) AS points_per_match_last_5,
             round(count(*) FILTER (WHERE p.rn <= 5 AND p.goals_for > p.goals_against)::numeric / NULLIF(count(*) FILTER (WHERE p.rn <= 5), 0), 4) AS win_rate_last_5,
             count(*) FILTER (WHERE p.rn <= 10) AS matches_last_10,
             count(*) FILTER (WHERE p.rn <= 10 AND p.goals_for > p.goals_against) AS wins_last_10,
             count(*) FILTER (WHERE p.rn <= 10 AND p.goals_for = p.goals_against) AS draws_last_10,
             count(*) FILTER (WHERE p.rn <= 10 AND p.goals_for < p.goals_against) AS losses_last_10,
             COALESCE(sum(p.points) FILTER (WHERE p.rn <= 10), 0) AS points_last_10,
             COALESCE(sum(p.goals_for) FILTER (WHERE p.rn <= 10), 0) AS goals_for_last_10,
             COALESCE(sum(p.goals_against) FILTER (WHERE p.rn <= 10), 0) AS goals_against_last_10,
             (COALESCE(sum(p.goals_for) FILTER (WHERE p.rn <= 10), 0) - COALESCE(sum(p.goals_against) FILTER (WHERE p.rn <= 10), 0)) AS goal_difference_last_10,
             count(*) FILTER (WHERE p.rn <= 10 AND p.goals_against = 0) AS clean_sheets_last_10,
             count(*) FILTER (WHERE p.rn <= 10 AND p.goals_for = 0) AS failed_to_score_last_10,
             count(*) FILTER (WHERE p.rn <= 10 AND p.goals_for > 0 AND p.goals_against > 0) AS both_teams_scored_last_10,
             count(*) FILTER (WHERE p.rn <= 10 AND p.goals_for + p.goals_against > 2) AS over_2_5_last_10,
             round(sum(p.goals_for) FILTER (WHERE p.rn <= 10)::numeric / NULLIF(count(*) FILTER (WHERE p.rn <= 10), 0), 4) AS goals_for_per_match_last_10,
             round(sum(p.goals_against) FILTER (WHERE p.rn <= 10)::numeric / NULLIF(count(*) FILTER (WHERE p.rn <= 10), 0), 4) AS goals_against_per_match_last_10,
             round(sum(p.points) FILTER (WHERE p.rn <= 10)::numeric / NULLIF(count(*) FILTER (WHERE p.rn <= 10), 0), 4) AS points_per_match_last_10,
             round(count(*) FILTER (WHERE p.rn <= 10 AND p.goals_for > p.goals_against)::numeric / NULLIF(count(*) FILTER (WHERE p.rn <= 10), 0), 4) AS win_rate_last_10
        FROM (
            SELECT p.goals_for, p.goals_against, p.points,
                   row_number() OVER (ORDER BY p.utc_kickoff DESC, p.match_id DESC) AS rn
              FROM curated.match_team_history p
             WHERE p.team_id = a.team_id
           AND p.is_finished
           AND p.utc_kickoff < a.utc_kickoff - interval '3 hours'
           AND p.goals_for IS NOT NULL AND p.goals_against IS NOT NULL
             ORDER BY p.utc_kickoff DESC, p.match_id DESC LIMIT 10
        ) p
  ) form ON true
  LEFT JOIN LATERAL (
      SELECT count(*) AS matches,
             COALESCE(sum(p.points), 0) AS points,
             count(*) FILTER (WHERE p.goals_for > p.goals_against) AS wins,
             COALESCE(sum(p.goals_for), 0) AS goals_for,
             COALESCE(sum(p.goals_against), 0) AS goals_against,
             count(*) FILTER (WHERE p.goals_against = 0) AS clean_sheets,
             round(sum(p.points)::numeric / NULLIF(count(*), 0), 4) AS points_per_match
        FROM (
            SELECT p.goals_for, p.goals_against, p.points
              FROM curated.match_team_history p
             WHERE p.team_id = a.team_id
           AND p.is_finished
           AND p.utc_kickoff < a.utc_kickoff - interval '3 hours'
           AND p.goals_for IS NOT NULL AND p.goals_against IS NOT NULL
               AND p.is_home = a.is_home
             ORDER BY p.utc_kickoff DESC, p.match_id DESC LIMIT 5
        ) p
  ) venue ON true
  LEFT JOIN LATERAL (
      SELECT count(*) AS matches,
             COALESCE(sum(p.points), 0) AS points,
             count(*) FILTER (WHERE p.goals_for > p.goals_against) AS wins,
             COALESCE(sum(p.goals_for), 0) AS goals_for,
             COALESCE(sum(p.goals_against), 0) AS goals_against,
             count(*) FILTER (WHERE p.goals_against = 0) AS clean_sheets,
             round(sum(p.points)::numeric / NULLIF(count(*), 0), 4) AS points_per_match
        FROM (
            SELECT p.goals_for, p.goals_against, p.points
              FROM curated.match_team_history p
             WHERE p.team_id = a.team_id
           AND p.is_finished
           AND p.utc_kickoff < a.utc_kickoff - interval '3 hours'
           AND p.goals_for IS NOT NULL AND p.goals_against IS NOT NULL
               AND p.competition_code = a.competition_code
             ORDER BY p.utc_kickoff DESC, p.match_id DESC LIMIT 5
        ) p
  ) competition ON true
  LEFT JOIN LATERAL (
      SELECT count(*) AS matches,
             count(*) FILTER (WHERE p.goals_for > p.goals_against) AS wins,
             count(*) FILTER (WHERE p.goals_for = p.goals_against) AS draws,
             count(*) FILTER (WHERE p.goals_for < p.goals_against) AS losses,
             COALESCE(sum(p.points), 0) AS points,
             COALESCE(sum(p.goals_for), 0) AS goals_for,
             COALESCE(sum(p.goals_against), 0) AS goals_against,
             round(sum(p.points)::numeric / NULLIF(count(*), 0), 4) AS points_per_match
        FROM (
            SELECT p.goals_for, p.goals_against, p.points
              FROM curated.match_team_history p
             WHERE p.team_id = a.team_id
           AND p.is_finished
           AND p.utc_kickoff < a.utc_kickoff - interval '3 hours'
           AND p.goals_for IS NOT NULL AND p.goals_against IS NOT NULL
               AND p.opponent_team_id = a.opponent_team_id
             ORDER BY p.utc_kickoff DESC, p.match_id DESC LIMIT 5
        ) p
  ) h2h ON true
  LEFT JOIN LATERAL (
      SELECT p.season_matches_to_date, p.season_wins_to_date, p.season_draws_to_date, p.season_losses_to_date, p.season_points_to_date, p.season_goals_for_to_date, p.season_goals_against_to_date, p.season_goal_difference_to_date
        FROM curated.match_team_history p
       WHERE p.team_id = a.team_id
           AND p.is_finished
           AND p.utc_kickoff < a.utc_kickoff - interval '3 hours'
           AND p.goals_for IS NOT NULL AND p.goals_against IS NOT NULL
         AND p.competition_code = a.competition_code AND p.season_id = a.season_id
       ORDER BY p.utc_kickoff DESC, p.match_id DESC LIMIT 1
  ) season ON true;

ANALYZE curated.team_match_features;
