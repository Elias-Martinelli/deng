-- dim_team: the clubs, as curated.dim_team in PostgreSQL (sql/schema/005).
--
-- A dimension of a few hundred rows: no partitioning (it would only add
-- metadata), clustered by team_id because every fact joins on it.

CREATE TABLE IF NOT EXISTS `{{project}}.{{dataset}}.dim_team` (
    team_id                INT64     NOT NULL,
    name                   STRING,
    short_name             STRING,
    tla                    STRING,
    country                STRING,
    venue                  STRING,
    crest_url              STRING,
    competitions           ARRAY<STRING>,
    has_domestic_coverage  BOOL      NOT NULL,
    updated_at             TIMESTAMP NOT NULL
)
CLUSTER BY team_id
OPTIONS (description = 'Grain: one row per club (team_id). Current description, no history (no SCD).');
