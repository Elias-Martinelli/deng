-- Curated layer: the data product.
--
-- Every table states its grain, because "what does one row represent?" is an
-- explicit requirement of the module and the first question at the defence.

CREATE TABLE IF NOT EXISTS curated.dim_team (
    team_id             BIGINT PRIMARY KEY,
    name                TEXT   NOT NULL,
    short_name          TEXT,
    tla                 TEXT,
    country             TEXT,
    venue               TEXT,
    crest_url           TEXT,
    competitions        TEXT[] NOT NULL DEFAULT '{}',
    -- True when the club's domestic league is covered by our API tier (false for
    -- 11 of 36, evidence §9). Descriptive only - form is CL-only (ADR-004).
    has_domestic_coverage BOOLEAN NOT NULL,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE curated.dim_team IS
    'Grain: one row per team. Dimension - descriptive attributes, no measures.';
COMMENT ON COLUMN curated.dim_team.has_domestic_coverage IS
    'False for clubs whose domestic league the free tier does not cover. Descriptive only: form uses Champions League matches for every club (ADR-004).';

CREATE TABLE IF NOT EXISTS curated.fact_match (
    match_id        BIGINT      PRIMARY KEY,
    season_id       BIGINT      NOT NULL,
    utc_kickoff     TIMESTAMPTZ NOT NULL,
    match_date      DATE        NOT NULL,
    stage           TEXT        NOT NULL,
    matchday        INTEGER,
    status          TEXT        NOT NULL,
    -- Derived, not copied: the source's status vocabulary mixes "scheduled"
    -- and "timed"; downstream only ever needs "has this been played".
    is_finished     BOOLEAN     NOT NULL,
    is_upcoming     BOOLEAN     NOT NULL,
    home_team_id    BIGINT      NOT NULL REFERENCES curated.dim_team (team_id),
    away_team_id    BIGINT      NOT NULL REFERENCES curated.dim_team (team_id),
    home_goals      INTEGER,
    away_goals      INTEGER,
    goal_difference INTEGER,
    outcome         TEXT        CHECK (outcome IN ('HOME_WIN', 'DRAW', 'AWAY_WIN')),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fact_match_teams_differ CHECK (home_team_id <> away_team_id),
    CONSTRAINT fact_match_finished_has_score
        CHECK (NOT is_finished OR (home_goals IS NOT NULL AND away_goals IS NOT NULL))
);

COMMENT ON TABLE curated.fact_match IS
    'Grain: one row represents one UEFA Champions League match. Fact table; measures are the goals and the derived outcome.';
COMMENT ON COLUMN curated.fact_match.outcome IS
    'HOME_WIN / DRAW / AWAY_WIN - the ML target label. NULL until the match is finished.';
COMMENT ON COLUMN curated.fact_match.is_upcoming IS
    'Derived from the kick-off time, not from status: ?status=SCHEDULED returns rows stored as TIMED.';

CREATE INDEX IF NOT EXISTS fact_match_date_idx     ON curated.fact_match (match_date);
CREATE INDEX IF NOT EXISTS fact_match_upcoming_idx ON curated.fact_match (is_upcoming, utc_kickoff);

CREATE TABLE IF NOT EXISTS curated.fact_team_match_form (
    match_id            BIGINT  NOT NULL REFERENCES curated.fact_match (match_id) ON DELETE CASCADE,
    team_id             BIGINT  NOT NULL REFERENCES curated.dim_team (team_id),
    is_home             BOOLEAN NOT NULL,
    opponent_team_id    BIGINT  NOT NULL REFERENCES curated.dim_team (team_id),

    -- Rolling window over the team's last completed matches BEFORE this match.
    -- matches_considered is part of the data, not metadata: comparing a form
    -- built on 5 matches with one built on 1 would be misleading, and for 11 of
    -- 36 clubs the small window is the normal case.
    matches_considered  INTEGER NOT NULL,
    wins_last_5         INTEGER NOT NULL,
    draws_last_5        INTEGER NOT NULL,
    losses_last_5       INTEGER NOT NULL,
    goals_scored_last_5 INTEGER NOT NULL,
    goals_conceded_last_5 INTEGER NOT NULL,
    goal_difference_last_5 INTEGER NOT NULL,
    points_last_5       INTEGER NOT NULL,
    days_since_last_match INTEGER,

    computed_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (match_id, team_id),
    CONSTRAINT form_window_is_bounded CHECK (matches_considered BETWEEN 0 AND 5),
    CONSTRAINT form_counts_add_up
        CHECK (wins_last_5 + draws_last_5 + losses_last_5 = matches_considered)
);

COMMENT ON TABLE curated.fact_team_match_form IS
    'Grain: one row represents one team''s participation in one match, with that team''s form going into it.';
COMMENT ON COLUMN curated.fact_team_match_form.matches_considered IS
    'How many completed matches the window is based on (0-5). Never compare forms with different values without saying so.';
COMMENT ON CONSTRAINT form_counts_add_up ON curated.fact_team_match_form IS
    'The API''s own aggregates fail exactly this check (evidence §8), which is why we compute ours and enforce it.';
