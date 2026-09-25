-- Raw zone for OpenStreetMap: one stored answer per club stadium.
--
-- Same shape as the other raw tables (the answer unchanged, plus who asked
-- what and when), with two extra columns that the other sources do not need:
--
--   review_status / review_note - our own verdict about the answer. The search
--   can return a stadium of the same name in another city, so a person checked
--   every flagged row once and the verdict is stored next to the payload
--   instead of only in a CSV file. The payload itself stays untouched.

CREATE TABLE IF NOT EXISTS raw.osm_venues (
    raw_id         BIGSERIAL   PRIMARY KEY,
    source         TEXT        NOT NULL DEFAULT 'openstreetmap.org',
    endpoint       TEXT        NOT NULL,            -- 'search' (Nominatim)
    team_id        BIGINT      NOT NULL,            -- whose home venue
    request_params JSONB       NOT NULL,            -- the search terms we sent
    request_url    TEXT        NOT NULL,
    ingestion_date DATE        NOT NULL,
    ingested_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    run_id         UUID        REFERENCES meta.pipeline_runs (run_id),
    payload        JSONB       NOT NULL,            -- the Nominatim answer, unchanged
    payload_hash   TEXT        NOT NULL,
    review_status  TEXT        NOT NULL CHECK (review_status IN ('RESOLVED', 'NOT_AVAILABLE')),
    review_note    TEXT,
    timezone       TEXT,                            -- IANA zone of the club's country
    CONSTRAINT osm_venues_unique_per_day UNIQUE (source, team_id, ingestion_date)
);

COMMENT ON TABLE raw.osm_venues IS
    'Grain: one OpenStreetMap answer per club per ingestion date. Stadiums do not move, so this is fetched once per season, not daily.';

-- What the weather source is allowed to look up: the newest coordinates per club.
CREATE OR REPLACE VIEW raw.venue_coordinates AS
SELECT DISTINCT ON (team_id)
       team_id,
       payload ->> 'name'                             AS osm_name,
       (payload ->> 'lat')::numeric(8, 5)             AS latitude,
       (payload ->> 'lon')::numeric(8, 5)             AS longitude,
       payload ->> 'display_name'                     AS osm_address,
       payload ->> 'osm_type'                         AS osm_type,
       payload ->> 'osm_id'                           AS osm_id,
       timezone,
       review_status,
       review_note,
       ingestion_date
  FROM raw.osm_venues
 ORDER BY team_id, ingestion_date DESC, ingested_at DESC;

COMMENT ON VIEW raw.venue_coordinates IS
    'One row per club with the newest stadium coordinates. Read by the weather source; the transformation builds staging.venues from the same table.';
