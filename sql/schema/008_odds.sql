-- Bookmaker odds and the model forecast they are compared with.
--
-- Two new sources of change enter the model here, and they move at different
-- speeds. Odds change minute by minute before a match; the model forecast
-- changes once per pipeline run. The tables keep both as *history*, each row
-- stamped with the moment the source said it and the moment we fetched it, so
-- a comparison can always pair a forecast with the odds that existed at the
-- same time - never a 14:00 forecast with tomorrow's odds.
--
-- Requires PostgreSQL 15+ (UNIQUE NULLS NOT DISTINCT); Compose and CI use 16.

-- --------------------------------------------------------------------------
-- Raw zone for The Odds API. Grain: one row per fetch - the JSON array of
-- events exactly as received. Append-only by design: unlike the daily
-- football payloads, the point of this source is the intraday history, so a
-- second fetch on the same day is a new row, not an overwrite. The key holds
-- the fetch time; replayed samples carry the sample's own time and therefore
-- stay idempotent.
-- --------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw.odds_api (
    raw_id              BIGSERIAL   PRIMARY KEY,
    source              TEXT        NOT NULL DEFAULT 'the-odds-api.com',
    endpoint            TEXT        NOT NULL,          -- 'sports/soccer_uefa_champs_league/odds'
    request_params      JSONB       NOT NULL DEFAULT '{}'::jsonb,  -- never contains the key
    request_url         TEXT        NOT NULL,          -- never contains the key
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT now(),  -- the fetch time
    run_id              UUID        NOT NULL REFERENCES meta.pipeline_runs (run_id),
    payload             JSONB       NOT NULL,          -- JSON array of events
    payload_hash        TEXT        NOT NULL,
    event_count         INTEGER,
    -- Quota bookkeeping from the response headers: what the free tier has left
    -- this month, how much was used, and what this call cost. Stored per fetch
    -- so the app can say "quota reserve reached - last state from 14:05".
    requests_remaining  INTEGER,
    requests_used       INTEGER,
    requests_last       INTEGER,
    CONSTRAINT odds_api_unique_per_fetch UNIQUE (source, endpoint, request_params, ingested_at)
);

COMMENT ON TABLE raw.odds_api IS
    'Grain: one row per fetch from The Odds API - the array of events with every bookmaker''s odds at that moment.';
COMMENT ON COLUMN raw.odds_api.requests_remaining IS
    'x-requests-remaining header: credits left in the monthly quota after this call.';

CREATE INDEX IF NOT EXISTS odds_api_ingested_idx ON raw.odds_api (ingested_at DESC);

-- --------------------------------------------------------------------------
-- Staging: one row per quoted outcome. Shape only - the names are the
-- bookmaker's, the fixture is resolved separately (odds_event_match).
-- --------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS staging.bookmaker_odds (
    raw_id              BIGINT      NOT NULL REFERENCES raw.odds_api (raw_id) ON DELETE CASCADE,
    fetched_at          TIMESTAMPTZ NOT NULL,          -- when we asked
    event_id            TEXT        NOT NULL,          -- the API's event id
    commence_time       TIMESTAMPTZ NOT NULL,
    home_team_name      TEXT        NOT NULL,          -- as the bookmakers spell it
    away_team_name      TEXT        NOT NULL,
    bookmaker_key       TEXT        NOT NULL,
    bookmaker_title     TEXT        NOT NULL,
    market_key          TEXT        NOT NULL,          -- 'h2h' = 1X2, regular time incl. stoppage
    source_updated_at   TIMESTAMPTZ NOT NULL,          -- when the bookmaker last changed it
    outcome_role        TEXT        NOT NULL CHECK (outcome_role IN ('HOME', 'DRAW', 'AWAY')),
    outcome_name        TEXT        NOT NULL,
    price               NUMERIC(9, 3) NOT NULL CHECK (price >= 1),  -- decimal odds
    loaded_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (raw_id, event_id, bookmaker_key, market_key, outcome_role)
);

COMMENT ON TABLE staging.bookmaker_odds IS
    'Grain: one row per fetch, event, bookmaker, market and outcome - a quoted decimal price.';

CREATE INDEX IF NOT EXISTS staging_bookmaker_odds_event_idx ON staging.bookmaker_odds (event_id);

-- Which fixture an event is. Filled by the name matcher in Python
-- (deng.ingestion.odds.match_events); kept as a table so the decision is
-- inspectable and an unmatched event stays visible until someone adds an alias.
CREATE TABLE IF NOT EXISTS staging.odds_event_match (
    event_id            TEXT        PRIMARY KEY,
    match_id            BIGINT,                         -- NULL: no fixture matched
    commence_time       TIMESTAMPTZ NOT NULL,
    home_team_name      TEXT        NOT NULL,
    away_team_name      TEXT        NOT NULL,
    method              TEXT        NOT NULL CHECK (method IN ('NAME', 'UNMATCHED')),
    confidence          NUMERIC(4, 3),
    note                TEXT,
    matched_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT odds_event_match_consistent CHECK ((method = 'UNMATCHED') = (match_id IS NULL))
);

