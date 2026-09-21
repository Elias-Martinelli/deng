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

## Staging tables

| Table | Grain |
|---|---|
| `staging.matches` | one row per match |
| `staging.teams` | one row per team in the current season |
| `staging.standings` | **one row per team per season per ingestion date** — a point-in-time snapshot, because the table changes after every matchday |

`staging.standings` is the one staging table whose grain includes the ingestion
date. That is intentional: it turns the league table into a time series and is
the seed for the match-snapshot idea in the final architecture.

## Operational tables

| Table | Grain |
|---|---|
| `raw.football_data` | one row per (source, endpoint, request parameters, ingestion date) — one API answer on one day |
| `meta.pipeline_runs` | one row per pipeline execution |
| `meta.dq_results` | one row per data-quality check per run |

## Dimensional view

`fact_match` and `fact_team_match_form` are the facts; `dim_team` is the shared
dimension. `dim_date` and `dim_venue` are planned for the cloud model, where a
date dimension earns its place through partition pruning. Locally they would
only add joins.

```
            dim_team
           /        \
fact_match            fact_team_match_form
      |                        |
      +------ match_id --------+
```

## What is not modelled, and why

* **No group dimension.** Since the 2024/25 format change `group` is null in
  every row (evidence §5). A textbook design would have produced a table that
  is empty for every current-season match.
* **No odds.** The field exists but carries a marketing message, not data.
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
