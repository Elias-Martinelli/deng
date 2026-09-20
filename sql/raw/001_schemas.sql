-- Schemas of the local pipeline.
--
-- raw      immutable API payloads exactly as received, plus ingestion metadata
-- staging  typed, flattened tables derived from raw (built in sprint 4)
-- curated  facts and dimensions that the data product exposes (sprint 4)
-- meta     pipeline run log and data-quality results
--
-- Why four schemas in one database instead of four databases? A single
-- connection can join across them, transactions span them, and `docker compose
-- down -v` resets everything at once. The separation is about *meaning*
-- (trust level of the data), not about isolation.

CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS staging;
CREATE SCHEMA IF NOT EXISTS curated;
CREATE SCHEMA IF NOT EXISTS meta;

COMMENT ON SCHEMA raw IS 'Immutable API payloads + ingestion metadata. Never edited, only appended or replaced per (source, endpoint, params, ingestion_date).';
COMMENT ON SCHEMA staging IS 'Typed, flattened tables derived from raw. Rebuildable at any time.';
COMMENT ON SCHEMA curated IS 'Facts and dimensions served to analytics, ML and the app.';
COMMENT ON SCHEMA meta IS 'Pipeline run log and data-quality results.';
