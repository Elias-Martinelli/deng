-- fact_match_prediction: the baseline model's HOME / DRAW / AWAY probabilities.
-- Parameter: %(logical_date)s - the run date the forecast is stamped with.
--
-- Model "form-poisson-v1", deliberately simple and fully in SQL so it can be
-- read, defended and re-run by hand. Goals of each side are Poisson with
--
--     lambda_home = mu_home * attack_home * defence_away
--     lambda_away = mu_away * attack_away * defence_home
--
-- mu_home / mu_away: the league's average home and away goals per match, from
-- matches finished *before this match's kick-off*, shrunk towards a prior
-- (1.55 / 1.25, roughly the Champions League long-run figures) with the
-- weight of 20 matches, so the first matchday does not run on 6 matches alone.
--
-- attack / defence: the team's goals scored / conceded per match in its last-5
-- window (curated.fact_team_match_form - already point-in-time correct),
-- divided by the league average and shrunk towards 1 with the weight of 3
-- matches. A team with no completed match has strength 1 = league average.
--
-- The three probabilities are sums over the 0..10 x 0..10 score grid, then
-- normalised so the truncated tail does not leave them short of 1.
--
-- Point-in-time correctness: every input is restricted to matches finished
-- before the kick-off of the match being predicted, so a forecast computed for
-- a finished match is still built from pre-match information only. Whether it
-- was *computed* before kick-off is a separate fact, stored as is_pre_match.

WITH params AS (
    SELECT 1.55::numeric AS prior_home_goals,
           1.25::numeric AS prior_away_goals,
           20::numeric   AS prior_matches,
           3::numeric    AS shrink_matches,
           10            AS max_goals
),
league AS (
    SELECT m.match_id,
           l.n AS league_matches_considered,
           (l.home_goals + p.prior_matches * p.prior_home_goals) / (l.n + p.prior_matches) AS mu_home,
           (l.away_goals + p.prior_matches * p.prior_away_goals) / (l.n + p.prior_matches) AS mu_away
      FROM curated.fact_match m
     CROSS JOIN params p
     CROSS JOIN LATERAL (
         SELECT count(*)                          AS n,
                coalesce(sum(f.home_goals), 0)    AS home_goals,
                coalesce(sum(f.away_goals), 0)    AS away_goals
           FROM curated.fact_match f
          WHERE f.is_finished
            AND f.home_goals IS NOT NULL AND f.away_goals IS NOT NULL
            AND f.utc_kickoff < m.utc_kickoff          -- the leakage guard
     ) AS l
),
strength AS (
    SELECT m.match_id, m.utc_kickoff,
           lg.league_matches_considered, lg.mu_home, lg.mu_away,
           fh.matches_considered AS home_n,
           fa.matches_considered AS away_n,
           (fh.goals_scored_last_5   + p.shrink_matches * mu.avg)
               / ((fh.matches_considered + p.shrink_matches) * mu.avg) AS home_att,
           (fh.goals_conceded_last_5 + p.shrink_matches * mu.avg)
               / ((fh.matches_considered + p.shrink_matches) * mu.avg) AS home_def,
           (fa.goals_scored_last_5   + p.shrink_matches * mu.avg)
               / ((fa.matches_considered + p.shrink_matches) * mu.avg) AS away_att,
           (fa.goals_conceded_last_5 + p.shrink_matches * mu.avg)
               / ((fa.matches_considered + p.shrink_matches) * mu.avg) AS away_def
      FROM curated.fact_match m
      JOIN league lg ON lg.match_id = m.match_id
     CROSS JOIN LATERAL (SELECT (lg.mu_home + lg.mu_away) / 2 AS avg) AS mu
      JOIN curated.fact_team_match_form fh
        ON fh.match_id = m.match_id AND fh.team_id = m.home_team_id
      JOIN curated.fact_team_match_form fa
        ON fa.match_id = m.match_id AND fa.team_id = m.away_team_id
     CROSS JOIN params p
),
rates AS (
    -- Clamped: a 0.2..6 goals-per-match range covers every plausible fixture and
    -- keeps a data error (a 15:0 in the form window) from producing nonsense.
    SELECT s.*,
           least(greatest(s.mu_home * s.home_att * s.away_def, 0.2), 6) AS lambda_home,
           least(greatest(s.mu_away * s.away_att * s.home_def, 0.2), 6) AS lambda_away
      FROM strength s
),
grid AS (
    SELECT r.match_id, i.g AS home_goals, j.g AS away_goals,
           exp(-r.lambda_home) * power(r.lambda_home, i.g) / factorial(i.g)
         * exp(-r.lambda_away) * power(r.lambda_away, j.g) / factorial(j.g) AS p
      FROM rates r
     CROSS JOIN params pr
     CROSS JOIN LATERAL generate_series(0, pr.max_goals) AS i(g)
     CROSS JOIN LATERAL generate_series(0, pr.max_goals) AS j(g)
),
outcome AS (
    SELECT match_id,
           sum(p) FILTER (WHERE home_goals > away_goals) / sum(p) AS home_prob,
           sum(p) FILTER (WHERE home_goals = away_goals) / sum(p) AS draw_prob,
           sum(p) FILTER (WHERE home_goals < away_goals) / sum(p) AS away_prob
      FROM grid
     GROUP BY match_id
)
INSERT INTO curated.fact_match_prediction AS t (
    match_id, model_version, as_of_date, predicted_at, is_pre_match,
    home_prob, draw_prob, away_prob, expected_home_goals, expected_away_goals,
    home_matches_considered, away_matches_considered, league_matches_considered
)
SELECT
    r.match_id,
    'form-poisson-v1',
    %(logical_date)s,
    now(),
    now() < r.utc_kickoff,
    round(o.home_prob, 5),
    round(o.draw_prob, 5),
    round(o.away_prob, 5),
    round(r.lambda_home, 3),
    round(r.lambda_away, 3),
    r.home_n,
    r.away_n,
    r.league_matches_considered
FROM rates r
JOIN outcome o ON o.match_id = r.match_id
-- A rerun of the same day replaces that day's forecast; a new day adds one.
ON CONFLICT (match_id, model_version, as_of_date) DO UPDATE SET
    predicted_at = now(),
    is_pre_match = EXCLUDED.is_pre_match,
    home_prob = EXCLUDED.home_prob,
    draw_prob = EXCLUDED.draw_prob,
    away_prob = EXCLUDED.away_prob,
    expected_home_goals = EXCLUDED.expected_home_goals,
    expected_away_goals = EXCLUDED.expected_away_goals,
    home_matches_considered = EXCLUDED.home_matches_considered,
    away_matches_considered = EXCLUDED.away_matches_considered,
    league_matches_considered = EXCLUDED.league_matches_considered;
