-- Rebuild observed snapshots. Logical run dates never backdate API knowledge.
DELETE FROM staging.team_context_snapshot;

INSERT INTO staging.team_context_snapshot (snapshot_id, team_id, source, source_url, observed_at, valid_from, valid_until, squad_size, squad_avg_age, squad_min_age, squad_max_age, squad_nationalities, squad_foreign_players, squad_goalkeepers, squad_defenders, squad_midfielders, squad_attackers, squad_unknown_positions, squad_missing_birthdates, coach_id, coach_name, coach_birth_date, coach_nationality, coach_tenure_start, coach_contract_start, squad_market_value_eur)
SELECT 'football:' || r.raw_id || ':' || (t->>'id'), (t->>'id')::bigint,
       r.source, r.request_url, greatest(r.ingested_at, run.finished_at), greatest(r.ingested_at, run.finished_at), NULL::timestamptz,
       p.squad_size,
       p.squad_avg_age,
       p.squad_min_age,
       p.squad_max_age,
       p.squad_nationalities,
       p.squad_foreign_players,
       p.squad_goalkeepers,
       p.squad_defenders,
       p.squad_midfielders,
       p.squad_attackers,
       p.squad_unknown_positions,
       p.squad_missing_birthdates,
       CASE WHEN t->'coach'->>'id' IS NOT NULL
            THEN 'football-data.org:' || (t->'coach'->>'id') END,
       t->'coach'->>'name', NULLIF(t->'coach'->>'dateOfBirth', '')::date,
       t->'coach'->>'nationality', NULL::date, t->'coach'->'contract'->>'start',
       -- Provider examples show marketValue, but plan coverage/currency/history
       -- are not guaranteed. EUR valuations require an explicit dated import.
       NULL::numeric
FROM raw.football_data r
LEFT JOIN meta.pipeline_runs run ON run.run_id = r.run_id
CROSS JOIN LATERAL jsonb_array_elements(
    CASE WHEN r.endpoint ~ '^teams/[0-9]+$' THEN jsonb_build_array(r.payload)
         ELSE COALESCE(r.payload->'teams', '[]'::jsonb) END
) AS t
CROSS JOIN LATERAL (
    SELECT NULLIF(count(*), 0)::integer AS squad_size,
           avg(((greatest(r.ingested_at, run.finished_at) AT TIME ZONE 'UTC')::date - birth_date) / 365.2425) AS squad_avg_age,
           min(((greatest(r.ingested_at, run.finished_at) AT TIME ZONE 'UTC')::date - birth_date) / 365.2425) AS squad_min_age,
           max(((greatest(r.ingested_at, run.finished_at) AT TIME ZONE 'UTC')::date - birth_date) / 365.2425) AS squad_max_age,
           NULLIF(count(DISTINCT nationality), 0)::integer AS squad_nationalities,
           CASE WHEN count(*) > 0 AND count(nationality) = count(*)
                          AND t->'area'->>'name' IS NOT NULL
                THEN count(*) FILTER (WHERE nationality <> t->'area'->>'name')::integer
           END AS squad_foreign_players,
           CASE WHEN count(*) > 0 THEN count(*) FILTER (WHERE role = 'GK')::integer
           END AS squad_goalkeepers,
           CASE WHEN count(*) > 0 THEN count(*) FILTER (WHERE role = 'DF')::integer
           END AS squad_defenders,
           CASE WHEN count(*) > 0 THEN count(*) FILTER (WHERE role = 'MF')::integer
           END AS squad_midfielders,
           CASE WHEN count(*) > 0 THEN count(*) FILTER (WHERE role = 'FW')::integer
           END AS squad_attackers,
           CASE WHEN count(*) > 0 THEN count(*) FILTER (WHERE role = 'UNKNOWN')::integer
           END AS squad_unknown_positions,
           CASE WHEN count(*) > 0 THEN count(*) FILTER (WHERE birth_date IS NULL)::integer
           END AS squad_missing_birthdates
    FROM (
        SELECT DISTINCT ON (player->>'id')
               NULLIF(player->>'dateOfBirth', '')::date AS birth_date,
               NULLIF(player->>'nationality', '') AS nationality,
               CASE
                   WHEN lower(player->>'position') ~ 'keeper' THEN 'GK'
                   WHEN lower(player->>'position') ~ 'defen|defence|back' THEN 'DF'
                   WHEN lower(player->>'position') ~ 'midfield' THEN 'MF'
                   WHEN lower(player->>'position') ~ 'offen|offence|attack|forward|wing|striker' THEN 'FW'
                   ELSE 'UNKNOWN'
               END AS role
        FROM jsonb_array_elements(COALESCE(NULLIF(t->'squad', 'null'::jsonb), '[]'::jsonb)) player
        WHERE player->>'id' IS NOT NULL
        ORDER BY player->>'id', player::text
    ) players
) p
WHERE r.ingestion_date <= %(logical_date)s
  AND (r.endpoint ~ '^competitions/[^/]+/teams$' OR r.endpoint ~ '^teams/[0-9]+$')
  AND t->>'id' IS NOT NULL
  -- Season-filtered squad responses may describe an old roster. Observation
  -- time alone does not make an old roster valid for a current fixture.
  AND NOT (r.request_params ? 'season');

