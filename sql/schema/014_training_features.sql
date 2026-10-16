-- Version 1 match training product: regular-time labels and pre-match history.
-- Historical results are reconstructed by event time. The source does not
-- expose final-whistle timestamps, so kickoff + 3 hours is the availability
-- proxy. This is NOT an archive of what our system had ingested at that time.
-- Snapshot enrichments, weather and odds additionally enforce observation time.

ALTER TABLE staging.matches ADD COLUMN IF NOT EXISTS home_goals_90min integer;
ALTER TABLE staging.matches ADD COLUMN IF NOT EXISTS away_goals_90min integer;

CREATE TABLE IF NOT EXISTS curated.match_team_history (
    match_id bigint NOT NULL REFERENCES curated.fact_match(match_id) ON DELETE CASCADE,
    team_id bigint NOT NULL REFERENCES curated.dim_team(team_id),
    opponent_team_id bigint NOT NULL,
    competition_code text NOT NULL,
    season_id bigint NOT NULL,
    is_home boolean NOT NULL,
    utc_kickoff timestamptz NOT NULL,
    result_available_at timestamptz NOT NULL,
    is_finished boolean NOT NULL,
    goals_for integer,
    goals_against integer,
    points integer,
    completed_matches_to_date integer NOT NULL,
    first_completed_kickoff timestamptz,
    season_matches_to_date integer NOT NULL,
    season_wins_to_date integer NOT NULL,
    season_draws_to_date integer NOT NULL,
    season_losses_to_date integer NOT NULL,
    season_points_to_date integer NOT NULL,
    season_goals_for_to_date integer NOT NULL,
    season_goals_against_to_date integer NOT NULL,
    season_goal_difference_to_date integer NOT NULL,
    PRIMARY KEY (match_id, team_id)
);
CREATE INDEX IF NOT EXISTS team_history_prior_idx
    ON curated.match_team_history(team_id, utc_kickoff DESC)
    WHERE is_finished;
CREATE INDEX IF NOT EXISTS team_history_season_idx
    ON curated.match_team_history(team_id, competition_code, season_id, utc_kickoff DESC)
    WHERE is_finished;
CREATE INDEX IF NOT EXISTS team_history_venue_idx
    ON curated.match_team_history(team_id, is_home, utc_kickoff DESC)
    WHERE is_finished;
CREATE INDEX IF NOT EXISTS team_history_opponent_idx
    ON curated.match_team_history(team_id, opponent_team_id, utc_kickoff DESC)
    WHERE is_finished;
COMMENT ON TABLE curated.match_team_history IS
    'Two rows per fixture: one per team. Indexed history for regular-time features; all completed matches count toward workload.';
COMMENT ON COLUMN curated.match_team_history.result_available_at IS
    'Kickoff + 3 hours: conservative proxy because the source does not provide actual final-whistle time.';

CREATE TABLE IF NOT EXISTS curated.team_match_features (
    match_id bigint NOT NULL REFERENCES curated.fact_match(match_id) ON DELETE CASCADE,
    team_id bigint NOT NULL REFERENCES curated.dim_team(team_id),
    history_matches integer,
    history_first_kickoff timestamptz,
    history_last_kickoff timestamptz,
    history_last_available_at timestamptz,
    rest_days numeric(10,3),
    played_last_7_days integer,
    played_last_14_days integer,
    played_last_30_days integer,
    matches_last_3 integer,
    wins_last_3 integer,
    draws_last_3 integer,
    losses_last_3 integer,
    points_last_3 integer,
    goals_for_last_3 integer,
    goals_against_last_3 integer,
    goal_difference_last_3 integer,
    clean_sheets_last_3 integer,
    failed_to_score_last_3 integer,
    both_teams_scored_last_3 integer,
    over_2_5_last_3 integer,
    goals_for_per_match_last_3 numeric(10,4),
    goals_against_per_match_last_3 numeric(10,4),
    points_per_match_last_3 numeric(10,4),
    win_rate_last_3 numeric(10,4),
    matches_last_5 integer,
    wins_last_5 integer,
    draws_last_5 integer,
    losses_last_5 integer,
    points_last_5 integer,
    goals_for_last_5 integer,
    goals_against_last_5 integer,
    goal_difference_last_5 integer,
    clean_sheets_last_5 integer,
    failed_to_score_last_5 integer,
    both_teams_scored_last_5 integer,
    over_2_5_last_5 integer,
    goals_for_per_match_last_5 numeric(10,4),
    goals_against_per_match_last_5 numeric(10,4),
    points_per_match_last_5 numeric(10,4),
    win_rate_last_5 numeric(10,4),
    matches_last_10 integer,
    wins_last_10 integer,
    draws_last_10 integer,
    losses_last_10 integer,
    points_last_10 integer,
    goals_for_last_10 integer,
    goals_against_last_10 integer,
    goal_difference_last_10 integer,
    clean_sheets_last_10 integer,
    failed_to_score_last_10 integer,
    both_teams_scored_last_10 integer,
    over_2_5_last_10 integer,
    goals_for_per_match_last_10 numeric(10,4),
    goals_against_per_match_last_10 numeric(10,4),
    points_per_match_last_10 numeric(10,4),
    win_rate_last_10 numeric(10,4),
    venue_matches_last_5 integer,
    venue_points_last_5 integer,
    venue_wins_last_5 integer,
    venue_goals_for_last_5 integer,
    venue_goals_against_last_5 integer,
    venue_clean_sheets_last_5 integer,
    venue_points_per_match_last_5 numeric(10,4),
    competition_matches_last_5 integer,
    competition_points_last_5 integer,
    competition_wins_last_5 integer,
    competition_goals_for_last_5 integer,
    competition_goals_against_last_5 integer,
    competition_clean_sheets_last_5 integer,
    competition_points_per_match_last_5 numeric(10,4),
    season_matches integer,
    season_wins integer,
    season_draws integer,
    season_losses integer,
    season_points integer,
    season_goals_for integer,
    season_goals_against integer,
    season_goal_difference integer,
    season_points_per_match numeric(10,4),
    h2h_matches_last_5 integer,
    h2h_wins_last_5 integer,
    h2h_draws_last_5 integer,
    h2h_losses_last_5 integer,
    h2h_points_last_5 integer,
    h2h_goals_for_last_5 integer,
    h2h_goals_against_last_5 integer,
    h2h_points_per_match_last_5 numeric(10,4),
    computed_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (match_id, team_id)
);
COMMENT ON TABLE curated.team_match_features IS
    'One row per fixture and team. Prior completed fixtures only, regular-time scores, explicit window sizes and coverage.';

