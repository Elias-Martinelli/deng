-- dim_venue from the reference file (staging.venues). Keyed by the home club:
-- in the league phase every match is played at the home club's venue.

INSERT INTO curated.dim_venue AS d (
    team_id, venue_name, api_venue_name, latitude, longitude, timezone,
    coordinates_status, osm_reference
)
SELECT
    v.team_id,
    v.osm_name,
    v.api_venue,
    v.latitude,
    v.longitude,
    v.timezone,
    v.status,
    CASE WHEN v.osm_id IS NOT NULL THEN v.osm_type || '/' || v.osm_id END
FROM staging.venues v
JOIN curated.dim_team t ON t.team_id = v.team_id
ON CONFLICT (team_id) DO UPDATE SET
    venue_name = EXCLUDED.venue_name,
    api_venue_name = EXCLUDED.api_venue_name,
    latitude = EXCLUDED.latitude,
    longitude = EXCLUDED.longitude,
    timezone = EXCLUDED.timezone,
    coordinates_status = EXCLUDED.coordinates_status,
    osm_reference = EXCLUDED.osm_reference,
    updated_at = now();
