-- fact_match: one row per match with the derived outcome, as curated.fact_match
-- in PostgreSQL (sql/schema/005) - the table the model and the app read.
--
-- Partitioned by MONTH of match_date, not by day. The questions this table
-- answers are date ranges - "this matchday", "this season", "everything before
-- the snapshot date" - so the match date is the column to prune on. Daily
-- partitions would hold three to ten matches each: thousands of tiny partitions
-- (BigQuery allows 10 000 per table and recommends about 1 GB each). A month
-- holds one or two matchdays, so a date-range query still reads few partitions.
--
-- Clustered by home_team_id, away_team_id, match_id: inside a partition the
-- blocks are sorted by team, which is how the form features and the app ask
-- ("the last five matches of club X"), and match_id serves the MERGE.

CREATE TABLE IF NOT EXISTS `{{project}}.{{dataset}}.fact_match` (
    match_id         INT64     NOT NULL,
    season_id        INT64     NOT NULL,
    utc_kickoff      TIMESTAMP NOT NULL,
    match_date       DATE      NOT NULL,   -- UTC calendar day of the kick-off
    stage            STRING    NOT NULL,
    matchday         INT64,
    status           STRING    NOT NULL,
    is_finished      BOOL      NOT NULL,
    is_upcoming      BOOL      NOT NULL,
    home_team_id     INT64     NOT NULL,
    away_team_id     INT64     NOT NULL,
    home_goals       INT64,
    away_goals       INT64,
    goal_difference  INT64,
    outcome          STRING,               -- HOME_WIN / DRAW / AWAY_WIN, NULL until played
    updated_at       TIMESTAMP NOT NULL
)
PARTITION BY DATE_TRUNC(match_date, MONTH)
CLUSTER BY home_team_id, away_team_id, match_id
OPTIONS (description = 'Grain: one row per match (match_id). Measures: goals and the derived outcome (the ML label).');