-- Keep the old curated.model_features dashboard contract intact.
-- This product has no post-match result columns disguised as predictors.
-- Training odds use live fetches directly. Fictional offline prices must
-- never acquire an early observation time by sharing a quote with live data.
CREATE OR REPLACE VIEW curated.training_bookmaker_quotes AS
WITH quotes AS (
    SELECT s.raw_id AS odds_id, x.match_id, s.bookmaker_key, s.market_key,
           s.source_updated_at, s.fetched_at AS first_seen_at,
           max(s.price) FILTER (WHERE s.outcome_role = 'HOME') AS home_price,
           max(s.price) FILTER (WHERE s.outcome_role = 'DRAW') AS draw_price,
           max(s.price) FILTER (WHERE s.outcome_role = 'AWAY') AS away_price
    FROM staging.bookmaker_odds s
    JOIN raw.odds_api r USING (raw_id)
    JOIN staging.odds_event_match x USING (event_id)
    WHERE r.source = 'the-odds-api.com' AND x.match_id IS NOT NULL
    GROUP BY 1,2,3,4,5,6
), priced AS (
    SELECT *, home_price IS NOT NULL AND draw_price IS NOT NULL
              AND away_price IS NOT NULL AS is_complete,
           1/home_price + 1/draw_price + 1/away_price AS implied_total
    FROM quotes
)
SELECT *, implied_total-1 AS overround,
       (1/home_price)/implied_total AS home_prob_fair,
       (1/draw_price)/implied_total AS draw_prob_fair,
       (1/away_price)/implied_total AS away_prob_fair
FROM priced;

