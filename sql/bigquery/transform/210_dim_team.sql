-- dim_team from staging_teams. BigQuery port of sql/transform/210_dim_team.sql.
--
-- has_domestic_coverage: the club also plays a domestic league of the free
-- tier (PL, PD, BL1, SA, FL1, DED, PPL, ELC, BSA). Descriptive only.
-- One row per club, overwritten in place: no history of names or venues is
-- needed by the use case (no slowly changing dimension).

MERGE `{{project}}.{{dataset}}.dim_team` AS target
USING (
    SELECT
        team_id,
        name,
        COALESCE(short_name, name) AS short_name,   -- the app needs a label
        tla,
        area_name AS country,
        venue,
        crest_url,
        competitions,
        EXISTS (
            SELECT 1
            FROM UNNEST(competitions) AS code
            WHERE code IN ('PL', 'PD', 'BL1', 'SA', 'FL1', 'DED', 'PPL', 'ELC', 'BSA')
        ) AS has_domestic_coverage
    FROM `{{project}}.{{dataset}}.staging_teams`
) AS source
ON target.team_id = source.team_id
WHEN MATCHED THEN UPDATE SET
    name = source.name,
    short_name = source.short_name,
    tla = source.tla,
    country = source.country,
    venue = source.venue,
    crest_url = source.crest_url,
    competitions = source.competitions,
    has_domestic_coverage = source.has_domestic_coverage,
    updated_at = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN INSERT (
    team_id, name, short_name, tla, country, venue, crest_url, competitions,
    has_domestic_coverage, updated_at
) VALUES (
    source.team_id, source.name, source.short_name, source.tla, source.country,
    source.venue, source.crest_url, source.competitions, source.has_domestic_coverage,
    CURRENT_TIMESTAMP()
);
