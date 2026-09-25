# Analytical Data Model

The module requires that we state, for every final table, **what one row
represents**. Each grain below is also a `COMMENT ON TABLE` in the database, so
`\d+` and the notebook show the same answer as this document — documentation
that cannot drift away from the schema.

## Layers

```
raw          API payloads exactly as received (JSONB)     append/upsert per day
  ↓  shape only: flatten, cast, rename
staging      typed tables, one per source entity          rebuildable from raw
  ↓  business logic: derive, aggregate, join
curated      facts and dimensions - the data product      rebuildable from staging
```

Why three layers and not two: raw answers *what did the source say*, staging
answers *what does that mean in typed columns*, curated answers *what does the
use case need*. A bug in the last step costs one `make transform`, not a
re-fetch — which matters because the API has a 10-requests-per-minute budget.

## Curated tables

### `curated.fact_match` — fact

> **Grain: one row represents one UEFA Champions League match.**

| Column | Type | Notes |
|---|---|---|
| `match_id` | BIGINT PK | business key from the source, stable across seasons |
| `season_id` | BIGINT | needed because the same competition changes format between seasons |
| `utc_kickoff`, `match_date` | TIMESTAMPTZ, DATE | `match_date` is the partition key in BigQuery later |
| `stage`, `matchday`, `status` | TEXT, INT, TEXT | source values |
| `is_finished`, `is_upcoming` | BOOLEAN | **derived from the kick-off time, not from `status`** — see below |
| `home_team_id`, `away_team_id` | BIGINT FK → `dim_team` | constraint: must differ |
| `home_goals`, `away_goals`, `goal_difference` | INT | measures; NULL until played |
| `outcome` | TEXT | `HOME_WIN` / `DRAW` / `AWAY_WIN` — the ML target label |

Two deliberate derivations:

* `is_upcoming` comes from `utc_kickoff > now()`, not from the status string.
  The source returns rows stored as `TIMED` when queried with
  `?status=SCHEDULED`, so a predicate on the status text silently returns
  nothing (evidence §7). A time comparison cannot drift with the API's
  vocabulary.
* `outcome` is computed from the goals rather than copied from
  `score.winner`, so the label can never contradict the numbers in its own row.
  A data-quality check enforces exactly that.

### `curated.fact_team_match_form` — fact

> **Grain: one row represents one team's participation in one match, with that
> team's form going into it.** Exactly two rows per match.

| Column | Notes |
|---|---|
| `match_id`, `team_id` | composite PK |
| `is_home`, `opponent_team_id` | the match seen from this team's side |
| `matches_considered` | 0–5: how many completed matches the window rests on |
| `wins_last_5`, `draws_last_5`, `losses_last_5` | constraint: must sum to `matches_considered` |
| `goals_scored_last_5`, `goals_conceded_last_5`, `goal_difference_last_5` | |
| `points_last_5` | 3·wins + draws |
| `days_since_last_match` | rest before this match |

**The point-in-time rule:** a row for match *M* and team *T* may only use
matches that were finished *before M's kick-off*. Nothing from *M*, nothing
later. That is what makes these columns usable as model features without
leaking the result being predicted, and it is enforced twice — by the `LIMIT 5`
window in [`230_fact_team_match_form.sql`](../sql/transform/230_fact_team_match_form.sql)
and by the `form_uses_no_future_matches` data-quality check.

**Why `matches_considered` is a column and not a footnote:** early in a season
it is 0 or 1, and the league phase has at most 8 matches per club. A five-match form
and a one-match form are not comparable, and a consumer that cannot see the
difference will compare them anyway.

*Scope:* Champions League matches only, for every club
([ADR-004](adr/ADR-004-champions-league-scope.md)).

### `curated.dim_team` — dimension

> **Grain: one row represents one team.**

Descriptive attributes only: name, short name, TLA, country, venue, crest.
Plus `has_domestic_coverage`, a boolean that records whether the club's
domestic league exists in our API tier. Descriptive only since ADR-004.

