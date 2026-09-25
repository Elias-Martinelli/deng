-- Weather: raw forecasts, venues, and the weather each match can be joined to.

-- Raw zone for Open-Meteo, one table per source (see 003_raw_tables.sql).
-- Grain: one forecast answer per venue per ingestion date. A rerun on the same
-- day overwrites it; the next day adds a new row, so the history of how the
-- forecast for a match evolved is kept.
CREATE TABLE IF NOT EXISTS raw.open_meteo (
    raw_id          BIGSERIAL   PRIMARY KEY,
    source          TEXT        NOT NULL DEFAULT 'open-meteo.com',
    endpoint        TEXT        NOT NULL,               -- 'v1/forecast'
    venue_team_id   BIGINT      NOT NULL,               -- whose home venue; not sent to the API
    request_params  JSONB       NOT NULL,
    request_url     TEXT        NOT NULL,
    ingestion_date  DATE        NOT NULL,
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now(), -- wall clock: the leakage guard uses it
    run_id          UUID        NOT NULL REFERENCES meta.pipeline_runs (run_id),
    payload         JSONB       NOT NULL,
    payload_hash    TEXT        NOT NULL,
    CONSTRAINT open_meteo_unique_per_day UNIQUE (source, endpoint, venue_team_id, ingestion_date)
);

COMMENT ON TABLE raw.open_meteo IS
    'Grain: one row per (endpoint, venue, ingestion date) - one forecast answer for one stadium on one day.';

-- Venue data, built by sql/transform/305_staging_venues.sql from the stored
-- OpenStreetMap answers in raw.osm_venues.
CREATE TABLE IF NOT EXISTS staging.venues (
    team_id      BIGINT PRIMARY KEY,
    team_name    TEXT   NOT NULL,
    api_venue    TEXT,
    osm_name     TEXT,
    latitude     NUMERIC(8, 5),
    longitude    NUMERIC(8, 5),
    timezone     TEXT,
    osm_type     TEXT,
    osm_id       BIGINT,
    status       TEXT   NOT NULL CHECK (status IN ('RESOLVED', 'NOT_AVAILABLE')),
    note         TEXT,
    CONSTRAINT venues_resolved_have_coordinates
        CHECK (status <> 'RESOLVED' OR (latitude IS NOT NULL AND longitude IS NOT NULL))
);

COMMENT ON TABLE staging.venues IS 'Grain: one row per club (its home venue). Source: raw.osm_venues (OpenStreetMap).';

-- Hourly forecast values, unpacked from the columnar arrays of the payload.
CREATE TABLE IF NOT EXISTS staging.weather_forecast (
    venue_team_id             BIGINT      NOT NULL,
    forecast_hour_utc         TIMESTAMPTZ NOT NULL,
    ingestion_date            DATE        NOT NULL,
    fetched_at                TIMESTAMPTZ NOT NULL,
    temperature_c             NUMERIC(5, 1),
    precipitation_mm          NUMERIC(6, 2),
    precipitation_probability INTEGER,
    wind_speed_kmh            NUMERIC(6, 1),
    weather_code              INTEGER,
    loaded_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (venue_team_id, forecast_hour_utc, ingestion_date)
);

COMMENT ON TABLE staging.weather_forecast IS
    'Grain: one row per venue per forecast hour per ingestion date - every day''s forecast is kept.';

CREATE TABLE IF NOT EXISTS curated.dim_venue (
    team_id             BIGINT PRIMARY KEY REFERENCES curated.dim_team (team_id),
    venue_name          TEXT,
    api_venue_name      TEXT,
    latitude            NUMERIC(8, 5),
    longitude           NUMERIC(8, 5),
    timezone            TEXT,
    coordinates_status  TEXT   NOT NULL CHECK (coordinates_status IN ('RESOLVED', 'NOT_AVAILABLE')),
    osm_reference       TEXT,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE curated.dim_venue IS
    'Grain: one row per club home venue (keyed by team). League-phase matches are played at the home club''s venue.';

-- The weather each match can be judged by, and why it is missing when it is.
CREATE TABLE IF NOT EXISTS curated.fact_match_weather (
    match_id                  BIGINT      PRIMARY KEY REFERENCES curated.fact_match (match_id),
    venue_team_id             BIGINT      NOT NULL,
    weather_status            TEXT        NOT NULL CHECK (weather_status IN
                                  ('AVAILABLE', 'NOT_YET_AVAILABLE', 'VENUE_UNKNOWN',
                                   'NOT_CAPTURED', 'MISSING')),
    kickoff_hour_utc          TIMESTAMPTZ NOT NULL,
    forecast_ingestion_date   DATE,
    forecast_fetched_at       TIMESTAMPTZ,
    lead_days                 INTEGER,
    temperature_c             NUMERIC(5, 1),
    precipitation_mm          NUMERIC(6, 2),
    precipitation_probability INTEGER,
    wind_speed_kmh            NUMERIC(6, 1),
    weather_code              INTEGER,
    as_of_date                DATE        NOT NULL,
    updated_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT weather_available_has_values
        CHECK ((weather_status = 'AVAILABLE') = (temperature_c IS NOT NULL))
);

COMMENT ON TABLE curated.fact_match_weather IS
    'Grain: one row per match. The latest forecast fetched before kick-off, or the reason there is none.';
COMMENT ON COLUMN curated.fact_match_weather.weather_status IS
    'AVAILABLE; NOT_YET_AVAILABLE (kick-off beyond the 16-day horizon); VENUE_UNKNOWN (no coordinates); '
    'NOT_CAPTURED (played before we fetched a forecast - cannot be recovered); '
    'MISSING (inside the horizon but no forecast fetched - a pipeline gap).';