-- Labels and audit fields are explicitly named for the export allowlist.
CREATE OR REPLACE VIEW curated.match_training_features AS
SELECT
    m.match_id,
    m.season_id,
    m.competition_code,
    m.utc_kickoff,
    (m.utc_kickoff AT TIME ZONE 'UTC')::date AS match_date,
    m.stage,
    m.matchday,
    m.home_team_id,
    m.away_team_id,
    extract(year FROM m.utc_kickoff AT TIME ZONE 'UTC')::int AS kickoff_year,
    extract(month FROM m.utc_kickoff AT TIME ZONE 'UTC')::int AS kickoff_month,
    extract(isodow FROM m.utc_kickoff AT TIME ZONE 'UTC')::int AS kickoff_day_of_week,
    extract(hour FROM m.utc_kickoff AT TIME ZONE 'UTC')::int AS kickoff_hour_utc,
    ht.name AS audit_home_team_name,
    at.name AS audit_away_team_name,
    m.status AS audit_match_status,
    m.duration AS audit_result_duration,
    m.last_updated AS audit_result_last_updated,
    m.ingestion_date AS audit_ingestion_date,
    greatest(h.computed_at, a.computed_at) AS audit_computed_at,
    'regular-time-v3'::text AS audit_feature_version,
    CASE WHEN m.status = 'FINISHED' AND m.home_goals_90min IS NOT NULL AND m.away_goals_90min IS NOT NULL
         THEN CASE WHEN m.home_goals_90min > m.away_goals_90min THEN 'HOME_WIN'
                   WHEN m.home_goals_90min < m.away_goals_90min THEN 'AWAY_WIN'
                   ELSE 'DRAW' END END AS label_outcome_90min,
    CASE WHEN m.status = 'FINISHED' THEN m.home_goals_90min END AS label_home_goals_90min,
    CASE WHEN m.status = 'FINISHED' THEN m.away_goals_90min END AS label_away_goals_90min,
    (m.status = 'FINISHED' AND m.home_goals_90min IS NOT NULL AND m.away_goals_90min IS NOT NULL) AS label_available,
    h.history_matches AS home_history_matches,
    h.history_first_kickoff AS audit_home_history_first_kickoff,
    h.history_last_kickoff AS audit_home_history_last_kickoff,
    h.history_last_available_at AS audit_home_history_last_available_at,
    h.rest_days AS home_rest_days,
    h.played_last_7_days AS home_played_last_7_days,
    h.played_last_14_days AS home_played_last_14_days,
    h.played_last_30_days AS home_played_last_30_days,
    h.matches_last_3 AS home_matches_last_3,
    h.wins_last_3 AS home_wins_last_3,
    h.draws_last_3 AS home_draws_last_3,
    h.losses_last_3 AS home_losses_last_3,
    h.points_last_3 AS home_points_last_3,
    h.goals_for_last_3 AS home_goals_for_last_3,
    h.goals_against_last_3 AS home_goals_against_last_3,
    h.goal_difference_last_3 AS home_goal_difference_last_3,
    h.clean_sheets_last_3 AS home_clean_sheets_last_3,
    h.failed_to_score_last_3 AS home_failed_to_score_last_3,
    h.both_teams_scored_last_3 AS home_both_teams_scored_last_3,
    h.over_2_5_last_3 AS home_over_2_5_last_3,
    h.goals_for_per_match_last_3 AS home_goals_for_per_match_last_3,
    h.goals_against_per_match_last_3 AS home_goals_against_per_match_last_3,
    h.points_per_match_last_3 AS home_points_per_match_last_3,
    h.win_rate_last_3 AS home_win_rate_last_3,
    h.matches_last_5 AS home_matches_last_5,
    h.wins_last_5 AS home_wins_last_5,
    h.draws_last_5 AS home_draws_last_5,
    h.losses_last_5 AS home_losses_last_5,
    h.points_last_5 AS home_points_last_5,
    h.goals_for_last_5 AS home_goals_for_last_5,
    h.goals_against_last_5 AS home_goals_against_last_5,
    h.goal_difference_last_5 AS home_goal_difference_last_5,
    h.clean_sheets_last_5 AS home_clean_sheets_last_5,
    h.failed_to_score_last_5 AS home_failed_to_score_last_5,
    h.both_teams_scored_last_5 AS home_both_teams_scored_last_5,
    h.over_2_5_last_5 AS home_over_2_5_last_5,
    h.goals_for_per_match_last_5 AS home_goals_for_per_match_last_5,
    h.goals_against_per_match_last_5 AS home_goals_against_per_match_last_5,
    h.points_per_match_last_5 AS home_points_per_match_last_5,
    h.win_rate_last_5 AS home_win_rate_last_5,
    h.matches_last_10 AS home_matches_last_10,
    h.wins_last_10 AS home_wins_last_10,
    h.draws_last_10 AS home_draws_last_10,
    h.losses_last_10 AS home_losses_last_10,
    h.points_last_10 AS home_points_last_10,
    h.goals_for_last_10 AS home_goals_for_last_10,
    h.goals_against_last_10 AS home_goals_against_last_10,
    h.goal_difference_last_10 AS home_goal_difference_last_10,
    h.clean_sheets_last_10 AS home_clean_sheets_last_10,
    h.failed_to_score_last_10 AS home_failed_to_score_last_10,
    h.both_teams_scored_last_10 AS home_both_teams_scored_last_10,
    h.over_2_5_last_10 AS home_over_2_5_last_10,
    h.goals_for_per_match_last_10 AS home_goals_for_per_match_last_10,
    h.goals_against_per_match_last_10 AS home_goals_against_per_match_last_10,
    h.points_per_match_last_10 AS home_points_per_match_last_10,
    h.win_rate_last_10 AS home_win_rate_last_10,
    h.venue_matches_last_5 AS home_venue_matches_last_5,
    h.venue_points_last_5 AS home_venue_points_last_5,
    h.venue_wins_last_5 AS home_venue_wins_last_5,
    h.venue_goals_for_last_5 AS home_venue_goals_for_last_5,
    h.venue_goals_against_last_5 AS home_venue_goals_against_last_5,
    h.venue_clean_sheets_last_5 AS home_venue_clean_sheets_last_5,
    h.venue_points_per_match_last_5 AS home_venue_points_per_match_last_5,
    h.competition_matches_last_5 AS home_competition_matches_last_5,
    h.competition_points_last_5 AS home_competition_points_last_5,
    h.competition_wins_last_5 AS home_competition_wins_last_5,
    h.competition_goals_for_last_5 AS home_competition_goals_for_last_5,
    h.competition_goals_against_last_5 AS home_competition_goals_against_last_5,
    h.competition_clean_sheets_last_5 AS home_competition_clean_sheets_last_5,
    h.competition_points_per_match_last_5 AS home_competition_points_per_match_last_5,
    h.season_matches AS home_season_matches,
    h.season_wins AS home_season_wins,
    h.season_draws AS home_season_draws,
    h.season_losses AS home_season_losses,
    h.season_points AS home_season_points,
    h.season_goals_for AS home_season_goals_for,
    h.season_goals_against AS home_season_goals_against,
    h.season_goal_difference AS home_season_goal_difference,
    h.season_points_per_match AS home_season_points_per_match,
    h.h2h_matches_last_5 AS home_h2h_matches_last_5,
    h.h2h_wins_last_5 AS home_h2h_wins_last_5,
    h.h2h_draws_last_5 AS home_h2h_draws_last_5,
    h.h2h_losses_last_5 AS home_h2h_losses_last_5,
    h.h2h_points_last_5 AS home_h2h_points_last_5,
    h.h2h_goals_for_last_5 AS home_h2h_goals_for_last_5,
    h.h2h_goals_against_last_5 AS home_h2h_goals_against_last_5,
    h.h2h_points_per_match_last_5 AS home_h2h_points_per_match_last_5,
    a.history_matches AS away_history_matches,
    a.history_first_kickoff AS audit_away_history_first_kickoff,
    a.history_last_kickoff AS audit_away_history_last_kickoff,
    a.history_last_available_at AS audit_away_history_last_available_at,
    a.rest_days AS away_rest_days,
    a.played_last_7_days AS away_played_last_7_days,
    a.played_last_14_days AS away_played_last_14_days,
    a.played_last_30_days AS away_played_last_30_days,
    a.matches_last_3 AS away_matches_last_3,
    a.wins_last_3 AS away_wins_last_3,
    a.draws_last_3 AS away_draws_last_3,
    a.losses_last_3 AS away_losses_last_3,
    a.points_last_3 AS away_points_last_3,
    a.goals_for_last_3 AS away_goals_for_last_3,
    a.goals_against_last_3 AS away_goals_against_last_3,
    a.goal_difference_last_3 AS away_goal_difference_last_3,
    a.clean_sheets_last_3 AS away_clean_sheets_last_3,
    a.failed_to_score_last_3 AS away_failed_to_score_last_3,
    a.both_teams_scored_last_3 AS away_both_teams_scored_last_3,
    a.over_2_5_last_3 AS away_over_2_5_last_3,
    a.goals_for_per_match_last_3 AS away_goals_for_per_match_last_3,
    a.goals_against_per_match_last_3 AS away_goals_against_per_match_last_3,
    a.points_per_match_last_3 AS away_points_per_match_last_3,
    a.win_rate_last_3 AS away_win_rate_last_3,
    a.matches_last_5 AS away_matches_last_5,
    a.wins_last_5 AS away_wins_last_5,
    a.draws_last_5 AS away_draws_last_5,
    a.losses_last_5 AS away_losses_last_5,
    a.points_last_5 AS away_points_last_5,
    a.goals_for_last_5 AS away_goals_for_last_5,
    a.goals_against_last_5 AS away_goals_against_last_5,
    a.goal_difference_last_5 AS away_goal_difference_last_5,
    a.clean_sheets_last_5 AS away_clean_sheets_last_5,
    a.failed_to_score_last_5 AS away_failed_to_score_last_5,
    a.both_teams_scored_last_5 AS away_both_teams_scored_last_5,
    a.over_2_5_last_5 AS away_over_2_5_last_5,
    a.goals_for_per_match_last_5 AS away_goals_for_per_match_last_5,
    a.goals_against_per_match_last_5 AS away_goals_against_per_match_last_5,
    a.points_per_match_last_5 AS away_points_per_match_last_5,
    a.win_rate_last_5 AS away_win_rate_last_5,
    a.matches_last_10 AS away_matches_last_10,
    a.wins_last_10 AS away_wins_last_10,
    a.draws_last_10 AS away_draws_last_10,
    a.losses_last_10 AS away_losses_last_10,
    a.points_last_10 AS away_points_last_10,
    a.goals_for_last_10 AS away_goals_for_last_10,
    a.goals_against_last_10 AS away_goals_against_last_10,
    a.goal_difference_last_10 AS away_goal_difference_last_10,
    a.clean_sheets_last_10 AS away_clean_sheets_last_10,
    a.failed_to_score_last_10 AS away_failed_to_score_last_10,
    a.both_teams_scored_last_10 AS away_both_teams_scored_last_10,
    a.over_2_5_last_10 AS away_over_2_5_last_10,
    a.goals_for_per_match_last_10 AS away_goals_for_per_match_last_10,
    a.goals_against_per_match_last_10 AS away_goals_against_per_match_last_10,
    a.points_per_match_last_10 AS away_points_per_match_last_10,
    a.win_rate_last_10 AS away_win_rate_last_10,
    a.venue_matches_last_5 AS away_venue_matches_last_5,
    a.venue_points_last_5 AS away_venue_points_last_5,
    a.venue_wins_last_5 AS away_venue_wins_last_5,
    a.venue_goals_for_last_5 AS away_venue_goals_for_last_5,
    a.venue_goals_against_last_5 AS away_venue_goals_against_last_5,
    a.venue_clean_sheets_last_5 AS away_venue_clean_sheets_last_5,
    a.venue_points_per_match_last_5 AS away_venue_points_per_match_last_5,
    a.competition_matches_last_5 AS away_competition_matches_last_5,
    a.competition_points_last_5 AS away_competition_points_last_5,
    a.competition_wins_last_5 AS away_competition_wins_last_5,
    a.competition_goals_for_last_5 AS away_competition_goals_for_last_5,
    a.competition_goals_against_last_5 AS away_competition_goals_against_last_5,
    a.competition_clean_sheets_last_5 AS away_competition_clean_sheets_last_5,
    a.competition_points_per_match_last_5 AS away_competition_points_per_match_last_5,
    a.season_matches AS away_season_matches,
    a.season_wins AS away_season_wins,
    a.season_draws AS away_season_draws,
    a.season_losses AS away_season_losses,
    a.season_points AS away_season_points,
    a.season_goals_for AS away_season_goals_for,
    a.season_goals_against AS away_season_goals_against,
    a.season_goal_difference AS away_season_goal_difference,
    a.season_points_per_match AS away_season_points_per_match,
    a.h2h_matches_last_5 AS away_h2h_matches_last_5,
    a.h2h_wins_last_5 AS away_h2h_wins_last_5,
    a.h2h_draws_last_5 AS away_h2h_draws_last_5,
    a.h2h_losses_last_5 AS away_h2h_losses_last_5,
    a.h2h_points_last_5 AS away_h2h_points_last_5,
    a.h2h_goals_for_last_5 AS away_h2h_goals_for_last_5,
    a.h2h_goals_against_last_5 AS away_h2h_goals_against_last_5,
    a.h2h_points_per_match_last_5 AS away_h2h_points_per_match_last_5,
    h.points_last_5 - a.points_last_5 AS points_difference_last_5,
    h.points_last_10 - a.points_last_10 AS points_difference_last_10,
    h.goals_for_last_5 - a.goals_for_last_5 AS goals_for_difference_last_5,
    h.goals_against_last_5 - a.goals_against_last_5 AS goals_against_difference_last_5,
    h.goal_difference_last_10 - a.goal_difference_last_10 AS goal_difference_difference_last_10,
    h.rest_days - a.rest_days AS rest_days_difference,
    h.season_points_per_match - a.season_points_per_match AS season_points_per_match_difference,
    h.matches_last_10 = 10 AND a.matches_last_10 = 10 AS has_full_history_last_10,
    h.matches_last_10 = 0 AS home_has_no_prior_results,
    a.matches_last_10 = 0 AS away_has_no_prior_results,
    c.home_context_observed_at AS audit_home_context_observed_at,
    c.home_context_source AS audit_home_context_source,
    c.home_context_age_days AS home_context_age_days,
    c.home_squad_source AS audit_home_squad_source,
    c.home_squad_observed_at AS audit_home_squad_observed_at,
    c.home_squad_size AS home_squad_size,
    c.home_squad_avg_age AS home_squad_avg_age,
    c.home_squad_min_age AS home_squad_min_age,
    c.home_squad_max_age AS home_squad_max_age,
    c.home_squad_nationalities AS home_squad_nationalities,
    c.home_squad_foreign_players AS home_squad_foreign_players,
    c.home_squad_goalkeepers AS home_squad_goalkeepers,
    c.home_squad_defenders AS home_squad_defenders,
    c.home_squad_midfielders AS home_squad_midfielders,
    c.home_squad_attackers AS home_squad_attackers,
    c.home_squad_unknown_positions AS home_squad_unknown_positions,
    c.home_squad_missing_birthdates AS home_squad_missing_birthdates,
    c.home_coach_id AS audit_home_coach_id,
    c.home_coach_name AS audit_home_coach_name,
    c.home_coach_age AS home_coach_age,
    c.home_coach_nationality AS home_coach_nationality,
    c.home_coach_tenure_days AS home_coach_tenure_days,
    c.home_coach_observed_tenure_days AS home_coach_observed_tenure_days,
    c.home_coach_prior_matches AS home_coach_prior_matches,
    c.home_coach_prior_win_rate AS home_coach_prior_win_rate,
    c.home_coach_prior_points_per_match AS home_coach_prior_points_per_match,
    c.home_coach_source AS audit_home_coach_source,
    c.home_coach_observed_at AS audit_home_coach_observed_at,
    c.home_squad_market_value_eur AS home_squad_market_value_eur,
    c.home_market_value_observed_at AS audit_home_market_value_observed_at,
    c.home_market_value_source AS audit_home_market_value_source,
    c.away_context_observed_at AS audit_away_context_observed_at,
    c.away_context_source AS audit_away_context_source,
    c.away_context_age_days AS away_context_age_days,
    c.away_squad_source AS audit_away_squad_source,
    c.away_squad_observed_at AS audit_away_squad_observed_at,
    c.away_squad_size AS away_squad_size,
    c.away_squad_avg_age AS away_squad_avg_age,
    c.away_squad_min_age AS away_squad_min_age,
    c.away_squad_max_age AS away_squad_max_age,
    c.away_squad_nationalities AS away_squad_nationalities,
    c.away_squad_foreign_players AS away_squad_foreign_players,
    c.away_squad_goalkeepers AS away_squad_goalkeepers,
    c.away_squad_defenders AS away_squad_defenders,
    c.away_squad_midfielders AS away_squad_midfielders,
    c.away_squad_attackers AS away_squad_attackers,
    c.away_squad_unknown_positions AS away_squad_unknown_positions,
    c.away_squad_missing_birthdates AS away_squad_missing_birthdates,
    c.away_coach_id AS audit_away_coach_id,
    c.away_coach_name AS audit_away_coach_name,
    c.away_coach_age AS away_coach_age,
    c.away_coach_nationality AS away_coach_nationality,
    c.away_coach_tenure_days AS away_coach_tenure_days,
    c.away_coach_observed_tenure_days AS away_coach_observed_tenure_days,
    c.away_coach_prior_matches AS away_coach_prior_matches,
    c.away_coach_prior_win_rate AS away_coach_prior_win_rate,
    c.away_coach_prior_points_per_match AS away_coach_prior_points_per_match,
    c.away_coach_source AS audit_away_coach_source,
    c.away_coach_observed_at AS audit_away_coach_observed_at,
    c.away_squad_market_value_eur AS away_squad_market_value_eur,
    c.away_market_value_observed_at AS audit_away_market_value_observed_at,
    c.away_market_value_source AS audit_away_market_value_source,
    COALESCE(w.weather_status, 'NOT_CAPTURED') AS weather_status,
    w.temperature_c,
    w.precipitation_mm,
    w.precipitation_probability,
    w.wind_speed_kmh,
    w.weather_code,
    w.lead_days AS weather_lead_days,
    w.forecast_fetched_at AS audit_weather_observed_at,
    o.odds_bookmaker_count,
    o.odds_home_prob_fair,
    o.odds_draw_prob_fair,
    o.odds_away_prob_fair,
    o.odds_mean_overround,
    o.odds_home_price_mean,
    o.odds_draw_price_mean,
    o.odds_away_price_mean,
    o.odds_home_prob_stddev,
    o.odds_draw_prob_stddev,
    o.odds_away_prob_stddev,
    o.odds_observed_at AS audit_odds_observed_at,
    o.odds_source_updated_at AS audit_odds_source_updated_at,
    rh.world_rank AS home_world_rank,
    ra.world_rank AS away_world_rank,
    rh.rating_points AS home_world_rating_points,
    ra.rating_points AS away_world_rating_points,
    rh.rating_points - ra.rating_points AS world_rating_points_difference,
    ra.world_rank - rh.world_rank AS world_rank_advantage_home,
    rh.ranking_date AS audit_home_world_ranking_date,
    ra.ranking_date AS audit_away_world_ranking_date,
    rh.observed_at AS audit_home_world_ranking_observed_at,
    ra.observed_at AS audit_away_world_ranking_observed_at,
    rh.source_url AS audit_home_world_ranking_source,
    ra.source_url AS audit_away_world_ranking_source
