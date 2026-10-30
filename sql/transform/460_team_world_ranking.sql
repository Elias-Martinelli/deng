-- Rebuild mappings from immutable captured observations. No backdating.
DELETE FROM staging.team_world_ranking;
INSERT INTO staging.team_world_ranking (
    raw_id, team_id, club_slug, ranking_date, observed_at, world_rank, rating_points, source_url
)
SELECT r.raw_id, mapping.team_id, p->>'club_slug', r.ranking_date, r.observed_at,
       (p->>'world_rank')::int, (p->>'rating_points')::int, r.request_url
FROM raw.footballdatabase_pages r
CROSS JOIN LATERAL jsonb_array_elements(r.payload) p
JOIN raw.footballdatabase_team_map mapping ON mapping.club_slug = p->>'club_slug'
WHERE r.ingestion_date <= %(logical_date)s;
