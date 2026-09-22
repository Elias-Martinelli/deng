-- Unpack the teams payload into one typed row per team.
-- Parameter: %(logical_date)s - the ingestion date to transform.
--
-- Reading JSONB: `->` returns JSON (to navigate further), `->>` returns text
-- (to cast into a column type). psycopg reads every percent sign in these
-- files as the start of a parameter - even inside a comment - so SQL's LIKE
-- wildcard is written doubled (%%) and stands for a single one.

-- The day's payload. If a day holds more than one (a sample replay and a real
-- API answer, which differ in `source`), the newest wins - deterministic.
WITH payload AS (
    SELECT payload
      FROM raw.football_data
     WHERE endpoint LIKE '%%/teams'
       AND ingestion_date = %(logical_date)s
     ORDER BY ingested_at DESC
     LIMIT 1
),
-- One row per element of the "teams" array.
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
    -- The competitions the club plays in our API tier, as a sorted text
    -- array (e.g. {CL,PL}); feeds dim_team.has_domestic_coverage. Sorted so the
    -- same set always compares equal; '{}' instead of NULL for "none".
    COALESCE(
        (SELECT array_agg(c ->> 'code' ORDER BY c ->> 'code')
           FROM jsonb_array_elements(t -> 'runningCompetitions') AS c),
        '{}'
    ),
    %(logical_date)s
FROM unpacked
-- A team without an id cannot be joined to anything; skip it instead of
-- failing the whole transformation on one malformed element.
WHERE t ->> 'id' IS NOT NULL
-- One row per team (current state). A rerun updates in place ...
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
-- ... but only with data at least as new: a backfill of an older date must not
-- overwrite a newer state (same guard as staging.matches).
WHERE EXCLUDED.ingestion_date >= s.ingestion_date;
