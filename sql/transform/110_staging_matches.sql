-- Unpack the day's fixture payload into one typed row per match.
--
-- Parameter: %(logical_date)s - the ingestion date to transform. Passing it
-- explicitly (rather than using "the newest row") is what makes a rerun for a
-- past date produce that date's result instead of today's.
--
-- Idempotent throughout: every statement is an upsert on the table's key, so
-- running the transformation twice changes nothing.

-- --------------------------------------------------------------------------
-- matches
-- --------------------------------------------------------------------------
-- Every match answer stored on this day, not just one: the current season comes
-- without parameters, each past season as its own answer (?season=2023). A match
-- can therefore appear twice - in the sample replay and in the real answer, or in
-- two overlapping seasons - so DISTINCT ON keeps the newest and the INSERT below
-- sees each match_id exactly once. (Without that, PostgreSQL refuses the upsert:
-- "ON CONFLICT DO UPDATE command cannot affect row a second time".)
WITH unpacked AS (
    SELECT DISTINCT ON ((m ->> 'id')::bigint) m
      FROM raw.football_data r
      CROSS JOIN LATERAL jsonb_array_elements(r.payload -> 'matches') AS m
     WHERE r.endpoint LIKE '%%/matches'
       AND r.ingestion_date = %(logical_date)s
     ORDER BY (m ->> 'id')::bigint, r.ingested_at DESC
)
INSERT INTO staging.matches AS t (
    match_id, season_id, competition_code, utc_kickoff, status, stage, matchday,
    home_team_id, away_team_id, home_goals, away_goals, home_goals_ht, away_goals_ht,
    winner, duration, last_updated, ingestion_date
)
SELECT
    (m ->> 'id')::bigint,
    (m -> 'season' ->> 'id')::bigint,
    m -> 'competition' ->> 'code',
    (m ->> 'utcDate')::timestamptz,              -- "2026-10-13T16:45:00Z": UTC, stored as such
    m ->> 'status',
    m ->> 'stage',
    (m ->> 'matchday')::int,
    (m -> 'homeTeam' ->> 'id')::bigint,
    (m -> 'awayTeam' ->> 'id')::bigint,
    -- NULL until the match is played; `::int` of a JSON null stays NULL.
    (m -> 'score' -> 'fullTime' ->> 'home')::int,
    (m -> 'score' -> 'fullTime' ->> 'away')::int,
    (m -> 'score' -> 'halfTime' ->> 'home')::int,
    (m -> 'score' -> 'halfTime' ->> 'away')::int,
    m -> 'score' ->> 'winner',
    m -> 'score' ->> 'duration',
    (m ->> 'lastUpdated')::timestamptz,
    %(logical_date)s
FROM unpacked
-- Defensive: a match without both teams cannot be modelled, and the source has
-- never produced one. Skipping instead of failing keeps one malformed row from
-- blocking the whole run; the data-quality check reports the count difference.
WHERE m -> 'homeTeam' ->> 'id' IS NOT NULL
  AND m -> 'awayTeam' ->> 'id' IS NOT NULL
ON CONFLICT (match_id) DO UPDATE SET
    season_id = EXCLUDED.season_id,
    utc_kickoff = EXCLUDED.utc_kickoff,
    status = EXCLUDED.status,
    stage = EXCLUDED.stage,
    matchday = EXCLUDED.matchday,
    home_goals = EXCLUDED.home_goals,
    away_goals = EXCLUDED.away_goals,
    home_goals_ht = EXCLUDED.home_goals_ht,
    away_goals_ht = EXCLUDED.away_goals_ht,
    winner = EXCLUDED.winner,
    duration = EXCLUDED.duration,
    last_updated = EXCLUDED.last_updated,
    ingestion_date = EXCLUDED.ingestion_date,
    loaded_at = now()
-- Only overwrite when the source is at least as new. Protects a rerun of an
-- older logical date from stamping stale values over fresher ones.
WHERE EXCLUDED.ingestion_date >= t.ingestion_date;
