-- Captured public ranking pages, immutable per content; mapping is inspectable.
CREATE TABLE IF NOT EXISTS raw.footballdatabase_pages (
    raw_id BIGSERIAL PRIMARY KEY,
    source TEXT NOT NULL DEFAULT 'footballdatabase.com',
    page INTEGER NOT NULL CHECK (page > 0),
    ranking_date DATE NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    ingestion_date DATE NOT NULL,
    last_checked_date DATE NOT NULL DEFAULT CURRENT_DATE,
    request_url TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    html TEXT NOT NULL,
    payload JSONB NOT NULL,
    run_id UUID NOT NULL REFERENCES meta.pipeline_runs(run_id),
    UNIQUE (source, page, ranking_date, payload_hash)
);
CREATE TABLE IF NOT EXISTS raw.footballdatabase_team_map (
    team_id BIGINT PRIMARY KEY,
    club_slug TEXT NOT NULL UNIQUE,
    method TEXT NOT NULL CHECK (method IN ('EXACT_COUNTRY', 'REVIEWED')),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS staging.team_world_ranking (
    raw_id BIGINT NOT NULL REFERENCES raw.footballdatabase_pages(raw_id),
    team_id BIGINT NOT NULL,
    club_slug TEXT NOT NULL,
    ranking_date DATE NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    world_rank INTEGER NOT NULL CHECK (world_rank > 0),
    rating_points INTEGER NOT NULL CHECK (rating_points > 0),
    source_url TEXT NOT NULL,
    PRIMARY KEY (raw_id, team_id)
);
CREATE INDEX IF NOT EXISTS team_world_ranking_lookup_idx
    ON staging.team_world_ranking(team_id, observed_at DESC, ranking_date DESC);
COMMENT ON TABLE staging.team_world_ranking IS
    'FootballDatabase world club rank and rating points. ranking_date is games-through date, not publication time. observed_at is first successful capture.';

ALTER TABLE raw.footballdatabase_pages ADD COLUMN IF NOT EXISTS last_checked_date DATE NOT NULL DEFAULT CURRENT_DATE;
