-- Verification: bookmaker odds and the model forecast they are compared with.
-- Same convention as 010: one row per check, a boolean `passed`.
-- Every check passes on an empty odds zone too - the odds source is optional.

SELECT
    'model forecast for every match'              AS check_name,
    count(*)::text || ' match(es) without one'    AS observed,
    count(*) = 0                                  AS passed
FROM curated.fact_match m
WHERE NOT EXISTS (SELECT 1 FROM curated.match_prediction_latest p WHERE p.match_id = m.match_id)

UNION ALL

-- The key is never stored: neither in the URL nor in the parameters.
SELECT
    'no API key in the raw zone',
    count(*)::text,
    count(*) = 0
FROM raw.odds_api
WHERE request_url ILIKE '%apiKey=%' OR request_params ? 'apiKey'

UNION ALL

SELECT
    'every fetch is staged',
    count(*)::text || ' fetch(es) not staged',
    count(*) = 0
FROM raw.odds_api r
WHERE r.event_count > 0
  AND NOT EXISTS (SELECT 1 FROM staging.bookmaker_odds s WHERE s.raw_id = r.raw_id)

UNION ALL

SELECT
    'bookmaker events resolved to fixtures',
    count(*) FILTER (WHERE match_id IS NOT NULL)::text || ' of ' || count(*)::text,
    count(*) FILTER (WHERE match_id IS NULL) = 0
FROM staging.odds_event_match

UNION ALL

SELECT
    'fair probabilities add up per bookmaker quote',
    count(*)::text,
    count(*) = 0
FROM curated.fact_bookmaker_odds
WHERE is_complete AND abs(home_prob_fair + draw_prob_fair + away_prob_fair - 1) >= 0.001

UNION ALL

SELECT
    'newest odds fetch',
    coalesce(to_char(max(ingested_at), 'YYYY-MM-DD HH24:MI') || ' ('
             || coalesce(max(requests_remaining)::text, 'unknown') || ' credits left)', 'none'),
    true
FROM raw.odds_api;
