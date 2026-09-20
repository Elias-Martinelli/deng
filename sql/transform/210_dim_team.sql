-- dim_team from staging.teams.
--
-- The free tier of football-data.org covers 12 competitions. A club whose
-- domestic league is not among them yields no domestic matches, so its form
-- can only come from Champions League games - recorded here as a flag rather
-- than discovered later by surprise.

INSERT INTO curated.dim_team AS d (
    team_id, name, short_name, tla, country, venue, crest_url,
    competitions, has_domestic_coverage
)
SELECT
    team_id,
    name,
    COALESCE(short_name, name),
    tla,
    area_name,
    venue,
    crest_url,
    competitions,
    EXISTS (
        SELECT 1
          FROM unnest(competitions) AS code
         WHERE code <> 'CL'
           AND code IN ('PL', 'PD', 'BL1', 'SA', 'FL1', 'DED', 'PPL', 'ELC', 'BSA')
    )
FROM staging.teams
ON CONFLICT (team_id) DO UPDATE SET
    name = EXCLUDED.name,
    short_name = EXCLUDED.short_name,
    tla = EXCLUDED.tla,
    country = EXCLUDED.country,
    venue = EXCLUDED.venue,
    crest_url = EXCLUDED.crest_url,
    competitions = EXCLUDED.competitions,
    has_domestic_coverage = EXCLUDED.has_domestic_coverage,
    updated_at = now();
