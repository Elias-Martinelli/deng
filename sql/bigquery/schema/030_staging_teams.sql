-- staging_teams: one typed row per club, the current state.
-- Same grain and columns as staging.teams in PostgreSQL (sql/schema/004);
-- `competitions` is an ARRAY<STRING> where PostgreSQL has TEXT[].
--
-- Clustered by team_id for the MERGE, not partitioned: a few hundred clubs.

CREATE TABLE IF NOT EXISTS `{{project}}.{{dataset}}.staging_teams` (
    team_id         INT64     NOT NULL,
    name            STRING,
    short_name      STRING,
    tla             STRING,
    crest_url       STRING,
    founded         INT64,
    club_colors     STRING,
    venue           STRING,
    website         STRING,
    area_name       STRING,
    competitions    ARRAY<STRING>,
    ingestion_date  DATE      NOT NULL,
    loaded_at       TIMESTAMP NOT NULL
)
CLUSTER BY team_id
OPTIONS (description = 'Grain: one row per club (team_id), the newest description up to the logical date.');