FROM staging.matches m
JOIN curated.fact_match f USING (match_id)
JOIN curated.dim_team ht ON ht.team_id = m.home_team_id
JOIN curated.dim_team at ON at.team_id = m.away_team_id
JOIN curated.team_match_features h ON h.match_id = m.match_id AND h.team_id = m.home_team_id
JOIN curated.team_match_features a ON a.match_id = m.match_id AND a.team_id = m.away_team_id
LEFT JOIN curated.match_context_features c ON c.match_id = m.match_id
LEFT JOIN curated.fact_match_weather w ON w.match_id = m.match_id
    AND (w.forecast_fetched_at IS NULL OR w.forecast_fetched_at < m.utc_kickoff)
LEFT JOIN LATERAL (
    SELECT count(*)::int AS odds_bookmaker_count,
           avg(q.home_prob_fair) AS odds_home_prob_fair,
           avg(q.draw_prob_fair) AS odds_draw_prob_fair,
           avg(q.away_prob_fair) AS odds_away_prob_fair,
           avg(q.overround) AS odds_mean_overround,
           avg(q.home_price) AS odds_home_price_mean,
           avg(q.draw_price) AS odds_draw_price_mean,
           avg(q.away_price) AS odds_away_price_mean,
           stddev_pop(q.home_prob_fair) AS odds_home_prob_stddev,
           stddev_pop(q.draw_prob_fair) AS odds_draw_prob_stddev,
           stddev_pop(q.away_prob_fair) AS odds_away_prob_stddev,
           max(q.first_seen_at) AS odds_observed_at,
           max(q.source_updated_at) AS odds_source_updated_at
      FROM (
          -- Pick each bookmaker's last observable quote including partial
          -- quotes, THEN exclude incomplete markets. A suspended market must
          -- not resurrect an older complete quote.
          SELECT DISTINCT ON (b.bookmaker_key) b.*
            FROM curated.training_bookmaker_quotes b
           WHERE b.match_id = m.match_id AND b.market_key = 'h2h'
             AND b.first_seen_at < m.utc_kickoff
             AND b.source_updated_at < m.utc_kickoff
           ORDER BY b.bookmaker_key, b.source_updated_at DESC, b.first_seen_at DESC, b.odds_id DESC
      ) q WHERE q.is_complete
          -- Apply quality checks AFTER latest selection: a bad current quote
          -- must not silently resurrect an older acceptable quote.
          AND q.home_price BETWEEN 1.01 AND 1000
          AND q.draw_price BETWEEN 1.01 AND 1000
          AND q.away_price BETWEEN 1.01 AND 1000
          AND q.overround BETWEEN -0.02 AND 0.30
) o ON true
LEFT JOIN LATERAL (
    SELECT r.* FROM staging.team_world_ranking r
    WHERE r.team_id = m.home_team_id AND r.observed_at < m.utc_kickoff
      AND r.ranking_date < (m.utc_kickoff AT TIME ZONE 'UTC')::date
      AND (m.utc_kickoff AT TIME ZONE 'UTC')::date - r.ranking_date <= 35
    ORDER BY r.ranking_date DESC, r.observed_at DESC, r.raw_id DESC LIMIT 1
) rh ON true
LEFT JOIN LATERAL (
    SELECT r.* FROM staging.team_world_ranking r
    WHERE r.team_id = m.away_team_id AND r.observed_at < m.utc_kickoff
      AND r.ranking_date < (m.utc_kickoff AT TIME ZONE 'UTC')::date
      AND (m.utc_kickoff AT TIME ZONE 'UTC')::date - r.ranking_date <= 35
    ORDER BY r.ranking_date DESC, r.observed_at DESC, r.raw_id DESC LIMIT 1
) ra ON true;

