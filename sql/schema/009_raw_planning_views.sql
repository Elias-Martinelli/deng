-- What the ingestion is allowed to look up: two read-only views on the raw zone.
--
-- The rule (tests/test_layering.py enforces it): ingestion may read the APIs,
-- the files under data/ and the raw zone - never staging or curated. Without
-- these views the weather step would have to ask curated.fact_match which
-- matches are coming up, and the transformation would have to run in the middle
-- of the ingestion. With them, every source can be ingested first.
--
-- Both views do the same thing: unpack the JSON answers that are already in the
-- raw zone and keep the newest answer per object.
--   DISTINCT ON (x) ... ORDER BY x, ingestion_date DESC  =  "one row per x,
--   the one from the most recent day we asked".

CREATE OR REPLACE VIEW raw.match_calendar AS
SELECT DISTINCT ON (match_id)
       (m ->> 'id')::bigint                        AS match_id,
       (m ->> 'utcDate')::timestamptz              AS utc_kickoff,
       (m ->> 'utcDate')::timestamptz::date        AS match_date,
       m ->> 'status'                              AS status,
       m ->> 'status' = 'FINISHED'                 AS is_finished,
       (m -> 'homeTeam' ->> 'id')::bigint          AS home_team_id,
       (m -> 'awayTeam' ->> 'id')::bigint          AS away_team_id,
       (m -> 'season' ->> 'id')::bigint            AS season_id,
       r.ingestion_date                            AS ingestion_date
  FROM raw.football_data r
  CROSS JOIN LATERAL jsonb_array_elements(r.payload -> 'matches') AS m
 WHERE r.endpoint LIKE '%/matches'
   AND m -> 'homeTeam' ->> 'id' IS NOT NULL
 ORDER BY match_id, r.ingestion_date DESC, r.ingested_at DESC;

COMMENT ON VIEW raw.match_calendar IS
    'One row per match, from the newest stored football payload. Read by the ingestion to plan weather and odds; the transformation uses staging.matches instead.';

CREATE OR REPLACE VIEW raw.team_catalog AS
SELECT DISTINCT ON (team_id)
       (t ->> 'id')::bigint     AS team_id,
       t ->> 'name'             AS name,
       t ->> 'shortName'        AS short_name,
       t ->> 'tla'              AS tla,
       t ->> 'crest'            AS crest_url,
       t ->> 'venue'            AS venue,
       t -> 'area' ->> 'name'   AS country,
       r.ingestion_date         AS ingestion_date
  FROM raw.football_data r
  CROSS JOIN LATERAL jsonb_array_elements(r.payload -> 'teams') AS t
 WHERE r.endpoint LIKE '%/teams'
   AND t ->> 'id' IS NOT NULL
 ORDER BY team_id, r.ingestion_date DESC, r.ingested_at DESC;

COMMENT ON VIEW raw.team_catalog IS
    'One row per club, from the newest stored teams payload. Read by the ingestion to know which crests and which stadiums to fetch.';
