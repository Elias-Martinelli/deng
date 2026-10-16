-- Receipt time must advance inside a long ingestion transaction.
-- now() is the transaction start, potentially minutes before a response arrives.
ALTER TABLE raw.football_data ALTER COLUMN ingested_at SET DEFAULT clock_timestamp();
ALTER TABLE raw.open_meteo ALTER COLUMN ingested_at SET DEFAULT clock_timestamp();
ALTER TABLE raw.osm_venues ALTER COLUMN ingested_at SET DEFAULT clock_timestamp();
ALTER TABLE raw.team_context_import ALTER COLUMN ingested_at SET DEFAULT clock_timestamp();