COMMENT ON VIEW curated.match_training_features IS
    'One row per match; regular-time labels, reconstructed pre-match results, timestamp-safe context/weather/odds. Exclude label_* and audit_* from model inputs.';
COMMENT ON COLUMN curated.match_training_features.label_outcome_90min IS
    'Target HOME_WIN/DRAW/AWAY_WIN after 90 minutes plus stoppage time. Extra time/penalties excluded; NULL without an unambiguous regular-time score.';
COMMENT ON COLUMN curated.match_training_features.label_available IS
    'True only for FINISHED matches with both regular-time goals. Labels are never features.';
COMMENT ON COLUMN curated.match_training_features.audit_feature_version IS
    'Feature definition version. Historical match results are reconstructed using kickoff+3h availability, not archived ingestion-time facts.';
COMMENT ON COLUMN curated.match_training_features.has_full_history_last_10 IS
    'Both teams have ten prior completed matches with regular-time scores across the configured competitions.';
COMMENT ON COLUMN curated.match_training_features.odds_bookmaker_count IS
    'Number of complete latest pre-kickoff 1X2 quotes passing price 1.01-1000 and margin -2% to 30% checks. Zero indicates absent usable coverage.';
COMMENT ON COLUMN curated.match_training_features.home_history_matches IS 'home team: history matches; completed fixtures across available configured competitions. Missing competitions are not inferred.';
COMMENT ON COLUMN curated.match_training_features.audit_home_history_first_kickoff IS 'home team: history first kickoff; completed fixtures across available configured competitions. Missing competitions are not inferred.';
COMMENT ON COLUMN curated.match_training_features.audit_home_history_last_kickoff IS 'home team: history last kickoff; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.audit_home_history_last_available_at IS 'home team: history last available at; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.home_rest_days IS 'home team: rest days; completed fixtures across available configured competitions. Missing competitions are not inferred.';
COMMENT ON COLUMN curated.match_training_features.home_played_last_7_days IS 'home team: played last 7 days; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.home_played_last_14_days IS 'home team: played last 14 days; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.home_played_last_30_days IS 'home team: played last 30 days; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.home_matches_last_3 IS 'home team: matches last 3; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.home_wins_last_3 IS 'home team: wins last 3; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.home_draws_last_3 IS 'home team: draws last 3; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.home_losses_last_3 IS 'home team: losses last 3; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.home_points_last_3 IS 'home team: points last 3; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.home_goals_for_last_3 IS 'home team: goals for last 3; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.home_goals_against_last_3 IS 'home team: goals against last 3; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.home_goal_difference_last_3 IS 'home team: goal difference last 3; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.home_clean_sheets_last_3 IS 'home team: clean sheets last 3; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.home_failed_to_score_last_3 IS 'home team: failed to score last 3; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.home_both_teams_scored_last_3 IS 'home team: both teams scored last 3; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.home_over_2_5_last_3 IS 'home team: over 2 5 last 3; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.home_goals_for_per_match_last_3 IS 'home team: goals for per match last 3; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.home_goals_against_per_match_last_3 IS 'home team: goals against per match last 3; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.home_points_per_match_last_3 IS 'home team: points per match last 3; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.home_win_rate_last_3 IS 'home team: win rate last 3; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.home_matches_last_5 IS 'home team: matches last 5; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.home_wins_last_5 IS 'home team: wins last 5; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.home_draws_last_5 IS 'home team: draws last 5; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.home_losses_last_5 IS 'home team: losses last 5; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.home_points_last_5 IS 'home team: points last 5; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.home_goals_for_last_5 IS 'home team: goals for last 5; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.home_goals_against_last_5 IS 'home team: goals against last 5; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.home_goal_difference_last_5 IS 'home team: goal difference last 5; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.home_clean_sheets_last_5 IS 'home team: clean sheets last 5; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.home_failed_to_score_last_5 IS 'home team: failed to score last 5; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.home_both_teams_scored_last_5 IS 'home team: both teams scored last 5; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.home_over_2_5_last_5 IS 'home team: over 2 5 last 5; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.home_goals_for_per_match_last_5 IS 'home team: goals for per match last 5; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.home_goals_against_per_match_last_5 IS 'home team: goals against per match last 5; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.home_points_per_match_last_5 IS 'home team: points per match last 5; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.home_win_rate_last_5 IS 'home team: win rate last 5; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.home_matches_last_10 IS 'home team: matches last 10; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.home_wins_last_10 IS 'home team: wins last 10; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.home_draws_last_10 IS 'home team: draws last 10; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.home_losses_last_10 IS 'home team: losses last 10; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.home_points_last_10 IS 'home team: points last 10; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.home_goals_for_last_10 IS 'home team: goals for last 10; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.home_goals_against_last_10 IS 'home team: goals against last 10; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.home_goal_difference_last_10 IS 'home team: goal difference last 10; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.home_clean_sheets_last_10 IS 'home team: clean sheets last 10; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.home_failed_to_score_last_10 IS 'home team: failed to score last 10; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.home_both_teams_scored_last_10 IS 'home team: both teams scored last 10; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.home_over_2_5_last_10 IS 'home team: over 2 5 last 10; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.home_goals_for_per_match_last_10 IS 'home team: goals for per match last 10; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.home_goals_against_per_match_last_10 IS 'home team: goals against per match last 10; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.home_points_per_match_last_10 IS 'home team: points per match last 10; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.home_win_rate_last_10 IS 'home team: win rate last 10; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.home_venue_matches_last_5 IS 'home team: venue matches last 5; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.home_venue_points_last_5 IS 'home team: venue points last 5; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.home_venue_wins_last_5 IS 'home team: venue wins last 5; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.home_venue_goals_for_last_5 IS 'home team: venue goals for last 5; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.home_venue_goals_against_last_5 IS 'home team: venue goals against last 5; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.home_venue_clean_sheets_last_5 IS 'home team: venue clean sheets last 5; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.home_venue_points_per_match_last_5 IS 'home team: venue points per match last 5; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.home_competition_matches_last_5 IS 'home team: competition matches last 5; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.home_competition_points_last_5 IS 'home team: competition points last 5; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.home_competition_wins_last_5 IS 'home team: competition wins last 5; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.home_competition_goals_for_last_5 IS 'home team: competition goals for last 5; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.home_competition_goals_against_last_5 IS 'home team: competition goals against last 5; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.home_competition_clean_sheets_last_5 IS 'home team: competition clean sheets last 5; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.home_competition_points_per_match_last_5 IS 'home team: competition points per match last 5; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.home_season_matches IS 'home team: season matches in this competition and season, computed from prior regular-time results only; not the final league table.';
COMMENT ON COLUMN curated.match_training_features.home_season_wins IS 'home team: season wins in this competition and season, computed from prior regular-time results only; not the final league table.';
COMMENT ON COLUMN curated.match_training_features.home_season_draws IS 'home team: season draws in this competition and season, computed from prior regular-time results only; not the final league table.';
COMMENT ON COLUMN curated.match_training_features.home_season_losses IS 'home team: season losses in this competition and season, computed from prior regular-time results only; not the final league table.';
COMMENT ON COLUMN curated.match_training_features.home_season_points IS 'home team: season points in this competition and season, computed from prior regular-time results only; not the final league table.';
COMMENT ON COLUMN curated.match_training_features.home_season_goals_for IS 'home team: season goals for in this competition and season, computed from prior regular-time results only; not the final league table.';
COMMENT ON COLUMN curated.match_training_features.home_season_goals_against IS 'home team: season goals against in this competition and season, computed from prior regular-time results only; not the final league table.';
COMMENT ON COLUMN curated.match_training_features.home_season_goal_difference IS 'home team: season goal difference in this competition and season, computed from prior regular-time results only; not the final league table.';
COMMENT ON COLUMN curated.match_training_features.home_season_points_per_match IS 'home team: season points per match in this competition and season, computed from prior regular-time results only; not the final league table.';
COMMENT ON COLUMN curated.match_training_features.home_h2h_matches_last_5 IS 'home team: h2h matches last 5; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.home_h2h_wins_last_5 IS 'home team: h2h wins last 5; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.home_h2h_draws_last_5 IS 'home team: h2h draws last 5; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.home_h2h_losses_last_5 IS 'home team: h2h losses last 5; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.home_h2h_points_last_5 IS 'home team: h2h points last 5; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.home_h2h_goals_for_last_5 IS 'home team: h2h goals for last 5; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.home_h2h_goals_against_last_5 IS 'home team: h2h goals against last 5; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.home_h2h_points_per_match_last_5 IS 'home team: h2h points per match last 5; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.away_history_matches IS 'away team: history matches; completed fixtures across available configured competitions. Missing competitions are not inferred.';
COMMENT ON COLUMN curated.match_training_features.audit_away_history_first_kickoff IS 'away team: history first kickoff; completed fixtures across available configured competitions. Missing competitions are not inferred.';
COMMENT ON COLUMN curated.match_training_features.audit_away_history_last_kickoff IS 'away team: history last kickoff; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.audit_away_history_last_available_at IS 'away team: history last available at; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.away_rest_days IS 'away team: rest days; completed fixtures across available configured competitions. Missing competitions are not inferred.';
COMMENT ON COLUMN curated.match_training_features.away_played_last_7_days IS 'away team: played last 7 days; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.away_played_last_14_days IS 'away team: played last 14 days; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.away_played_last_30_days IS 'away team: played last 30 days; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.away_matches_last_3 IS 'away team: matches last 3; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.away_wins_last_3 IS 'away team: wins last 3; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.away_draws_last_3 IS 'away team: draws last 3; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.away_losses_last_3 IS 'away team: losses last 3; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.away_points_last_3 IS 'away team: points last 3; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.away_goals_for_last_3 IS 'away team: goals for last 3; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.away_goals_against_last_3 IS 'away team: goals against last 3; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.away_goal_difference_last_3 IS 'away team: goal difference last 3; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.away_clean_sheets_last_3 IS 'away team: clean sheets last 3; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.away_failed_to_score_last_3 IS 'away team: failed to score last 3; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.away_both_teams_scored_last_3 IS 'away team: both teams scored last 3; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.away_over_2_5_last_3 IS 'away team: over 2 5 last 3; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.away_goals_for_per_match_last_3 IS 'away team: goals for per match last 3; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.away_goals_against_per_match_last_3 IS 'away team: goals against per match last 3; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.away_points_per_match_last_3 IS 'away team: points per match last 3; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.away_win_rate_last_3 IS 'away team: win rate last 3; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.away_matches_last_5 IS 'away team: matches last 5; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.away_wins_last_5 IS 'away team: wins last 5; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.away_draws_last_5 IS 'away team: draws last 5; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.away_losses_last_5 IS 'away team: losses last 5; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.away_points_last_5 IS 'away team: points last 5; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.away_goals_for_last_5 IS 'away team: goals for last 5; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.away_goals_against_last_5 IS 'away team: goals against last 5; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.away_goal_difference_last_5 IS 'away team: goal difference last 5; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.away_clean_sheets_last_5 IS 'away team: clean sheets last 5; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.away_failed_to_score_last_5 IS 'away team: failed to score last 5; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.away_both_teams_scored_last_5 IS 'away team: both teams scored last 5; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.away_over_2_5_last_5 IS 'away team: over 2 5 last 5; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.away_goals_for_per_match_last_5 IS 'away team: goals for per match last 5; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.away_goals_against_per_match_last_5 IS 'away team: goals against per match last 5; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.away_points_per_match_last_5 IS 'away team: points per match last 5; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.away_win_rate_last_5 IS 'away team: win rate last 5; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.away_matches_last_10 IS 'away team: matches last 10; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.away_wins_last_10 IS 'away team: wins last 10; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.away_draws_last_10 IS 'away team: draws last 10; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.away_losses_last_10 IS 'away team: losses last 10; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.away_points_last_10 IS 'away team: points last 10; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.away_goals_for_last_10 IS 'away team: goals for last 10; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.away_goals_against_last_10 IS 'away team: goals against last 10; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.away_goal_difference_last_10 IS 'away team: goal difference last 10; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.away_clean_sheets_last_10 IS 'away team: clean sheets last 10; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.away_failed_to_score_last_10 IS 'away team: failed to score last 10; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.away_both_teams_scored_last_10 IS 'away team: both teams scored last 10; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.away_over_2_5_last_10 IS 'away team: over 2 5 last 10; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.away_goals_for_per_match_last_10 IS 'away team: goals for per match last 10; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.away_goals_against_per_match_last_10 IS 'away team: goals against per match last 10; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.away_points_per_match_last_10 IS 'away team: points per match last 10; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.away_win_rate_last_10 IS 'away team: win rate last 10; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.away_venue_matches_last_5 IS 'away team: venue matches last 5; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.away_venue_points_last_5 IS 'away team: venue points last 5; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.away_venue_wins_last_5 IS 'away team: venue wins last 5; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.away_venue_goals_for_last_5 IS 'away team: venue goals for last 5; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.away_venue_goals_against_last_5 IS 'away team: venue goals against last 5; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.away_venue_clean_sheets_last_5 IS 'away team: venue clean sheets last 5; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.away_venue_points_per_match_last_5 IS 'away team: venue points per match last 5; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.away_competition_matches_last_5 IS 'away team: competition matches last 5; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.away_competition_points_last_5 IS 'away team: competition points last 5; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.away_competition_wins_last_5 IS 'away team: competition wins last 5; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.away_competition_goals_for_last_5 IS 'away team: competition goals for last 5; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.away_competition_goals_against_last_5 IS 'away team: competition goals against last 5; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.away_competition_clean_sheets_last_5 IS 'away team: competition clean sheets last 5; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.away_competition_points_per_match_last_5 IS 'away team: competition points per match last 5; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.away_season_matches IS 'away team: season matches in this competition and season, computed from prior regular-time results only; not the final league table.';
COMMENT ON COLUMN curated.match_training_features.away_season_wins IS 'away team: season wins in this competition and season, computed from prior regular-time results only; not the final league table.';
COMMENT ON COLUMN curated.match_training_features.away_season_draws IS 'away team: season draws in this competition and season, computed from prior regular-time results only; not the final league table.';
COMMENT ON COLUMN curated.match_training_features.away_season_losses IS 'away team: season losses in this competition and season, computed from prior regular-time results only; not the final league table.';
COMMENT ON COLUMN curated.match_training_features.away_season_points IS 'away team: season points in this competition and season, computed from prior regular-time results only; not the final league table.';
COMMENT ON COLUMN curated.match_training_features.away_season_goals_for IS 'away team: season goals for in this competition and season, computed from prior regular-time results only; not the final league table.';
COMMENT ON COLUMN curated.match_training_features.away_season_goals_against IS 'away team: season goals against in this competition and season, computed from prior regular-time results only; not the final league table.';
COMMENT ON COLUMN curated.match_training_features.away_season_goal_difference IS 'away team: season goal difference in this competition and season, computed from prior regular-time results only; not the final league table.';
COMMENT ON COLUMN curated.match_training_features.away_season_points_per_match IS 'away team: season points per match in this competition and season, computed from prior regular-time results only; not the final league table.';
COMMENT ON COLUMN curated.match_training_features.away_h2h_matches_last_5 IS 'away team: h2h matches last 5; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.away_h2h_wins_last_5 IS 'away team: h2h wins last 5; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.away_h2h_draws_last_5 IS 'away team: h2h draws last 5; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.away_h2h_losses_last_5 IS 'away team: h2h losses last 5; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.away_h2h_points_last_5 IS 'away team: h2h points last 5; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.away_h2h_goals_for_last_5 IS 'away team: h2h goals for last 5; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.away_h2h_goals_against_last_5 IS 'away team: h2h goals against last 5; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';
COMMENT ON COLUMN curated.match_training_features.away_h2h_points_per_match_last_5 IS 'away team: h2h points per match last 5; only completed matches whose kickoff+3h precedes this fixture. Counts are zero without history; rates are NULL.';

