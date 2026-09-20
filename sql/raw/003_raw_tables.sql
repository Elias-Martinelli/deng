-- Raw zone: API payloads stored exactly as received.
--
-- One table per source, not per endpoint: the endpoint is a column. Reason -
-- every football endpoint has the same envelope (metadata + one JSON document),
-- so separate tables would differ only in name and multiply the DDL, the loader
-- and the checks. A new endpoint therefore needs zero schema changes, which is
-- what keeps ingestion tolerant of the API growing.
--
-- The payload stays JSONB and untouched. All interpretation happens later, in
-- staging. If the API adds or renames a field, ingestion keeps succeeding and
-- only the transformation notices - that is deliberate (see ADR-003).

CREATE TABLE IF NOT EXISTS raw.football_data (
    raw_id          BIGSERIAL   PRIMARY KEY,

    -- Provenance: who said this, when, and in answer to which question
    source          TEXT        NOT NULL DEFAULT 'football-data.org',
    endpoint        TEXT        NOT NULL,          -- e.g. 'competitions/CL/matches'
    request_params  JSONB       NOT NULL DEFAULT '{}'::jsonb,
    request_url     TEXT        NOT NULL,
    ingestion_date  DATE        NOT NULL,          -- logical date of the run
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    run_id          UUID        NOT NULL REFERENCES meta.pipeline_runs (run_id),

    -- The payload itself, plus a hash to detect whether anything changed
    payload         JSONB       NOT NULL,
    payload_hash    TEXT        NOT NULL,          -- sha256 of the canonical JSON
    record_count    INTEGER,                       -- rows in the payload's main list

    -- Idempotency: one row per question per day. A rerun of the same day
    -- overwrites the payload instead of appending a near-duplicate, so running
    -- the pipeline twice cannot inflate the raw zone.
    CONSTRAINT football_data_unique_per_day
        UNIQUE (source, endpoint, request_params, ingestion_date)
);

COMMENT ON TABLE raw.football_data IS
    'Grain: one row per (source, endpoint, request parameters, ingestion date) - i.e. one API answer on one day.';
COMMENT ON COLUMN raw.football_data.payload_hash IS
    'sha256 over the canonical JSON. Equal hash on a rerun means the source did not change that day.';
COMMENT ON COLUMN raw.football_data.ingestion_date IS
    'Logical date of the run, not the wall-clock time - a backfill writes the date it is responsible for.';

-- Query patterns: "latest payload for endpoint X" and "everything from day Y".
CREATE INDEX IF NOT EXISTS football_data_endpoint_date_idx
    ON raw.football_data (endpoint, ingestion_date DESC);
CREATE INDEX IF NOT EXISTS football_data_ingestion_date_idx
    ON raw.football_data (ingestion_date DESC);
CREATE INDEX IF NOT EXISTS football_data_run_idx
    ON raw.football_data (run_id);