COMMENT ON TABLE staging.odds_event_match IS
    'Grain: one row per bookmaker event - the Champions League match it was resolved to, or UNMATCHED.';

-- --------------------------------------------------------------------------
-- Curated: the model forecast, versioned.
-- Grain: one row per match, model version and run date. Every run writes the
-- day's forecast, so how the forecast moved towards kick-off stays queryable
-- and a comparison can pick the forecast that existed when the odds were read.
-- --------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS curated.fact_match_prediction (
    match_id                  BIGINT      NOT NULL REFERENCES curated.fact_match (match_id) ON DELETE CASCADE,
    model_version             TEXT        NOT NULL,
    as_of_date                DATE        NOT NULL,     -- the run's logical date
    predicted_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- False once the forecast was computed after kick-off. Its *features* are
    -- still pre-match (the form table is point-in-time), so it is usable for a
    -- retrospective quality comparison - but it is not what was known before.
    is_pre_match              BOOLEAN     NOT NULL,
    home_prob                 NUMERIC(6, 5) NOT NULL,
    draw_prob                 NUMERIC(6, 5) NOT NULL,
    away_prob                 NUMERIC(6, 5) NOT NULL,
    expected_home_goals       NUMERIC(6, 3),
    expected_away_goals       NUMERIC(6, 3),
    home_matches_considered   INTEGER     NOT NULL,
    away_matches_considered   INTEGER     NOT NULL,
    league_matches_considered INTEGER     NOT NULL,
    PRIMARY KEY (match_id, model_version, as_of_date),
    CONSTRAINT prediction_probabilities_sum_to_one
        CHECK (abs(home_prob + draw_prob + away_prob - 1) < 0.001),
    CONSTRAINT prediction_probabilities_in_range
        CHECK (home_prob > 0 AND draw_prob > 0 AND away_prob > 0)
);

COMMENT ON TABLE curated.fact_match_prediction IS
    'Grain: one row per match, model version and run date - the model''s HOME/DRAW/AWAY probabilities as of that run.';
COMMENT ON COLUMN curated.fact_match_prediction.is_pre_match IS
    'True when the forecast was computed before kick-off. A forecast shown during or after a match is a pre-match forecast, never a live one.';

-- --------------------------------------------------------------------------
-- Curated: one row per odds change.
-- Grain: one row per match, bookmaker, market, source timestamp and price
-- triple. A bookmaker that quotes the same prices for hours has one row with
-- a widening [first_seen_at, last_seen_at]; every change adds a row.
-- --------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS curated.fact_bookmaker_odds (
    odds_id             BIGSERIAL   PRIMARY KEY,
    match_id            BIGINT      NOT NULL REFERENCES curated.fact_match (match_id) ON DELETE CASCADE,
    bookmaker_key       TEXT        NOT NULL,
    bookmaker_title     TEXT        NOT NULL,
    market_key          TEXT        NOT NULL,
    source_updated_at   TIMESTAMPTZ NOT NULL,          -- the bookmaker's own timestamp
    first_seen_at       TIMESTAMPTZ NOT NULL,          -- first fetch that showed these prices
    last_seen_at        TIMESTAMPTZ NOT NULL,          -- latest fetch that still showed them
    home_price          NUMERIC(9, 3),
    draw_price          NUMERIC(9, 3),
    away_price          NUMERIC(9, 3),
    -- False when the bookmaker quoted fewer than the three outcomes: a
    -- suspended or partial market. Kept, and flagged, rather than dropped.
    is_complete         BOOLEAN     NOT NULL,
    -- Bookmaker margin: sum of implied probabilities minus one (0.05 = 5 %).
    overround           NUMERIC(7, 5),
    -- Implied probabilities with the margin removed, from the three prices of
    -- the same bookmaker at the same moment: (1/price) / sum(1/price).
    home_prob_fair      NUMERIC(6, 5),
    draw_prob_fair      NUMERIC(6, 5),
    away_prob_fair      NUMERIC(6, 5),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT bookmaker_odds_one_row_per_change
        UNIQUE NULLS NOT DISTINCT (match_id, bookmaker_key, market_key, source_updated_at,
                                   home_price, draw_price, away_price),
    CONSTRAINT bookmaker_odds_complete_has_probabilities
        CHECK (is_complete = (home_prob_fair IS NOT NULL)),
    CONSTRAINT bookmaker_odds_seen_in_order CHECK (first_seen_at <= last_seen_at)
);

