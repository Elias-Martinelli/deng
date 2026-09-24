-- What a model would be trained on: one row per match, label plus features.
--
-- A view, not a table: it only selects and joins what the curated tables
-- already hold, so there is nothing to keep in sync. The snapshot table
-- planned for the final milestone will replace it with one row per match *per
-- day*, which is what makes "what was known N days before kick-off" queryable.
--
-- Every feature here is point-in-time correct by construction, because the
-- tables it reads are:
--   * the form counts only matches finished before this kick-off (230),
--   * the weather is the newest forecast fetched before kick-off (330),
--   * the odds are the newest quote seen before kick-off (420),
--   * the baseline forecast uses the form table only (240).
-- The label (outcome) is NULL until the match has been played, which is how a
-- training set and the upcoming fixtures are told apart.

CREATE OR REPLACE VIEW curated.model_features AS
SELECT
    m.match_id,
    m.season_id,
    m.match_date,
    m.utc_kickoff,
    m.matchday,
    m.is_finished,
    h.name                          AS home_team,
    a.name                          AS away_team,
    -- label
    m.outcome,
    m.home_goals,
    m.away_goals,
    -- features: form of both sides going into this match
    fh.matches_considered           AS home_form_matches,
    fh.points_last_5                AS home_form_points,
    fh.goals_scored_last_5          AS home_goals_scored_last_5,
    fh.goals_conceded_last_5        AS home_goals_conceded_last_5,
    fh.days_since_last_match        AS home_rest_days,
    fa.matches_considered           AS away_form_matches,
    fa.points_last_5                AS away_form_points,
    fa.goals_scored_last_5          AS away_goals_scored_last_5,
    fa.goals_conceded_last_5        AS away_goals_conceded_last_5,
    fa.days_since_last_match        AS away_rest_days,
    -- features: weather at the kick-off hour, with the reason when absent
    w.weather_status,
    w.temperature_c,
    w.precipitation_probability,
    w.wind_speed_kmh,
    w.lead_days                     AS weather_lead_days,
    -- benchmark: our own baseline forecast (newest per match)
    p.home_prob                     AS model_prob_home,
    p.draw_prob                     AS model_prob_draw,
    p.away_prob                     AS model_prob_away,
    -- benchmark: what the market thought, margin removed
    o.fair_prob_home,
    o.fair_prob_draw,
    o.fair_prob_away,
    o.bookmaker_count
FROM curated.fact_match m
JOIN curated.dim_team h ON h.team_id = m.home_team_id
JOIN curated.dim_team a ON a.team_id = m.away_team_id
LEFT JOIN curated.fact_team_match_form fh
       ON fh.match_id = m.match_id AND fh.team_id = m.home_team_id
LEFT JOIN curated.fact_team_match_form fa
       ON fa.match_id = m.match_id AND fa.team_id = m.away_team_id
LEFT JOIN curated.fact_match_weather w ON w.match_id = m.match_id
LEFT JOIN curated.match_prediction_latest p ON p.match_id = m.match_id
LEFT JOIN LATERAL (
    -- The newest quote per match across bookmakers, margin removed: one row.
    SELECT avg(b.home_prob_fair) AS fair_prob_home,
           avg(b.draw_prob_fair) AS fair_prob_draw,
           avg(b.away_prob_fair) AS fair_prob_away,
           count(DISTINCT b.bookmaker_key) AS bookmaker_count
      FROM curated.bookmaker_odds_latest b
     WHERE b.match_id = m.match_id
) o ON TRUE;

COMMENT ON VIEW curated.model_features IS
    'Grain: one row per match. Label (outcome) plus the features known before kick-off. The dashboard reads this; a model would too.';
