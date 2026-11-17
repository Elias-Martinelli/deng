-- The raw zone, read where it lies: one external table over every object in
-- the bucket (src/deng/raw_zone/gcs.py). Nothing is copied into BigQuery, so
-- the bucket stays the only raw zone, and a new source or endpoint needs no
-- DDL change - the same reason PostgreSQL has one raw table per source.
--
-- Hive partitioning: the path levels `source=`, `endpoint=` and
-- `ingestion_date=` become the three partition columns. A query that filters
-- them reads only the matching prefixes. require_hive_partition_filter makes
-- that mandatory: a query that forgets the day fails instead of scanning the
-- whole history.
--
-- The schema is explicit, not detected: every source's payload has another
-- shape, so the payload (and key, params, attributes) is JSON text, read in
-- staging with JSON_VALUE / JSON_QUERY_ARRAY. ignore_unknown_values lets the
-- envelope grow a field without breaking this table.
--
-- Placeholders: {{project}}, {{dataset}} and {{bucket}} come from the settings
-- (src/deng/warehouse/bigquery.py); identifiers cannot be query parameters.

CREATE OR REPLACE EXTERNAL TABLE `{{project}}.{{dataset}}.raw_answers` (
    request STRUCT<
        source STRING,      -- exact provenance, e.g. 'football-data.org (sample)'
        endpoint STRING,    -- exact path, e.g. 'competitions/CL/matches'
        url STRING,
        key STRING,         -- JSON text: the rest of the business key
        params STRING       -- JSON text: the query parameters sent
    >,
    run_id STRING,
    ingested_at STRING,     -- ISO 8601 with offset; TIMESTAMP() in staging
    payload_hash STRING,
    record_count INT64,
    attributes STRING,      -- JSON text: columns kept beside the payload
    payload STRING          -- JSON text: the answer, unchanged
)
WITH PARTITION COLUMNS (
    source STRING,          -- path-safe: 'football-data.org-sample'
    endpoint STRING,        -- path-safe: 'competitions.CL.matches'
    ingestion_date DATE
)
OPTIONS (
    format = 'NEWLINE_DELIMITED_JSON',
    uris = ['gs://{{bucket}}/raw/*'],
    hive_partition_uri_prefix = 'gs://{{bucket}}/raw',
    require_hive_partition_filter = TRUE,
    ignore_unknown_values = TRUE,
    description = 'Grain: one row per stored API answer per day (one GCS object). External over gs://{{bucket}}/raw.'
);