COMMENT ON TABLE curated.fact_bookmaker_odds IS
    'Grain: one row per match, bookmaker, market and distinct quote (source timestamp + prices) - i.e. one row per odds change, with the fetch interval that observed it.';
COMMENT ON COLUMN curated.fact_bookmaker_odds.home_prob_fair IS
    'Implied probability with the bookmaker margin removed, always from the three prices of the same bookmaker and moment.';

CREATE INDEX IF NOT EXISTS fact_bookmaker_odds_match_idx
    ON curated.fact_bookmaker_odds (match_id, bookmaker_key, last_seen_at DESC);

-- --------------------------------------------------------------------------
-- Views for consumers. Dropped and recreated (not CREATE OR REPLACE) so a
-- column change here applies on the next `make init` instead of failing.
-- --------------------------------------------------------------------------
-- CASCADE because curated.model_features (011) reads two of these views; the
-- next file recreates it. Without CASCADE, re-applying the DDL would fail as
-- soon as anything depends on them.
DROP VIEW IF EXISTS curated.odds_comparison_latest CASCADE;
DROP VIEW IF EXISTS curated.bookmaker_odds_latest CASCADE;
DROP VIEW IF EXISTS curated.match_prediction_latest CASCADE;

-- The newest quote per match, bookmaker and market, plus whether the newest
-- fetch overall still showed it. A quote the latest fetch no longer carries
-- means the bookmaker withdrew or suspended the market - that is what
-- is_current = false tells the app to say.
CREATE VIEW curated.bookmaker_odds_latest AS
WITH latest_fetch AS (
    SELECT max(ingested_at) AS latest_fetch_at FROM raw.odds_api
)
SELECT DISTINCT ON (o.match_id, o.bookmaker_key, o.market_key)
       o.odds_id, o.match_id, o.bookmaker_key, o.bookmaker_title, o.market_key,
       o.source_updated_at, o.first_seen_at, o.last_seen_at,
       o.home_price, o.draw_price, o.away_price, o.is_complete, o.overround,
       o.home_prob_fair, o.draw_prob_fair, o.away_prob_fair,
       f.latest_fetch_at,
       o.last_seen_at >= f.latest_fetch_at AS is_current
  FROM curated.fact_bookmaker_odds o
 CROSS JOIN latest_fetch f
 ORDER BY o.match_id, o.bookmaker_key, o.market_key, o.last_seen_at DESC, o.source_updated_at DESC;

COMMENT ON VIEW curated.bookmaker_odds_latest IS
    'Grain: one row per match, bookmaker and market - the newest quote, flagged when the latest fetch no longer carried it.';

CREATE VIEW curated.match_prediction_latest AS
SELECT DISTINCT ON (match_id, model_version) *
  FROM curated.fact_match_prediction
 ORDER BY match_id, model_version, as_of_date DESC, predicted_at DESC;

COMMENT ON VIEW curated.match_prediction_latest IS
    'Grain: one row per match and model version - the newest forecast.';

-- Model against market, side by side, with the two timestamps kept apart.
-- The deviation is in percentage points and is a *model deviation*: how far
-- our probability is from the margin-free market probability. It is not a
-- betting edge - the baseline model is far too simple for that claim.
CREATE VIEW curated.odds_comparison_latest AS
SELECT p.match_id, p.model_version, p.predicted_at, p.as_of_date, p.is_pre_match,
       o.bookmaker_key, o.bookmaker_title, o.market_key,
       o.source_updated_at, o.last_seen_at AS odds_fetched_at, o.latest_fetch_at,
       o.is_current, o.is_complete, o.overround,
       p.home_prob, p.draw_prob, p.away_prob,
       round(1 / p.home_prob, 2) AS home_model_odds,
       round(1 / p.draw_prob, 2) AS draw_model_odds,
       round(1 / p.away_prob, 2) AS away_model_odds,
       o.home_price, o.draw_price, o.away_price,
       o.home_prob_fair, o.draw_prob_fair, o.away_prob_fair,
       round((p.home_prob - o.home_prob_fair) * 100, 1) AS home_deviation_pp,
       round((p.draw_prob - o.draw_prob_fair) * 100, 1) AS draw_deviation_pp,
       round((p.away_prob - o.away_prob_fair) * 100, 1) AS away_deviation_pp
  FROM curated.match_prediction_latest p
  JOIN curated.bookmaker_odds_latest o USING (match_id);

COMMENT ON VIEW curated.odds_comparison_latest IS
    'Grain: one row per match, model version, bookmaker and market - newest forecast against newest quote, deviation in percentage points.';
