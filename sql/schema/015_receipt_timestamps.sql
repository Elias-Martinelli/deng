-- Receipt time must advance inside a long ingestion transaction.
-- now() is the transaction start, potentially minutes before a response arrives.
ALTER TABLE raw.football_data ALTER COLUMN ingested_at SET DEFAULT clock_timestamp();
ALTER TABLE raw.open_meteo ALTER COLUMN ingested_at SET DEFAULT clock_timestamp();
ALTER TABLE raw.osm_venues ALTER COLUMN ingested_at SET DEFAULT clock_timestamp();
ALTER TABLE raw.team_context_import ALTER COLUMN ingested_at SET DEFAULT clock_timestamp();

-- The receipt time a leakage guard compares with the kick-off: the replayed
-- moment during a sample replay (012_pipeline_clock.sql), otherwise the true
-- moment the answer arrived - not the transaction start, which now() and
-- meta.pipeline_now() return. VOLATILE because clock_timestamp() is.
CREATE OR REPLACE FUNCTION meta.receipt_time() RETURNS timestamptz
LANGUAGE sql VOLATILE AS $$
    SELECT coalesce(nullif(current_setting('deng.as_of', true), '')::timestamptz,
                    clock_timestamp())
$$;
COMMENT ON FUNCTION meta.receipt_time() IS
    'clock_timestamp(), or the moment a sample replay pinned with set_config(''deng.as_of'', ...).';
