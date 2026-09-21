-- fact_match_weather: for every match, the forecast for its kick-off hour - or
-- the reason there is none. Parameter: %(logical_date)s.
--
-- The point-in-time rule, as for team form: only a forecast *fetched before
-- kick-off* may be used (fetched_at < utc_kickoff), and only one this run could
-- have known (ingestion_date <= logical_date). Among those, the newest wins -
-- the forecast closest to the match. A forecast fetched after kick-off would
-- describe the weather that happened, i.e. leak the conditions of the match.
--
-- Kick-off hour: the hour that contains the kick-off (18:45 -> 18:00 UTC).
-- date_trunc with an explicit 'UTC' so the session time zone cannot shift it.

WITH usable AS (
    SELECT DISTINCT ON (m.match_id)
           m.match_id, f.ingestion_date, f.fetched_at, f.temperature_c, f.precipitation_mm,
           f.precipitation_probability, f.wind_speed_kmh, f.weather_code
      FROM curated.fact_match m
      JOIN staging.weather_forecast f
        ON f.venue_team_id = m.home_team_id
       AND f.forecast_hour_utc = date_trunc('hour', m.utc_kickoff, 'UTC')
       AND f.fetched_at < m.utc_kickoff
       AND f.ingestion_date <= %(logical_date)s
     ORDER BY m.match_id, f.ingestion_date DESC, f.fetched_at DESC
)
INSERT INTO curated.fact_match_weather AS w (
    match_id, venue_team_id, weather_status, kickoff_hour_utc,
    forecast_ingestion_date, forecast_fetched_at, lead_days,
    temperature_c, precipitation_mm, precipitation_probability, wind_speed_kmh, weather_code,
    as_of_date
)
SELECT
    m.match_id,
    m.home_team_id,
    CASE
        WHEN u.match_id IS NOT NULL THEN 'AVAILABLE'
        WHEN v.coordinates_status IS DISTINCT FROM 'RESOLVED' THEN 'VENUE_UNKNOWN'
        -- beyond the 16-day horizon (logical date + 15) nothing can be fetched yet
        WHEN m.match_date > %(logical_date)s::date + 15 THEN 'NOT_YET_AVAILABLE'
        -- played before any forecast was fetched: cannot be recovered afterwards
        WHEN m.match_date < %(logical_date)s::date THEN 'NOT_CAPTURED'
        -- inside the horizon, not played, but no forecast: a pipeline gap
        ELSE 'MISSING'
    END,
    date_trunc('hour', m.utc_kickoff, 'UTC'),
    u.ingestion_date,
    u.fetched_at,
    m.match_date - u.ingestion_date,
    u.temperature_c,
    u.precipitation_mm,
    u.precipitation_probability,
    u.wind_speed_kmh,
    u.weather_code,
    %(logical_date)s
FROM curated.fact_match m
LEFT JOIN usable u ON u.match_id = m.match_id
LEFT JOIN curated.dim_venue v ON v.team_id = m.home_team_id
ON CONFLICT (match_id) DO UPDATE SET
    venue_team_id = EXCLUDED.venue_team_id,
    weather_status = EXCLUDED.weather_status,
    kickoff_hour_utc = EXCLUDED.kickoff_hour_utc,
    forecast_ingestion_date = EXCLUDED.forecast_ingestion_date,
    forecast_fetched_at = EXCLUDED.forecast_fetched_at,
    lead_days = EXCLUDED.lead_days,
    temperature_c = EXCLUDED.temperature_c,
    precipitation_mm = EXCLUDED.precipitation_mm,
    precipitation_probability = EXCLUDED.precipitation_probability,
    wind_speed_kmh = EXCLUDED.wind_speed_kmh,
    weather_code = EXCLUDED.weather_code,
    as_of_date = EXCLUDED.as_of_date,
    updated_at = now()
-- Same guard as staging: a rerun for an older date must not roll the state back.
WHERE EXCLUDED.as_of_date >= w.as_of_date;
