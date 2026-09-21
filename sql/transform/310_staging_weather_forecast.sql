-- Unpack Open-Meteo's columnar payload (one array per variable, aligned by
-- position with `time`) into one row per venue and forecast hour.
-- Parameter: %(logical_date)s - the ingestion date to transform.
--
-- Only payloads requested in GMT are accepted: the hour is then UTC and can be
-- compared with the UTC kick-off directly.

INSERT INTO staging.weather_forecast AS w (
    venue_team_id, forecast_hour_utc, ingestion_date, fetched_at,
    temperature_c, precipitation_mm, precipitation_probability, wind_speed_kmh, weather_code
)
SELECT
    r.venue_team_id,
    (t.value #>> '{}')::timestamp AT TIME ZONE 'UTC',
    r.ingestion_date,
    r.ingested_at,
    (r.payload -> 'hourly' -> 'temperature_2m' ->> (t.pos - 1)::int)::numeric,
    (r.payload -> 'hourly' -> 'precipitation' ->> (t.pos - 1)::int)::numeric,
    (r.payload -> 'hourly' -> 'precipitation_probability' ->> (t.pos - 1)::int)::int,
    (r.payload -> 'hourly' -> 'wind_speed_10m' ->> (t.pos - 1)::int)::numeric,
    (r.payload -> 'hourly' -> 'weather_code' ->> (t.pos - 1)::int)::int
FROM raw.open_meteo r
CROSS JOIN LATERAL jsonb_array_elements(r.payload -> 'hourly' -> 'time')
     WITH ORDINALITY AS t(value, pos)
WHERE r.ingestion_date = %(logical_date)s
  AND r.payload ->> 'timezone' = 'GMT'
ON CONFLICT (venue_team_id, forecast_hour_utc, ingestion_date) DO UPDATE SET
    fetched_at = EXCLUDED.fetched_at,
    temperature_c = EXCLUDED.temperature_c,
    precipitation_mm = EXCLUDED.precipitation_mm,
    precipitation_probability = EXCLUDED.precipitation_probability,
    wind_speed_kmh = EXCLUDED.wind_speed_kmh,
    weather_code = EXCLUDED.weather_code,
    loaded_at = now();
