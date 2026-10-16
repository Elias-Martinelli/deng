-- Dated team context: no current squad is joined to an earlier match.
CREATE TABLE IF NOT EXISTS raw.team_context_import (
    import_id BIGSERIAL PRIMARY KEY,
    payload_hash TEXT NOT NULL UNIQUE,
    request_url TEXT NOT NULL,
    ingestion_date DATE NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    run_id UUID NOT NULL REFERENCES meta.pipeline_runs(run_id),
    csv_text TEXT NOT NULL,
    payload JSONB NOT NULL,
    record_count INTEGER NOT NULL CHECK (record_count >= 0)
);
COMMENT ON TABLE raw.team_context_import IS
    'Grain: one immutable CSV file hash. Original CSV, normalized rows and import lineage.';

CREATE TABLE IF NOT EXISTS staging.team_context_snapshot (
    snapshot_id TEXT PRIMARY KEY,
    team_id BIGINT NOT NULL,
    source TEXT NOT NULL,
    source_url TEXT NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    valid_from TIMESTAMPTZ NOT NULL,
    valid_until TIMESTAMPTZ,
    squad_size INTEGER,
    squad_avg_age NUMERIC,
    squad_min_age NUMERIC,
    squad_max_age NUMERIC,
    squad_nationalities INTEGER,
    squad_foreign_players INTEGER,
    squad_goalkeepers INTEGER,
    squad_defenders INTEGER,
    squad_midfielders INTEGER,
    squad_attackers INTEGER,
    squad_unknown_positions INTEGER,
    squad_missing_birthdates INTEGER,
    coach_id TEXT,
    coach_name TEXT,
    coach_birth_date DATE,
    coach_nationality TEXT,
    coach_tenure_start DATE,
    coach_contract_start TEXT,
    squad_market_value_eur NUMERIC CHECK (squad_market_value_eur >= 0),
    CHECK (valid_until IS NULL OR valid_until > valid_from)
);
CREATE INDEX IF NOT EXISTS team_context_snapshot_lookup_idx
    ON staging.team_context_snapshot(team_id, observed_at DESC, valid_from);

CREATE TABLE IF NOT EXISTS staging.team_player_snapshot (
    snapshot_id TEXT NOT NULL REFERENCES staging.team_context_snapshot(snapshot_id) ON DELETE CASCADE,
    player_id BIGINT NOT NULL,
    player_name TEXT,
    position TEXT,
    birth_date DATE,
    nationality TEXT,
    shirt_number INTEGER,
    PRIMARY KEY (snapshot_id, player_id)
);
COMMENT ON TABLE staging.team_player_snapshot IS
    'Grain: one player in one observed team squad. Player history is never inferred from a season parameter.';

CREATE TABLE IF NOT EXISTS curated.fact_match_team_context (
    match_id BIGINT NOT NULL REFERENCES curated.fact_match(match_id) ON DELETE CASCADE,
    team_id BIGINT NOT NULL REFERENCES curated.dim_team(team_id) ON DELETE CASCADE,
    context_observed_at TIMESTAMPTZ,
    context_source TEXT,
    context_age_days NUMERIC,
    squad_source TEXT,
    squad_observed_at TIMESTAMPTZ,
    squad_size INTEGER,
    squad_avg_age NUMERIC,
    squad_min_age NUMERIC,
    squad_max_age NUMERIC,
    squad_nationalities INTEGER,
    squad_foreign_players INTEGER,
    squad_goalkeepers INTEGER,
    squad_defenders INTEGER,
    squad_midfielders INTEGER,
    squad_attackers INTEGER,
    squad_unknown_positions INTEGER,
    squad_missing_birthdates INTEGER,
    coach_id TEXT,
    coach_name TEXT,
    coach_age NUMERIC,
    coach_nationality TEXT,
    coach_tenure_days INTEGER,
    coach_observed_tenure_days INTEGER,
    coach_prior_matches BIGINT,
    coach_prior_win_rate NUMERIC,
    coach_prior_points_per_match NUMERIC,
    coach_source TEXT,
    coach_observed_at TIMESTAMPTZ,
    squad_market_value_eur NUMERIC,
    market_value_observed_at TIMESTAMPTZ,
    market_value_source TEXT,
    PRIMARY KEY (match_id, team_id)
);
COMMENT ON TABLE curated.fact_match_team_context IS
    'Grain: one team per match. Separate latest eligible squad, coach and EUR valuation; NULL means unavailable before kickoff.';