INSERT INTO staging.team_context_snapshot (snapshot_id, team_id, source, source_url, observed_at, valid_from, valid_until, squad_size, squad_avg_age, squad_min_age, squad_max_age, squad_nationalities, squad_foreign_players, squad_goalkeepers, squad_defenders, squad_midfielders, squad_attackers, squad_unknown_positions, squad_missing_birthdates, coach_id, coach_name, coach_birth_date, coach_nationality, coach_tenure_start, coach_contract_start, squad_market_value_eur)
WITH imports AS (
    SELECT DISTINCT ON (j->>'team_id', j->>'source', j->>'observed_at', j->>'valid_from')
           j
    FROM raw.team_context_import r
    CROSS JOIN LATERAL jsonb_array_elements(r.payload->'snapshots') AS j
    WHERE r.ingestion_date <= %(logical_date)s
    ORDER BY j->>'team_id', j->>'source', j->>'observed_at', j->>'valid_from',
             r.ingested_at DESC, r.import_id DESC
)
SELECT 'csv:' || md5(concat_ws('|', j->>'team_id', j->>'source',
                              j->>'observed_at', j->>'valid_from')),
       (j->>'team_id')::bigint, j->>'source', j->>'source_url',
       (j->>'observed_at')::timestamptz, (j->>'valid_from')::timestamptz,
       NULLIF(j->>'valid_until', '')::timestamptz,
       NULLIF(j->>'squad_size', '')::integer AS squad_size,
       NULLIF(j->>'squad_avg_age', '')::numeric AS squad_avg_age,
       NULLIF(j->>'squad_min_age', '')::numeric AS squad_min_age,
       NULLIF(j->>'squad_max_age', '')::numeric AS squad_max_age,
       NULLIF(j->>'squad_nationalities', '')::integer AS squad_nationalities,
       NULLIF(j->>'squad_foreign_players', '')::integer AS squad_foreign_players,
       NULLIF(j->>'squad_goalkeepers', '')::integer AS squad_goalkeepers,
       NULLIF(j->>'squad_defenders', '')::integer AS squad_defenders,
       NULLIF(j->>'squad_midfielders', '')::integer AS squad_midfielders,
       NULLIF(j->>'squad_attackers', '')::integer AS squad_attackers,
       NULLIF(j->>'squad_unknown_positions', '')::integer AS squad_unknown_positions,
       NULLIF(j->>'squad_missing_birthdates', '')::integer AS squad_missing_birthdates,
       NULLIF(j->>'coach_id', '')::text AS coach_id,
       NULLIF(j->>'coach_name', '')::text AS coach_name,
       NULLIF(j->>'coach_birth_date', '')::date AS coach_birth_date,
       NULLIF(j->>'coach_nationality', '')::text AS coach_nationality,
       NULLIF(j->>'coach_tenure_start', '')::date AS coach_tenure_start,
       NULL::text AS coach_contract_start,
       NULLIF(j->>'squad_market_value_eur', '')::numeric AS squad_market_value_eur
FROM imports;

-- Keep individual players as well as match aggregates for later research.
INSERT INTO staging.team_player_snapshot
    (snapshot_id, player_id, player_name, position, birth_date, nationality, shirt_number)
