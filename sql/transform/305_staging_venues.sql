-- staging.venues from the stored OpenStreetMap answers.
--
-- Until this file existed, the venue table was loaded from a CSV by the
-- weather ingestion - which made the ingestion write a staging table. Now the
-- OpenStreetMap source stores its answers in raw.osm_venues like every other
-- source, and this transformation unpacks them, exactly like 110 unpacks the
-- football payload.
--
-- The club's own name and the venue name the football API reports come from
-- raw.team_catalog, so both spellings stay visible next to each other: ours
-- from OpenStreetMap, theirs from the football API.

INSERT INTO staging.venues AS v (
    team_id, team_name, api_venue, osm_name, latitude, longitude, timezone,
    osm_type, osm_id, status, note
)
SELECT
    c.team_id,
    t.name,
    t.venue,
    c.osm_name,
    c.latitude,
    c.longitude,
    c.timezone,
    c.osm_type,
    NULLIF(c.osm_id, '')::bigint,
    c.review_status,
    c.review_note
FROM raw.venue_coordinates c
JOIN raw.team_catalog t ON t.team_id = c.team_id
ON CONFLICT (team_id) DO UPDATE SET
    team_name = EXCLUDED.team_name,
    api_venue = EXCLUDED.api_venue,
    osm_name = EXCLUDED.osm_name,
    latitude = EXCLUDED.latitude,
    longitude = EXCLUDED.longitude,
    timezone = EXCLUDED.timezone,
    osm_type = EXCLUDED.osm_type,
    osm_id = EXCLUDED.osm_id,
    status = EXCLUDED.status,
    note = EXCLUDED.note;
