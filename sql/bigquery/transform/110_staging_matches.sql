-- Unpack the football answers into one typed row per match.
-- BigQuery port of sql/transform/110_staging_matches.sql; same rules:
--
-- * Every match answer of the logical date, plus every past-season answer
--   (?season=2023) stored up to that date - a finished season is fetched once.
-- * A match can appear in several answers (sample and real, overlapping
--   seasons); the newest by lastUpdated, then by day and receipt, wins.
-- * Written as staging state of @logical_date, and only over a row that is not
--   newer: a rerun of an older date cannot stamp stale values over fresh ones.
--
-- MERGE, not INSERT: running it twice for the same day changes nothing.
-- Parameter: @logical_date (DATE).

MERGE `{{project}}.{{dataset}}.staging_matches` AS target
USING (
    WITH answers AS (
        SELECT
            r.payload,
            r.ingestion_date AS answered_on,
            TIMESTAMP(r.ingested_at) AS received_at,
            JSON_VALUE(r.request.params, '$.season') IS NOT NULL AS is_past_season
        FROM `{{project}}.{{dataset}}.raw_answers` AS r
        -- Partition columns first: they decide which objects are read at all.
        WHERE r.source IN ('football-data.org', 'football-data.org-sample')
          AND r.ingestion_date <= @logical_date
          AND ENDS_WITH(r.request.endpoint, '/matches')
    ),
    unpacked AS (
        SELECT
            CAST(JSON_VALUE(m, '$.id') AS INT64) AS match_id,
            CAST(JSON_VALUE(m, '$.season.id') AS INT64) AS season_id,
            JSON_VALUE(m, '$.competition.code') AS competition_code,
            -- "2026-10-13T16:45:00Z"; the Z is spelled as an offset for TIMESTAMP().
            TIMESTAMP(REPLACE(JSON_VALUE(m, '$.utcDate'), 'Z', '+00:00')) AS utc_kickoff,
            JSON_VALUE(m, '$.status') AS status,
            JSON_VALUE(m, '$.stage') AS stage,
            CAST(JSON_VALUE(m, '$.matchday') AS INT64) AS matchday,
            CAST(JSON_VALUE(m, '$.homeTeam.id') AS INT64) AS home_team_id,
            CAST(JSON_VALUE(m, '$.awayTeam.id') AS INT64) AS away_team_id,
            -- NULL until the match is played: JSON null gives SQL NULL.
            CAST(JSON_VALUE(m, '$.score.fullTime.home') AS INT64) AS home_goals,
            CAST(JSON_VALUE(m, '$.score.fullTime.away') AS INT64) AS away_goals,
            CAST(JSON_VALUE(m, '$.score.halfTime.home') AS INT64) AS home_goals_ht,
            CAST(JSON_VALUE(m, '$.score.halfTime.away') AS INT64) AS away_goals_ht,
            -- fullTime can include extra time; the prediction label is 90 minutes.
            COALESCE(
                CAST(JSON_VALUE(m, '$.score.regularTime.home') AS INT64),
                IF(JSON_VALUE(m, '$.score.duration') = 'REGULAR',
                   CAST(JSON_VALUE(m, '$.score.fullTime.home') AS INT64), NULL)
            ) AS home_goals_90min,
            COALESCE(
                CAST(JSON_VALUE(m, '$.score.regularTime.away') AS INT64),
                IF(JSON_VALUE(m, '$.score.duration') = 'REGULAR',
                   CAST(JSON_VALUE(m, '$.score.fullTime.away') AS INT64), NULL)
            ) AS away_goals_90min,
            JSON_VALUE(m, '$.score.winner') AS winner,
            JSON_VALUE(m, '$.score.duration') AS duration,
            TIMESTAMP(REPLACE(JSON_VALUE(m, '$.lastUpdated'), 'Z', '+00:00')) AS last_updated,
            a.answered_on,
            a.received_at
        FROM answers AS a
        CROSS JOIN UNNEST(JSON_QUERY_ARRAY(a.payload, '$.matches')) AS m
        WHERE a.answered_on = @logical_date OR a.is_past_season
    ),
    ranked AS (
        SELECT
            *,
            ROW_NUMBER() OVER (
                PARTITION BY match_id
                ORDER BY last_updated DESC, answered_on DESC, received_at DESC
            ) AS newest
        FROM unpacked
        -- A match without both teams cannot be modelled; skipped, and the
        -- verification query reports the gap instead of the run failing.
        WHERE home_team_id IS NOT NULL AND away_team_id IS NOT NULL
    )
    SELECT * EXCEPT (newest, answered_on, received_at), @logical_date AS ingestion_date
    FROM ranked
    WHERE newest = 1
) AS source
ON target.match_id = source.match_id
WHEN MATCHED AND source.ingestion_date >= target.ingestion_date THEN UPDATE SET
    season_id = source.season_id,
    competition_code = source.competition_code,
    utc_kickoff = source.utc_kickoff,
    status = source.status,
    stage = source.stage,
    matchday = source.matchday,
    home_team_id = source.home_team_id,
    away_team_id = source.away_team_id,
    home_goals = source.home_goals,
    away_goals = source.away_goals,
    home_goals_ht = source.home_goals_ht,
    away_goals_ht = source.away_goals_ht,
    home_goals_90min = source.home_goals_90min,
    away_goals_90min = source.away_goals_90min,
    winner = source.winner,
    duration = source.duration,
    last_updated = source.last_updated,
    ingestion_date = source.ingestion_date,
    loaded_at = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN INSERT (
    match_id, season_id, competition_code, utc_kickoff, status, stage, matchday,
    home_team_id, away_team_id, home_goals, away_goals, home_goals_ht, away_goals_ht,
    home_goals_90min, away_goals_90min, winner, duration, last_updated,
    ingestion_date, loaded_at
) VALUES (
    source.match_id, source.season_id, source.competition_code, source.utc_kickoff,
    source.status, source.stage, source.matchday, source.home_team_id, source.away_team_id,
    source.home_goals, source.away_goals, source.home_goals_ht, source.away_goals_ht,
    source.home_goals_90min, source.away_goals_90min, source.winner, source.duration,
    source.last_updated, source.ingestion_date, CURRENT_TIMESTAMP()
);
