# ADR-001 – Football and weather data sources

Status: **PROPOSED** (2026-09-18). Becomes ACCEPTED after the first real
exploration run (`make explore`) confirms the schema and the season restriction.

## Context

The use case needs, for the UEFA Champions League: the full fixture list of the
current season (future matches included), results, standings, team metadata and
– to enrich upcoming matches – a weather forecast for the venue. The pipeline
runs as a daily batch and must be reproducible by peer teams with a free
account. Detailed comparison: [`docs/data-sources.md`](../data-sources.md).

## Decision

* **Football data: football-data.org v4, free tier.** Endpoints
  `competitions/CL/{matches,standings,teams}`, `teams/{id}/matches`,
  `matches/{id}/head2head`.
* **Weather data: Open-Meteo** forecast API (16-day horizon) and archive API
  (post-match actuals), no API key.
* **Venue coordinates: a small versioned reference file** (`venues.csv`)
  maintained in the repository.

## Alternatives considered

| Alternative | Why not (for the core) |
|---|---|
| API-Football (api-sports.io) free plan | 100 requests/day is a hard daily budget; a batch that touches fixtures, standings and 36 teams would use it up in one run, leaving nothing for reruns or backfills. Documentation is vague about whether the current season is even included in the free plan. Kept as a possible *add-on* for injuries/line-ups. |
| TheSportsDB | free tier caps result sets (15 events per season call, team search restricted); data typed as strings; community-maintained quality. |
| Scraping UEFA.com / FBref | no licence, brittle, not "a documented source" in the sense of the rubric. |
| Kaggle CSV dumps of past CL seasons | static, no future fixtures, no update cadence – nothing to orchestrate. Could serve as *optional* historical backfill later. |
| OpenWeatherMap for weather | needs a credit card for the free tier; 8-day horizon; proprietary terms. |
| Run-time geocoding for venues | third external dependency on every run; the set of venues is small (36 + finals) and changes once a year. |

## Advantages

* Both providers are free, documented, key-based (or key-less) and used by many
  learning projects → peer teams can reproduce with minimal setup.
* Minute-based rate limit (10/min) instead of a daily budget → reruns and
  backfills are always possible, just slower.
* Full season schedule available upfront → the "future match" part of the use
  case works from day one.
* `X-Requests-Available-Minute` header allows precise client-side throttling.
* Open-Meteo returns forecast *and* archive from one provider under CC BY 4.0.

## Disadvantages

* **Current season only** on the free tier – no multi-season history for form or
  model training. Mitigation: raw payloads are kept from the first run; the
  `head2head` sub-resource still yields historical encounters; ClubElo is a
  possible cross-season strength signal (COULD).
* No line-ups, injuries, player or match statistics → those attribute groups are
  `NOT_AVAILABLE` in the snapshot table.
* No venue coordinates → manual reference file must be maintained when new clubs
  qualify (data-quality check alerts on missing venues).
* Scores are "delayed" on the free tier – irrelevant for a daily batch, but the
  Streamlit app must not be presented as live.

## Consequences

* Ingestion budget ≈ 60 calls/day → ~6 minutes. The client throttles on the
  rate-limit headers and retries on 429/5xx.
* Raw zone becomes the archive of record; a backfill for a past date can only
  replay what was stored on that date (the API does not serve past seasons).
* The data model must carry explicit availability states instead of NULL-only.
* If the free tier changes, the client abstraction allows swapping the provider
  behind the same extraction interface; the raw zone remains valid.

## Failure and scale considerations

* *API unreachable / 429:* exponential back-off, then the run fails visibly;
  yesterday's curated data stays intact because loads are transactional.
* *100× data:* still trivially within Open-Meteo limits; football data would
  require a paid tier (more competitions) but no architectural change – the raw
  zone is partitioned by source/endpoint/date and BigQuery scales linearly.