COMMENT ON COLUMN curated.match_training_features.home_world_rank IS
    'FootballDatabase world club rank, lower is better; captured before kickoff and games-through date at most 35 days old. NULL without eligible mapping/snapshot.';
COMMENT ON COLUMN curated.match_training_features.away_world_rank IS
    'FootballDatabase world club rank, lower is better; same capture and 35-day freshness rules as home.';
COMMENT ON COLUMN curated.match_training_features.home_world_rating_points IS
    'FootballDatabase rating points, higher is stronger; not league table points. Source: FootballDatabase.com, CC BY-SA 4.0.';
COMMENT ON COLUMN curated.match_training_features.away_world_rating_points IS
    'FootballDatabase rating points, higher is stronger; not league table points. Source: FootballDatabase.com, CC BY-SA 4.0.';
COMMENT ON COLUMN curated.match_training_features.world_rating_points_difference IS
    'Home rating points minus away rating points. NULL unless both are available.';
COMMENT ON COLUMN curated.match_training_features.world_rank_advantage_home IS
    'Away rank minus home rank; positive means the home team is ranked better.';

COMMENT ON COLUMN curated.match_training_features.audit_home_world_ranking_date IS
    'Games-through date displayed by FootballDatabase; NOT publication time.';
COMMENT ON COLUMN curated.match_training_features.audit_away_world_ranking_date IS
    'Games-through date displayed by FootballDatabase; NOT publication time.';
COMMENT ON COLUMN curated.match_training_features.audit_home_world_ranking_observed_at IS
    'First successful page capture; retained across identical repeat fetches. Must precede kickoff.';
COMMENT ON COLUMN curated.match_training_features.audit_away_world_ranking_observed_at IS
    'First successful page capture; retained across identical repeat fetches. Must precede kickoff.';
