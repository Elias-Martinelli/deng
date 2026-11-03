-- Unpack the standings payload into one row per team and ingestion date.
-- Parameter: %(logical_date)s
--
-- The league phase has exactly one table (`standings[0].table`); the older
-- group format had one per group. Iterating over all of them keeps the
-- transformation valid for historical seasons too.
--
-- Unlike teams and matches, the ingestion date is part of the key: every day's
-- table is kept, which turns the standings into a time series ("position on
-- 20 October"). Hence no "only if newer" guard - a backfill writes its own
-- day's row and cannot touch another day's.

WITH payload AS (
    SELECT DISTINCT ON (endpoint, request_params) payload, ingested_at
      FROM raw.football_data
     WHERE endpoint LIKE '%%/standings'
       AND ingestion_date = %(logical_date)s
     ORDER BY endpoint, request_params, ingested_at DESC
),
-- Two levels of nesting: standings[] (one per group or phase) -> table[] (rows).
tables AS (
    SELECT (payload -> 'season' ->> 'id')::bigint AS season_id,
           ingested_at, jsonb_array_elements(payload -> 'standings') AS grp
      FROM payload
),
rows_ AS (
    SELECT season_id, ingested_at, jsonb_array_elements(grp -> 'table') AS r
      FROM tables
     WHERE grp ->> 'type' = 'TOTAL'
),
latest AS (
    SELECT DISTINCT ON (season_id, (r -> 'team' ->> 'id')::bigint) season_id, r
      FROM rows_
     ORDER BY season_id, (r -> 'team' ->> 'id')::bigint, ingested_at DESC
)
INSERT INTO staging.standings AS s (
    season_id, team_id, position, played_games, won, draw, lost,
    points, goals_for, goals_against, goal_difference, ingestion_date
)
SELECT
    season_id,
    (r -> 'team' ->> 'id')::bigint,
    (r ->> 'position')::int,
    (r ->> 'playedGames')::int,
    (r ->> 'won')::int,
    (r ->> 'draw')::int,
    (r ->> 'lost')::int,
    (r ->> 'points')::int,
    (r ->> 'goalsFor')::int,
    (r ->> 'goalsAgainst')::int,
    (r ->> 'goalDifference')::int,
    %(logical_date)s
FROM latest
WHERE r -> 'team' ->> 'id' IS NOT NULL
ON CONFLICT (season_id, team_id, ingestion_date) DO UPDATE SET
    position = EXCLUDED.position,
    played_games = EXCLUDED.played_games,
    won = EXCLUDED.won,
    draw = EXCLUDED.draw,
    lost = EXCLUDED.lost,
    points = EXCLUDED.points,
    goals_for = EXCLUDED.goals_for,
    goals_against = EXCLUDED.goals_against,
    goal_difference = EXCLUDED.goal_difference,
    loaded_at = now();
