-- dim_team from staging.teams.
--
-- has_domestic_coverage records whether the club's domestic league is among
-- the free tier's 12 competitions. Descriptive only: form is built from
-- Champions League matches for every club (ADR-004).

INSERT INTO curated.dim_team AS d (
    team_id, name, short_name, tla, country, venue, crest_url,
    competitions, has_domestic_coverage
)
SELECT
    team_id,
    name,
    COALESCE(short_name, name),   -- the app needs a label even if shortName is missing
    tla,
    area_name,
    venue,
    crest_url,
    competitions,
    -- True when the club also plays in a *domestic league* of the free tier.
    -- The free tier's 12 competitions are these leagues plus CL, the World Cup
    -- and the Euros (WC, EC - not club competitions). PL England, PD Spain,
    -- BL1 Germany, SA Italy, FL1 France, DED Netherlands, PPL Portugal,
    -- ELC English Championship, BSA Brazil.
    EXISTS (
        SELECT 1
          FROM unnest(competitions) AS code
         WHERE code IN ('PL', 'PD', 'BL1', 'SA', 'FL1', 'DED', 'PPL', 'ELC', 'BSA')
    )
FROM staging.teams
-- A dimension holds the current description of each team; history of names
-- or venues is not needed by the use case (no slowly changing dimension).
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
