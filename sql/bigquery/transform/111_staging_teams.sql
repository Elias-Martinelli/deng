-- Unpack the teams answers into one typed row per club.
-- BigQuery port of sql/transform/111_staging_teams.sql; same rules:
--
-- * The competition teams lists (competitions/XX/teams) and the single-team
--   answers (teams/86) of the logical date, plus past-season lists up to it.
-- * A club in several answers: the current season wins over past ones, then
--   the newest day and receipt.
-- * Only over a row that is not newer (same guard as staging_matches).
--
-- Parameter: @logical_date (DATE).

MERGE `{{project}}.{{dataset}}.staging_teams` AS target
USING (
    WITH answers AS (
        SELECT
            r.payload,
            r.request.endpoint AS endpoint_path,
            r.ingestion_date AS answered_on,
            TIMESTAMP(r.ingested_at) AS received_at,
            JSON_VALUE(r.request.params, '$.season') IS NOT NULL AS is_past_season
        FROM `{{project}}.{{dataset}}.raw_answers` AS r
        WHERE r.source IN ('football-data.org', 'football-data.org-sample')
          AND r.ingestion_date <= @logical_date
          AND (ENDS_WITH(r.request.endpoint, '/teams') OR STARTS_WITH(r.request.endpoint, 'teams/'))
    ),
    unpacked AS (
        SELECT
            CAST(JSON_VALUE(club, '$.id') AS INT64) AS team_id,
            JSON_VALUE(club, '$.name') AS name,
            JSON_VALUE(club, '$.shortName') AS short_name,
            JSON_VALUE(club, '$.tla') AS tla,
            JSON_VALUE(club, '$.crest') AS crest_url,
            CAST(JSON_VALUE(club, '$.founded') AS INT64) AS founded,
            JSON_VALUE(club, '$.clubColors') AS club_colors,
            JSON_VALUE(club, '$.venue') AS venue,
            JSON_VALUE(club, '$.website') AS website,
            JSON_VALUE(club, '$.area.name') AS area_name,
            -- Sorted, so the same set always compares equal; [] for "none".
            ARRAY(
                SELECT JSON_VALUE(competition, '$.code') AS code
                FROM UNNEST(JSON_QUERY_ARRAY(club, '$.runningCompetitions')) AS competition
                WHERE JSON_VALUE(competition, '$.code') IS NOT NULL
                ORDER BY code
            ) AS competitions,
            a.is_past_season,
            a.answered_on,
            a.received_at
        FROM answers AS a
        -- teams/86 is one club, competitions/XX/teams a list of them.
        CROSS JOIN UNNEST(
            IF(STARTS_WITH(a.endpoint_path, 'teams/'),
               [a.payload],
               JSON_QUERY_ARRAY(a.payload, '$.teams'))
        ) AS club
        WHERE a.answered_on = @logical_date OR a.is_past_season
    ),
    ranked AS (
        SELECT
            *,
            ROW_NUMBER() OVER (
                PARTITION BY team_id
                ORDER BY is_past_season, answered_on DESC, received_at DESC
            ) AS newest
        FROM unpacked
        WHERE team_id IS NOT NULL
    )
    SELECT
        * EXCEPT (newest, is_past_season, answered_on, received_at),
        @logical_date AS ingestion_date
    FROM ranked
    WHERE newest = 1
) AS source
ON target.team_id = source.team_id
WHEN MATCHED AND source.ingestion_date >= target.ingestion_date THEN UPDATE SET
    name = source.name,
    short_name = source.short_name,
    tla = source.tla,
    crest_url = source.crest_url,
    founded = source.founded,
    club_colors = source.club_colors,
    venue = source.venue,
    website = source.website,
    area_name = source.area_name,
    competitions = source.competitions,
    ingestion_date = source.ingestion_date,
    loaded_at = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN INSERT (
    team_id, name, short_name, tla, crest_url, founded, club_colors, venue, website,
    area_name, competitions, ingestion_date, loaded_at
) VALUES (
    source.team_id, source.name, source.short_name, source.tla, source.crest_url,
    source.founded, source.club_colors, source.venue, source.website, source.area_name,
    source.competitions, source.ingestion_date, CURRENT_TIMESTAMP()
);
