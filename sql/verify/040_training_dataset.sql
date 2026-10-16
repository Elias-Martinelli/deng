
-- Structural verification of the complete training handoff.
SELECT 'one row per canonical match' AS check_name,
       count(*)::text AS observed,
       count(*) = (SELECT count(*) FROM curated.fact_match)
           AND count(*) = count(DISTINCT match_id) AS passed
FROM curated.match_training_features
UNION ALL
SELECT 'regular-time labels are available', count(label_outcome_90min)::text,
       count(*) > 0
FROM curated.match_training_features
UNION ALL
SELECT 'no future history', count(*)::text, count(*) = 0
FROM curated.team_match_features t JOIN curated.fact_match m USING(match_id)
WHERE t.history_last_available_at >= m.utc_kickoff
UNION ALL
SELECT 'no future observed context or odds', count(*)::text, count(*) = 0
FROM curated.match_training_features
WHERE audit_home_context_observed_at >= utc_kickoff
   OR audit_away_context_observed_at >= utc_kickoff
   OR audit_odds_observed_at >= utc_kickoff
   OR audit_odds_source_updated_at >= utc_kickoff;
