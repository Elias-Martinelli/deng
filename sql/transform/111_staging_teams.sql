-- Unpack the teams payload. Parameter: %(logical_date)s

WITH payload AS (
    SELECT payload
      FROM raw.football_data
     WHERE endpoint LIKE '%%/teams'
       AND ingestion_date = %(logical_date)s
     ORDER BY ingested_at DESC
     LIMIT 1
),
unpacked AS (
    SELECT jsonb_array_elements(payload -> 'teams') AS t
      FROM payload
)
INSERT INTO staging.teams AS s (
    team_id, name, short_name, tla, crest_url, founded, club_colors,
    venue, website, area_name, competitions, ingestion_date
)
SELECT
    (t ->> 'id')::bigint,
    t ->> 'name',
    t ->> 'shortName',
    t ->> 'tla',
    t ->> 'crest',
    (t ->> 'founded')::int,
    t ->> 'clubColors',
    t ->> 'venue',
    t ->> 'website',
    t -> 'area' ->> 'name',
    COALESCE(
        (SELECT array_agg(c ->> 'code' ORDER BY c ->> 'code')
           FROM jsonb_array_elements(t -> 'runningCompetitions') AS c),
        '{}'
    ),
    %(logical_date)s
FROM unpacked
WHERE t ->> 'id' IS NOT NULL
ON CONFLICT (team_id) DO UPDATE SET
    name = EXCLUDED.name,
    short_name = EXCLUDED.short_name,
    tla = EXCLUDED.tla,
    crest_url = EXCLUDED.crest_url,
    founded = EXCLUDED.founded,
    club_colors = EXCLUDED.club_colors,
    venue = EXCLUDED.venue,
    website = EXCLUDED.website,
    area_name = EXCLUDED.area_name,
    competitions = EXCLUDED.competitions,
    ingestion_date = EXCLUDED.ingestion_date,
    loaded_at = now()
WHERE EXCLUDED.ingestion_date >= s.ingestion_date;