COMMENT ON COLUMN curated.fact_match_team_context.coach_prior_matches IS
    'Only matches with an observed pre-match coach assignment and kickoff at least 3 hours earlier; covered history, not lifetime career.';
COMMENT ON COLUMN curated.fact_match_team_context.coach_tenure_days IS
    'Days since an exact tenure start supplied by dated CSV; an API contract start month is not treated as an appointment.';
COMMENT ON COLUMN curated.fact_match_team_context.coach_observed_tenure_days IS
    'Lower bound: days since first eligible observation of this coach at this team, after the last observed different coach.';

CREATE OR REPLACE VIEW curated.match_context_features AS
SELECT m.match_id,
       h.context_observed_at AS home_context_observed_at,
       h.context_source AS home_context_source,
       h.context_age_days AS home_context_age_days,
       h.squad_source AS home_squad_source,
       h.squad_observed_at AS home_squad_observed_at,
       h.squad_size AS home_squad_size,
       h.squad_avg_age AS home_squad_avg_age,
       h.squad_min_age AS home_squad_min_age,
       h.squad_max_age AS home_squad_max_age,
       h.squad_nationalities AS home_squad_nationalities,
       h.squad_foreign_players AS home_squad_foreign_players,
       h.squad_goalkeepers AS home_squad_goalkeepers,
       h.squad_defenders AS home_squad_defenders,
       h.squad_midfielders AS home_squad_midfielders,
       h.squad_attackers AS home_squad_attackers,
       h.squad_unknown_positions AS home_squad_unknown_positions,
       h.squad_missing_birthdates AS home_squad_missing_birthdates,
       h.coach_id AS home_coach_id,
       h.coach_name AS home_coach_name,
       h.coach_age AS home_coach_age,
       h.coach_nationality AS home_coach_nationality,
       h.coach_tenure_days AS home_coach_tenure_days,
       h.coach_observed_tenure_days AS home_coach_observed_tenure_days,
       h.coach_prior_matches AS home_coach_prior_matches,
       h.coach_prior_win_rate AS home_coach_prior_win_rate,
       h.coach_prior_points_per_match AS home_coach_prior_points_per_match,
       h.coach_source AS home_coach_source,
       h.coach_observed_at AS home_coach_observed_at,
       h.squad_market_value_eur AS home_squad_market_value_eur,
       h.market_value_observed_at AS home_market_value_observed_at,
       h.market_value_source AS home_market_value_source,
       a.context_observed_at AS away_context_observed_at,
       a.context_source AS away_context_source,
       a.context_age_days AS away_context_age_days,
       a.squad_source AS away_squad_source,
       a.squad_observed_at AS away_squad_observed_at,
       a.squad_size AS away_squad_size,
       a.squad_avg_age AS away_squad_avg_age,
       a.squad_min_age AS away_squad_min_age,
       a.squad_max_age AS away_squad_max_age,
       a.squad_nationalities AS away_squad_nationalities,
       a.squad_foreign_players AS away_squad_foreign_players,
       a.squad_goalkeepers AS away_squad_goalkeepers,
       a.squad_defenders AS away_squad_defenders,
       a.squad_midfielders AS away_squad_midfielders,
       a.squad_attackers AS away_squad_attackers,
       a.squad_unknown_positions AS away_squad_unknown_positions,
       a.squad_missing_birthdates AS away_squad_missing_birthdates,
       a.coach_id AS away_coach_id,
       a.coach_name AS away_coach_name,
       a.coach_age AS away_coach_age,
       a.coach_nationality AS away_coach_nationality,
       a.coach_tenure_days AS away_coach_tenure_days,
       a.coach_observed_tenure_days AS away_coach_observed_tenure_days,
       a.coach_prior_matches AS away_coach_prior_matches,
       a.coach_prior_win_rate AS away_coach_prior_win_rate,
       a.coach_prior_points_per_match AS away_coach_prior_points_per_match,
       a.coach_source AS away_coach_source,
       a.coach_observed_at AS away_coach_observed_at,
       a.squad_market_value_eur AS away_squad_market_value_eur,
       a.market_value_observed_at AS away_market_value_observed_at,
       a.market_value_source AS away_market_value_source
FROM curated.fact_match m
LEFT JOIN curated.fact_match_team_context h ON h.match_id = m.match_id AND h.team_id = m.home_team_id
LEFT JOIN curated.fact_match_team_context a ON a.match_id = m.match_id AND a.team_id = m.away_team_id;
