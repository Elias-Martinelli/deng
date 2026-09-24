-- fact_bookmaker_odds: one row per odds change, per match, bookmaker and
-- market. No parameter - like the staging step it works on the whole history.
--
-- A "change" is a distinct (source timestamp, home, draw, away) quote. Fetches
-- that show the same quote again only widen its [first_seen_at, last_seen_at]
-- window; a new quote adds a row. That records every change the bookmaker
-- published together with when we first and last saw it - the two timestamps
-- the comparison needs, kept apart.
--
-- Fair probabilities remove the bookmaker's margin using the three prices of
-- the same bookmaker at the same moment: p_i = (1/price_i) / sum(1/price).
-- Mixing bookmakers, or a home price from 14:05 with a draw price from 14:20,
-- would produce probabilities that never existed anywhere. A market with fewer
-- than three outcomes gets no probabilities and is_complete = false.
--
-- Recomputed over all staged rows every run: the upsert makes that idempotent,
-- and at a few million rows it is one aggregate scan. Only events resolved to
-- a fixture (odds_event_match.match_id) reach the curated layer; the rest stay
-- visible in staging and in a WARNING check.

WITH quotes AS (
    SELECT s.fetched_at, s.event_id, s.bookmaker_key, s.bookmaker_title, s.market_key,
           s.source_updated_at,
           max(s.price) FILTER (WHERE s.outcome_role = 'HOME') AS home_price,
           max(s.price) FILTER (WHERE s.outcome_role = 'DRAW') AS draw_price,
           max(s.price) FILTER (WHERE s.outcome_role = 'AWAY') AS away_price
      FROM staging.bookmaker_odds s
     GROUP BY 1, 2, 3, 4, 5, 6
),
changes AS (
    SELECT x.match_id, q.bookmaker_key, q.market_key, q.source_updated_at,
           q.home_price, q.draw_price, q.away_price,
           min(q.fetched_at) AS first_seen_at,
           max(q.fetched_at) AS last_seen_at,
           (array_agg(q.bookmaker_title ORDER BY q.fetched_at DESC))[1] AS bookmaker_title
      FROM quotes q
      JOIN staging.odds_event_match x ON x.event_id = q.event_id AND x.match_id IS NOT NULL
      JOIN curated.fact_match m ON m.match_id = x.match_id
     GROUP BY 1, 2, 3, 4, 5, 6, 7
),
priced AS (
    SELECT c.*,
           (c.home_price IS NOT NULL AND c.draw_price IS NOT NULL AND c.away_price IS NOT NULL)
               AS is_complete,
           CASE WHEN c.home_price IS NOT NULL AND c.draw_price IS NOT NULL
                 AND c.away_price IS NOT NULL
                THEN 1 / c.home_price + 1 / c.draw_price + 1 / c.away_price
           END AS implied_total
      FROM changes c
)
INSERT INTO curated.fact_bookmaker_odds AS f (
    match_id, bookmaker_key, bookmaker_title, market_key, source_updated_at,
    first_seen_at, last_seen_at, home_price, draw_price, away_price,
    is_complete, overround, home_prob_fair, draw_prob_fair, away_prob_fair
)
SELECT
    p.match_id, p.bookmaker_key, p.bookmaker_title, p.market_key, p.source_updated_at,
    p.first_seen_at, p.last_seen_at, p.home_price, p.draw_price, p.away_price,
    p.is_complete,
    round(p.implied_total - 1, 5),
    round((1 / p.home_price) / p.implied_total, 5),
    round((1 / p.draw_price) / p.implied_total, 5),
    round((1 / p.away_price) / p.implied_total, 5)
FROM priced p
ON CONFLICT ON CONSTRAINT bookmaker_odds_one_row_per_change DO UPDATE SET
    bookmaker_title = EXCLUDED.bookmaker_title,
    first_seen_at = least(f.first_seen_at, EXCLUDED.first_seen_at),
    last_seen_at = greatest(f.last_seen_at, EXCLUDED.last_seen_at),
    updated_at = now();
