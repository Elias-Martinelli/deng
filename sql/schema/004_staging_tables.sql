-- Staging: the raw JSONB unpacked into typed columns.
--
-- One rule: staging only *shapes* data, it does not interpret it. Renaming,
-- casting and flattening happen here; business logic (form, features) happens
-- in curated. That split is what lets us rebuild everything from raw after a
-- bug without re-fetching anything from the API.
--
-- Tables, not views: the unpacking touches every element of a 212 KB document,
-- and curated queries join against it repeatedly. Materialising once per run is
-- cheaper and makes the intermediate state inspectable during a defence.

CREATE TABLE IF NOT EXISTS staging.matches (
    match_id        BIGINT      PRIMARY KEY,
    season_id       BIGINT      NOT NULL,
    competition_code TEXT       NOT NULL,
    utc_kickoff     TIMESTAMPTZ NOT NULL,
    status          TEXT        NOT NULL,
    stage           TEXT        NOT NULL,
    matchday        INTEGER,
    home_team_id    BIGINT      NOT NULL,
    away_team_id    BIGINT      NOT NULL,
    home_goals      INTEGER,
    away_goals      INTEGER,
    home_goals_ht   INTEGER,
    away_goals_ht   INTEGER,
    winner          TEXT,
    duration        TEXT,
    last_updated    TIMESTAMPTZ,
    ingestion_date  DATE        NOT NULL,
    loaded_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT matches_teams_differ CHECK (home_team_id <> away_team_id),
    CONSTRAINT matches_goals_non_negative
        CHECK ((home_goals IS NULL OR home_goals >= 0)
           AND (away_goals IS NULL OR away_goals >= 0))
);

COMMENT ON TABLE staging.matches IS 'Grain: one row per Champions League match (match_id).';
COMMENT ON COLUMN staging.matches.status IS
    'Source value. Note: querying the API with ?status=SCHEDULED returns rows stored as TIMED - see docs/evidence/api-exploration.md §7.';

CREATE INDEX IF NOT EXISTS staging_matches_kickoff_idx ON staging.matches (utc_kickoff);
CREATE INDEX IF NOT EXISTS staging_matches_home_idx    ON staging.matches (home_team_id);
CREATE INDEX IF NOT EXISTS staging_matches_away_idx    ON staging.matches (away_team_id);

CREATE TABLE IF NOT EXISTS staging.teams (
    team_id         BIGINT      PRIMARY KEY,
    name            TEXT        NOT NULL,
    short_name      TEXT,
    tla             TEXT,
    crest_url       TEXT,
    founded         INTEGER,
    club_colors     TEXT,
    venue           TEXT,
    website         TEXT,
    area_name       TEXT,
    -- Competition codes the club currently plays in, e.g. {CL,BL1}. Feeds the
    -- descriptive flag dim_team.has_domestic_coverage (form itself is
    -- Champions League only for every club, ADR-004).
    competitions    TEXT[]      NOT NULL DEFAULT '{}',
    ingestion_date  DATE        NOT NULL,
    loaded_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE staging.teams IS 'Grain: one row per team in the current Champions League season (team_id).';

CREATE TABLE IF NOT EXISTS staging.standings (
    season_id       BIGINT      NOT NULL,
    team_id         BIGINT      NOT NULL,
    position        INTEGER     NOT NULL,
    played_games    INTEGER     NOT NULL,
    won             INTEGER     NOT NULL,
    draw            INTEGER     NOT NULL,
    lost            INTEGER     NOT NULL,
    points          INTEGER     NOT NULL,
    goals_for       INTEGER     NOT NULL,
    goals_against   INTEGER     NOT NULL,
    goal_difference INTEGER     NOT NULL,
    ingestion_date  DATE        NOT NULL,
    loaded_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- The table changes after every matchday, so a standing is only meaningful
    -- together with the day it was observed.
    PRIMARY KEY (season_id, team_id, ingestion_date)
);

COMMENT ON TABLE staging.standings IS
    'Grain: one row per team per season per ingestion date - a point-in-time snapshot of the league table.';