### `curated.dim_venue` — dimension

> **Grain: one row represents one club's home venue** (keyed by `team_id`).

Keyed by the club rather than a venue id because in the league phase every
match is played at the home club's venue, and the source identifies venues only
by (outdated) name. Coordinates, time zone, the OSM reference they came from
and `coordinates_status` (`RESOLVED` / `NOT_AVAILABLE`). Built from
`data/reference/venues.csv` ([evidence](evidence/weather.md#2-venues-why-the-apis-venue-fields-could-not-be-geocoded-blindly)).
A neutral-venue final would need a venue key of its own - not before May.

### `curated.fact_match_weather` — fact

> **Grain: one row represents one match.**

The forecast for the hour containing the kick-off, from the **newest forecast
fetched before kick-off** (`forecast_fetched_at < utc_kickoff`) that the run
could know (`ingestion_date <= logical date`) - the same point-in-time rule as
the form table, guarded twice (SQL and `weather_fetched_before_kickoff`).

Every match has a row, and `weather_status` says why values are absent:

| Status | Meaning |
|---|---|
| `AVAILABLE` | values present (a constraint enforces: values ⇔ AVAILABLE) |
| `NOT_YET_AVAILABLE` | kick-off beyond the 16-day horizon |
| `VENUE_UNKNOWN` | the home venue has no verified coordinates |
| `NOT_CAPTURED` | played before any forecast was fetched; cannot be recovered |
| `MISSING` | inside the horizon, no forecast - a pipeline gap, reported by a WARNING check |

`lead_days` (match date − forecast date) is kept because a 1-day forecast and a
14-day forecast are different quality; a model should know which it gets.

### `curated.fact_match_prediction` — fact

> **Grain: one row represents one match, one model version and one run date** -
> the model's HOME / DRAW / AWAY probabilities as of that run.

Model `form-poisson-v1` ([`240_fact_match_prediction.sql`](../sql/transform/240_fact_match_prediction.sql)):
goals per side are Poisson with rates built from the league's average home and
away goals and each team's attack and defence strength from its last-5 window,
both shrunk towards a prior. Every input is restricted to matches finished
*before the kick-off of the match being predicted* - the same point-in-time
rule as the form table - so a forecast computed today for a finished match is
still built from pre-match information. Whether it was *computed* before
kick-off is a separate fact, `is_pre_match`. A rerun of the same day replaces
that day's forecast; a new day adds one, so how the forecast moved towards
kick-off stays queryable and a comparison can pick the forecast that existed
when the odds were read. Constraint: the three probabilities sum to 1.

A deliberately simple baseline: it is the thing the odds are compared with,
not a claim to beat the market (backlog 12.2 is the real model).

### `curated.fact_bookmaker_odds` — fact

> **Grain: one row represents one odds change: one match, one bookmaker, one
> market, one distinct quote** (the bookmaker's timestamp plus the three
> prices), with the fetch interval `[first_seen_at, last_seen_at]` in which
> the pipeline observed it.

| Column | Notes |
|---|---|
| `bookmaker_key`, `bookmaker_title` | the platform, as the API names it |
| `market_key` | `h2h`: 1X2 on regular time incl. stoppage time |
| `source_updated_at` | when the bookmaker last changed the quote (its own clock) |
| `first_seen_at`, `last_seen_at` | first and latest fetch that showed exactly this quote |
| `home_price`, `draw_price`, `away_price` | decimal odds; NULL when not quoted |
| `is_complete` | false when fewer than three outcomes were quoted (suspended / partial) |
| `overround` | bookmaker margin: sum of implied probabilities − 1 |
| `home_prob_fair`, `draw_prob_fair`, `away_prob_fair` | implied probabilities with the margin removed, **always from the three prices of the same bookmaker at the same moment** |

Two timestamps per row on purpose: "what the bookmaker said and when" and
"when we looked" are different facts, and the comparison shows both.

**Views for consumers:** `curated.bookmaker_odds_latest` (newest quote per
match, bookmaker and market, with `is_current` = still carried by the latest
fetch), `curated.match_prediction_latest` (newest forecast per match and
model) and `curated.odds_comparison_latest` (both joined: model probability,
model odds = 1/p, market odds, fair probability and the deviation in
percentage points - a *model deviation*, not a betting edge).

### `curated.team_crest` — view

One row per team with a stored crest, selecting from `raw.team_crests` by the
team's current crest URL. A view, because there is nothing to transform.

## Staging tables

| Table | Grain |
|---|---|
| `staging.matches` | one row per match |
| `staging.teams` | one row per team in the current season |
| `staging.standings` | **one row per team per season per ingestion date** — a point-in-time snapshot, because the table changes after every matchday |
| `staging.venues` | one row per club, loaded from `data/reference/venues.csv` on every weather run |
| `staging.weather_forecast` | **one row per venue per forecast hour per ingestion date** — every day's forecast is kept, so how a forecast evolved towards kick-off stays queryable |
| `staging.bookmaker_odds` | **one row per fetch, event, bookmaker, market and outcome** — a quoted price, with the bookmaker's own timestamp |
| `staging.odds_event_match` | one row per bookmaker event: the fixture it resolved to (kick-off time + name similarity + aliases), or `UNMATCHED` |

`staging.standings` is the one staging table whose grain includes the ingestion
date. That is intentional: it turns the league table into a time series and is
the seed for the match-snapshot idea in the final architecture.

## Operational tables

| Table | Grain |
|---|---|
| `raw.football_data` | one row per (source, endpoint, request parameters, ingestion date) — one API answer on one day |
| `raw.open_meteo` | one row per (endpoint, venue, ingestion date) — one forecast answer for one stadium on one day |
| `raw.odds_api` | one row per fetch — the array of events with every bookmaker's odds at that moment, plus the credits the API reported left |
| `raw.team_crests` | one row per crest URL — image bytes as received, fetched once |
| `meta.pipeline_runs` | one row per pipeline execution |
| `meta.dq_results` | one row per data-quality check per run |

## Dimensional view

`fact_match`, `fact_team_match_form`, `fact_match_weather`,
`fact_match_prediction` and `fact_bookmaker_odds` are the facts; `dim_team`
and `dim_venue` the dimensions. The last two are the only facts with a time
axis below the day: they record versions (forecast per run, quote per change)
rather than a state. `dim_date` is planned for the cloud
model, where a date dimension earns its place through partition pruning.
Locally it would only add joins.

```
     dim_venue ─── dim_team
         |        /        \
fact_match_weather   fact_match   fact_team_match_form
         |              |                 |
         +------------ match_id ----------+
```

## What is not modelled, and why

* **No group dimension.** Since the 2024/25 format change `group` is null in
  every row (evidence §5). A textbook design would have produced a table that
  is empty for every current-season match.
* **No odds from football-data.org.** Its field carries a marketing message,
  not data; odds come from The Odds API instead ([ADR-005](adr/ADR-005-bookmaker-odds-source.md)).
* **No line-ups, injuries or player data.** Not available on the free tier.
  The snapshot table in the final architecture reserves `NOT_AVAILABLE` states
  for them rather than pretending they are missing at random.

## Planned for the final (cloud) model

| Table | Grain | Partition | Cluster |
|---|---|---|---|
| `fact_match` | one match | `match_date` | `home_team_id`, `away_team_id` |
| `fact_team_match_form` | one team in one match | `match_date` | `team_id` |
| `fact_match_snapshot` | **one upcoming match per pipeline run date** | `snapshot_date` | `match_id` |
| `dim_team`, `dim_venue`, `dim_date` | one team / venue / calendar day | — | — |

The snapshot table is what turns the platform from "current state" into
"what was known when", and it is the reason the weather forecast can be joined
without contaminating history.
