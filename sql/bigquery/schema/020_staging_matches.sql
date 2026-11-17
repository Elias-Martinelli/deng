-- staging_matches: one typed row per match, the current state.
-- Same grain and columns as staging.matches in PostgreSQL (sql/schema/004).
--
-- Not partitioned, clustered by match_id: a few thousand rows per season are
-- far below the size where partitions pay off (BigQuery recommends about 1 GB
-- per partition), while every write is a MERGE on match_id, which clustering
-- lets BigQuery match without reading the whole table.

CREATE TABLE IF NOT EXISTS `{{project}}.{{dataset}}.staging_matches` (
    match_id          INT64     NOT NULL,
    season_id         INT64     NOT NULL,
    competition_code  STRING    NOT NULL,
    utc_kickoff       TIMESTAMP NOT NULL,
    status            STRING    NOT NULL,
    stage             STRING    NOT NULL,
    matchday          INT64,
    home_team_id      INT64     NOT NULL,
    away_team_id      INT64     NOT NULL,
    home_goals        INT64,
    away_goals        INT64,
    home_goals_ht     INT64,
    away_goals_ht     INT64,
    home_goals_90min  INT64,
    away_goals_90min  INT64,
    winner            STRING,
    duration          STRING,
    last_updated      TIMESTAMP,
    ingestion_date    DATE      NOT NULL,
    loaded_at         TIMESTAMP NOT NULL
)
CLUSTER BY match_id
OPTIONS (description = 'Grain: one row per match (match_id), the newest state up to the logical date.');
