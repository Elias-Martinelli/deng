-- Unpack every fetch of The Odds API that is not staged yet into one row per
-- quoted outcome. No parameter: the raw zone is append-only per fetch, so
-- "everything not yet staged" is the right unit, whatever the logical date.
--
-- Only the h2h market (1X2, regular time including stoppage time) is used. An
-- outcome is HOME or AWAY when its name equals the event's team name exactly,
-- DRAW when it is called "Draw"; anything else is dropped, which leaves that
-- bookmaker's market incomplete - and incomplete is flagged downstream, not
-- silently filled.

INSERT INTO staging.bookmaker_odds AS s (
    raw_id, fetched_at, event_id, commence_time, home_team_name, away_team_name,
    bookmaker_key, bookmaker_title, market_key, source_updated_at,
    outcome_role, outcome_name, price
)
SELECT raw_id, fetched_at, event_id, commence_time, home_team_name, away_team_name,
       bookmaker_key, bookmaker_title, market_key, source_updated_at,
       outcome_role, outcome_name, price
  FROM (
    SELECT r.raw_id,
           r.ingested_at                                  AS fetched_at,
           e.value ->> 'id'                               AS event_id,
           (e.value ->> 'commence_time')::timestamptz     AS commence_time,
           e.value ->> 'home_team'                        AS home_team_name,
           e.value ->> 'away_team'                        AS away_team_name,
           b.value ->> 'key'                              AS bookmaker_key,
           coalesce(b.value ->> 'title', b.value ->> 'key') AS bookmaker_title,
           m.value ->> 'key'                              AS market_key,
           -- The market's own timestamp when present, else the bookmaker's;
           -- the fetch time only as a last resort so the row is never lost.
           coalesce((m.value ->> 'last_update')::timestamptz,
                    (b.value ->> 'last_update')::timestamptz,
                    r.ingested_at)                        AS source_updated_at,
           CASE
               WHEN o.value ->> 'name' = e.value ->> 'home_team' THEN 'HOME'
               WHEN o.value ->> 'name' = e.value ->> 'away_team' THEN 'AWAY'
               WHEN lower(o.value ->> 'name') = 'draw'         THEN 'DRAW'
           END                                            AS outcome_role,
           o.value ->> 'name'                             AS outcome_name,
           (o.value ->> 'price')::numeric                 AS price
      FROM raw.odds_api r
     CROSS JOIN LATERAL jsonb_array_elements(r.payload) AS e(value)
     CROSS JOIN LATERAL jsonb_array_elements(coalesce(e.value -> 'bookmakers', '[]'::jsonb)) AS b(value)
     CROSS JOIN LATERAL jsonb_array_elements(coalesce(b.value -> 'markets', '[]'::jsonb)) AS m(value)
     CROSS JOIN LATERAL jsonb_array_elements(coalesce(m.value -> 'outcomes', '[]'::jsonb)) AS o(value)
     WHERE jsonb_typeof(r.payload) = 'array'
       AND m.value ->> 'key' = 'h2h'
       AND NOT EXISTS (SELECT 1 FROM staging.bookmaker_odds x WHERE x.raw_id = r.raw_id)
  ) AS unpacked
 WHERE outcome_role IS NOT NULL
   AND event_id IS NOT NULL
   AND commence_time IS NOT NULL
   AND price >= 1
-- The same outcome twice in one payload (never observed) keeps the first.
ON CONFLICT DO NOTHING;