SELECT DISTINCT ON (s.snapshot_id, player->>'id')
       s.snapshot_id, (player->>'id')::bigint, player->>'name', player->>'position',
       NULLIF(player->>'dateOfBirth', '')::date, player->>'nationality',
       NULLIF(player->>'shirtNumber', '')::integer
FROM raw.football_data r
CROSS JOIN LATERAL jsonb_array_elements(
    CASE WHEN r.endpoint ~ '^teams/[0-9]+$' THEN jsonb_build_array(r.payload)
         ELSE COALESCE(r.payload->'teams', '[]'::jsonb) END
) t
JOIN staging.team_context_snapshot s
  ON s.snapshot_id = 'football:' || r.raw_id || ':' || (t->>'id')
CROSS JOIN LATERAL jsonb_array_elements(COALESCE(NULLIF(t->'squad', 'null'::jsonb), '[]'::jsonb)) player
WHERE player->>'id' IS NOT NULL
ORDER BY s.snapshot_id, player->>'id', player::text;

DELETE FROM curated.fact_match_team_context;

INSERT INTO curated.fact_match_team_context
    (match_id, team_id, context_observed_at, context_source, context_age_days, squad_source, squad_observed_at, squad_size, squad_avg_age, squad_min_age, squad_max_age, squad_nationalities, squad_foreign_players, squad_goalkeepers, squad_defenders, squad_midfielders, squad_attackers, squad_unknown_positions, squad_missing_birthdates, coach_id, coach_name, coach_age, coach_nationality, coach_tenure_days, coach_observed_tenure_days, coach_prior_matches, coach_prior_win_rate, coach_prior_points_per_match, coach_source, coach_observed_at, squad_market_value_eur, market_value_observed_at, market_value_source)
