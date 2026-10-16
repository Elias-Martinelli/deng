-- A fetch for Portugal must not mark EPL/CL prices as withdrawn.
-- Include empty newer fetches of the SAME endpoint, source and parameters,
-- so actual withdrawal of an event is still detected.
CREATE OR REPLACE VIEW curated.bookmaker_odds_latest AS
WITH match_scopes AS (
    SELECT DISTINCT x.match_id, r.source, r.endpoint, r.request_params
      FROM staging.bookmaker_odds s
      JOIN staging.odds_event_match x USING (event_id)
      JOIN raw.odds_api r USING (raw_id)
     WHERE x.match_id IS NOT NULL
), latest_fetch AS (
    SELECT scope.match_id, max(r.ingested_at) AS latest_fetch_at
      FROM match_scopes scope
      JOIN raw.odds_api r ON r.source = scope.source AND r.endpoint = scope.endpoint
                        AND r.request_params = scope.request_params
     GROUP BY scope.match_id
)
SELECT DISTINCT ON (o.match_id, o.bookmaker_key, o.market_key)
       o.odds_id, o.match_id, o.bookmaker_key, o.bookmaker_title, o.market_key,
       o.source_updated_at, o.first_seen_at, o.last_seen_at,
       o.home_price, o.draw_price, o.away_price, o.is_complete, o.overround,
       o.home_prob_fair, o.draw_prob_fair, o.away_prob_fair,
       f.latest_fetch_at,
       o.last_seen_at >= f.latest_fetch_at AS is_current
  FROM curated.fact_bookmaker_odds o
 JOIN latest_fetch f ON f.match_id = o.match_id
 ORDER BY o.match_id, o.bookmaker_key, o.market_key, o.last_seen_at DESC, o.source_updated_at DESC;
