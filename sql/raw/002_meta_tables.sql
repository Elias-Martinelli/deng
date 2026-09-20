-- Pipeline observability: one row per pipeline run, one row per data-quality check.
--
-- Why persist runs in the database rather than only logging them? A reviewer (or
-- we, during the defence) must be able to answer "did yesterday's run succeed,
-- how many rows did it write, and how long did it take?" with a SQL query
-- instead of grepping container logs that are gone after `docker compose down`.

CREATE TABLE IF NOT EXISTS meta.pipeline_runs (
    run_id          UUID        PRIMARY KEY,
    pipeline_name   TEXT        NOT NULL,
    -- The logical date this run is responsible for. A backfill for 2026-09-10
    -- carries that date even when executed today, which is what makes a rerun
    -- for a past partition meaningful.
    logical_date    DATE        NOT NULL,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at     TIMESTAMPTZ,
    status          TEXT        NOT NULL DEFAULT 'RUNNING'
                                CHECK (status IN ('RUNNING', 'SUCCESS', 'FAILED')),
    rows_extracted  INTEGER     NOT NULL DEFAULT 0,
    rows_loaded     INTEGER     NOT NULL DEFAULT 0,
    rows_updated    INTEGER     NOT NULL DEFAULT 0,
    error_message   TEXT
);

COMMENT ON TABLE meta.pipeline_runs IS 'One row per pipeline execution. Grain: one run of one pipeline for one logical date.';
COMMENT ON COLUMN meta.pipeline_runs.logical_date IS 'The date the run is responsible for - not necessarily the execution date (backfills).';

CREATE INDEX IF NOT EXISTS pipeline_runs_logical_date_idx
    ON meta.pipeline_runs (pipeline_name, logical_date DESC);

CREATE TABLE IF NOT EXISTS meta.dq_results (
    dq_result_id  BIGSERIAL   PRIMARY KEY,
    run_id        UUID        REFERENCES meta.pipeline_runs (run_id) ON DELETE CASCADE,
    checked_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    check_name    TEXT        NOT NULL,
    target        TEXT        NOT NULL,
    severity      TEXT        NOT NULL CHECK (severity IN ('CRITICAL', 'WARNING')),
    passed        BOOLEAN     NOT NULL,
    observed      TEXT,
    details       TEXT
);

COMMENT ON TABLE meta.dq_results IS 'One row per data-quality check per run. CRITICAL failures fail the run; WARNING failures are recorded and visible.';