WITH appearances AS (
    SELECT m.match_id, m.home_team_id AS team_id, m.utc_kickoff, m.is_finished,
           CASE WHEN s.home_goals_90min > s.away_goals_90min THEN 3
                WHEN s.home_goals_90min = s.away_goals_90min THEN 1
                WHEN s.home_goals_90min < s.away_goals_90min THEN 0 END AS points
    FROM curated.fact_match m JOIN staging.matches s USING (match_id)
    UNION ALL
    SELECT m.match_id, m.away_team_id, m.utc_kickoff, m.is_finished,
           CASE WHEN s.away_goals_90min > s.home_goals_90min THEN 3
                WHEN s.away_goals_90min = s.home_goals_90min THEN 1
                WHEN s.away_goals_90min < s.home_goals_90min THEN 0 END
    FROM curated.fact_match m JOIN staging.matches s USING (match_id)
), assigned AS (
    SELECT m.*,
           greatest(s.observed_at, c.observed_at, v.observed_at) AS context_observed_at,
           NULLIF(concat_ws('; ', s.source, c.source, v.source), '') AS context_source,
           EXTRACT(epoch FROM m.utc_kickoff - greatest(s.observed_at, c.observed_at, v.observed_at))
               / 86400 AS context_age_days,
           s.source AS squad_source, s.observed_at AS squad_observed_at,
           s.squad_size,
           s.squad_avg_age + EXTRACT(epoch FROM m.utc_kickoff - s.observed_at)
               / (86400 * 365.2425) AS squad_avg_age,
           s.squad_min_age + EXTRACT(epoch FROM m.utc_kickoff - s.observed_at)
               / (86400 * 365.2425) AS squad_min_age,
           s.squad_max_age + EXTRACT(epoch FROM m.utc_kickoff - s.observed_at)
               / (86400 * 365.2425) AS squad_max_age,
           s.squad_nationalities,
           s.squad_foreign_players,
           s.squad_goalkeepers,
           s.squad_defenders,
           s.squad_midfielders,
           s.squad_attackers,
           s.squad_unknown_positions,
           s.squad_missing_birthdates,
           c.coach_id, c.coach_name,
           ((m.utc_kickoff AT TIME ZONE 'UTC')::date - c.coach_birth_date) / 365.2425 AS coach_age,
           c.coach_nationality,
           CASE WHEN c.coach_tenure_start <= (m.utc_kickoff AT TIME ZONE 'UTC')::date
                THEN (m.utc_kickoff AT TIME ZONE 'UTC')::date - c.coach_tenure_start
           END AS coach_tenure_days,
           ((m.utc_kickoff AT TIME ZONE 'UTC')::date
             - (first_coach.observed_at AT TIME ZONE 'UTC')::date) AS coach_observed_tenure_days,
           c.source AS coach_source, c.observed_at AS coach_observed_at,
           v.squad_market_value_eur, v.observed_at AS market_value_observed_at,
           v.source AS market_value_source
    FROM appearances m
    LEFT JOIN LATERAL (
        SELECT x.* FROM staging.team_context_snapshot x
        WHERE x.team_id = m.team_id AND x.squad_size IS NOT NULL
          AND x.observed_at < m.utc_kickoff AND x.valid_from <= m.utc_kickoff
          AND (x.valid_until IS NULL OR m.utc_kickoff < x.valid_until)
        ORDER BY x.observed_at DESC, x.valid_from DESC, x.snapshot_id DESC LIMIT 1
    ) s ON TRUE
    LEFT JOIN LATERAL (
        SELECT x.* FROM staging.team_context_snapshot x
        WHERE x.team_id = m.team_id AND x.coach_id IS NOT NULL
          AND x.observed_at < m.utc_kickoff AND x.valid_from <= m.utc_kickoff
          AND (x.valid_until IS NULL OR m.utc_kickoff < x.valid_until)
        ORDER BY x.observed_at DESC, x.valid_from DESC, x.snapshot_id DESC LIMIT 1
    ) c ON TRUE
    LEFT JOIN LATERAL (
        SELECT min(x.observed_at) AS observed_at
        FROM staging.team_context_snapshot x
        WHERE x.team_id = m.team_id AND x.coach_id = c.coach_id
          AND x.observed_at <= c.observed_at AND x.valid_from <= m.utc_kickoff
          AND NOT EXISTS (
              SELECT 1 FROM staging.team_context_snapshot previous
              WHERE previous.team_id = m.team_id AND previous.coach_id <> c.coach_id
                AND previous.observed_at > x.observed_at
                AND previous.observed_at < c.observed_at
                AND previous.valid_from <= m.utc_kickoff
          )
    ) first_coach ON TRUE
    LEFT JOIN LATERAL (
        SELECT x.* FROM staging.team_context_snapshot x
        WHERE x.team_id = m.team_id AND x.squad_market_value_eur IS NOT NULL
          AND x.observed_at < m.utc_kickoff AND x.valid_from <= m.utc_kickoff
          AND (x.valid_until IS NULL OR m.utc_kickoff < x.valid_until)
        ORDER BY x.observed_at DESC, x.valid_from DESC, x.snapshot_id DESC LIMIT 1
    ) v ON TRUE
), coach_stats AS (
    SELECT a.*,
           CASE WHEN coach_id IS NOT NULL THEN count(*) FILTER (WHERE is_finished AND points IS NOT NULL) OVER prior
           END AS coach_prior_matches,
           CASE WHEN coach_id IS NOT NULL
                THEN avg(CASE WHEN points = 3 THEN 1.0 ELSE 0.0 END)
                     FILTER (WHERE is_finished AND points IS NOT NULL) OVER prior END AS coach_prior_win_rate,
           CASE WHEN coach_id IS NOT NULL
                THEN avg(points) FILTER (WHERE is_finished AND points IS NOT NULL) OVER prior END AS coach_prior_points_per_match
    FROM assigned a
    WINDOW prior AS (
        PARTITION BY coach_id ORDER BY utc_kickoff
        RANGE BETWEEN UNBOUNDED PRECEDING AND INTERVAL '3 hours 1 microsecond' PRECEDING
    )
)
SELECT match_id, team_id,
       context_observed_at,
       context_source,
       context_age_days,
       squad_source,
       squad_observed_at,
       squad_size,
       squad_avg_age,
       squad_min_age,
       squad_max_age,
       squad_nationalities,
       squad_foreign_players,
       squad_goalkeepers,
       squad_defenders,
       squad_midfielders,
       squad_attackers,
       squad_unknown_positions,
       squad_missing_birthdates,
       coach_id,
       coach_name,
       coach_age,
       coach_nationality,
       coach_tenure_days,
       coach_observed_tenure_days,
       coach_prior_matches,
       coach_prior_win_rate,
       coach_prior_points_per_match,
       coach_source,
       coach_observed_at,
       squad_market_value_eur,
       market_value_observed_at,
       market_value_source
FROM coach_stats;
