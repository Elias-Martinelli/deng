# ADR-005 – Bookmaker odds: The Odds API, fetched by the pipeline under a credit budget

Status: **ACCEPTED** (2026-09-22)

## Context

The viewer should put our model forecast next to what the betting market
says: the 1X2 odds (home / draw / away, regular time including stoppage time)
of real, named bookmakers, for a chosen upcoming match, with a history of how
both moved towards kick-off. football-data.org's `odds` field is a marketing
stub (evidence §4), so a second source is needed.

Two constraints shape the decision. Odds change by the minute before a match,
so a daily batch is too coarse near kick-off. And every free odds source is
metered: fetching every 15 minutes around the clock costs ~2 900 requests a
month against a free budget of a few hundred.

## Decision

* **Source: The Odds API v4** (`api.the-odds-api.com`), free "Starter" plan with
  500 credits a month. One request answers with every upcoming Champions
  League event and every bookmaker of a region (`regions=eu`, ~25 bookmakers,
  each with key, name and its own `last_update`). One region × one market
  (`h2h`) = one credit per fetch.
* **Only the pipeline calls it.** A new job, `odds_refresh`, runs every
  `ODDS_REFRESH_MINUTES` (default 15) and decides on each tick whether to spend
  a credit: once a day always; at the interval only while a watched match is
  inside `ODDS_WATCH_HOURS_BEFORE_KICKOFF` (default 48 h); never below
  `ODDS_QUOTA_RESERVE` credits (default 50), where fetching pauses and the
  last state stays visible with its age. The app reads tables; a reload can
  never trigger a request.
* **Every fetch is stored**, and the curated layer derives one row per odds
  change per bookmaker and market, with the bookmaker's own timestamp and the
  interval in which the pipeline observed it.
* **Events are resolved to fixtures by kick-off time plus name similarity**
  against our team names and a small alias file; an unresolved event stays
  `UNMATCHED` and is reported by a WARNING check, never guessed.

## Alternatives considered

| Option | Why not |
|---|---|
| football-data.org odds package | paid add-on; the free tier returns a stub message |
| API-Football odds endpoint | 100 requests/day on the free plan, one request *per fixture and bookmaker* - a matchday of 18 fixtures would exhaust it before the first refresh |
| Scraping a bookmaker or an odds-comparison site | terms of service, brittle HTML, no timestamps we can trust |
| Fetching from the Streamlit app on demand | the rate limit would be shared with every visitor, and there would be no history - the opposite of what the pipeline is for |
| Fixed 15-minute polling around the clock | ~2 900 credits/month: six times the free budget; the watch-window rule keeps a matchday at ~200 credits |

## Advantages

* One request per fetch for the whole competition; bookmakers are named, and
  each quote carries the bookmaker's own timestamp.
* The budget is enforced in one place (`deng.sources.the_odds_api.plan_fetch`), is a
  pure function, and is unit-tested.
* Free plan; e-mail registration only; the key never enters the raw zone (the
  stored URL and parameters are rebuilt without it, and a verification query
  proves it).

## Disadvantages

* 500 credits a month means about two watched matchdays at 15-minute
  resolution. `ODDS_WATCH_MATCH_IDS` narrows the watch to chosen matches;
  `ODDS_REFRESH_MINUTES` trades resolution for coverage.
* Bookmakers spell club names their own way; the alias file needs a line when
  a new club appears (the WARNING check names it).
* The fair probabilities remove the margin proportionally, the simplest
  method. Bookmakers shade favourites and long shots differently
  (favourite-longshot bias), so the "fair" figure is an approximation - stated
  in the app as a model deviation, never as an edge.
* No sample was recorded from the live API: registering is a personal step,
  so the committed samples follow the documented schema with fictional prices
  (`data/sample/the-odds-api/README.md`). The first real fetch is evidence
  still to be produced.

## Consequences

* New tables: `raw.odds_api`, `staging.bookmaker_odds`,
  `staging.odds_event_match`, `curated.fact_bookmaker_odds`, and the model's
  `curated.fact_match_prediction`; views `bookmaker_odds_latest`,
  `match_prediction_latest`, `odds_comparison_latest`
  ([data model](../data-model.md)).
* A second Dagster job and schedule next to the daily one; the two never share
  a partition definition (odds are not daily data).
* Six new data-quality checks; the odds ones pass on an empty odds zone, so a
  reviewer without a key sees no failure from them.
* The Streamlit app gets its first configurable input beyond the fixture
  picker (bookmaker selection) and its first chart.
