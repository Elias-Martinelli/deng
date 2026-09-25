# ADR-001 – Football and weather data sources

Status: **ACCEPTED** (2026-09-20). Confirmed by a real exploration run; the
findings, including two corrections to earlier assumptions, are recorded in
[`docs/evidence/api-exploration.md`](../evidence/api-exploration.md).

**Two parts of this decision were changed later** (the rest still holds):

* *Venue coordinates.* The reference file `venues.csv` is gone. OpenStreetMap
  (Nominatim) is a source of the pipeline like the others: every answer is
  stored unchanged in `raw.osm_venues` with our review verdict next to it, and
  `sql/transform/305_staging_venues.sql` builds `staging.venues` from it. The
  cadence is the same as planned - once per club, not per run.
* *Daily budget.* [ADR-004](ADR-004-champions-league-scope.md) dropped the
  per-club `/teams/{id}/matches` calls, so a run asks **4 football endpoints**
  instead of ~60, plus at most ~20 weather requests and at most one odds
  credit.

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
  maintained in the repository. *(Superseded: OpenStreetMap is a pipeline
  source now - see the note under Status.)*

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
* **Historical seasons are accessible** despite the documentation suggesting
  otherwise: `?season=2023` returns the complete 2023/24 season (125 matches,
  HTTP 200), and 47 seasons back to 1980 are listed. Multi-season form,
  head-to-head and a realistic ML training set therefore become possible.
* Referees are included in match payloads and are usable as a match attribute.
* `X-Requests-Available-Minute` header allows precise client-side throttling.
* Open-Meteo returns forecast *and* archive from one provider under CC BY 4.0.

## Disadvantages

* No line-ups, injuries, player or match statistics → those attribute groups are
  `NOT_AVAILABLE` in the snapshot table.
* **Asymmetric domestic coverage:** `/teams/{id}/matches` is silently restricted
  to competitions in our tier. 25 of the 36 league-phase clubs have their
  domestic league covered, 11 do not, so their form rests on Champions League
  matches alone. Every form feature must carry the number of matches behind it.
* The API's own aggregates (`resultSet.wins/draws/losses`, `standings.form`) are
  inconsistent or empty and must not be used – see evidence §8.
* `odds` is a stub object containing a marketing message, not data.
* No venue coordinates → they are fetched from OpenStreetMap once per club, so a
  club that qualifies later needs one more lookup (a data-quality check alerts
  on missing venues).
* Scores are "delayed" on the free tier – irrelevant for a daily batch, but the
  Streamlit app must not be presented as live.

## Consequences

* Ingestion budget: 4 football calls/day since ADR-004 (≈ 60 while the per-club
  endpoint was still planned). The client throttles on the rate-limit headers
  and retries on 429/5xx.
* Raw zone remains the archive of record for *point-in-time* questions (what was
  known on a given day); past **seasons** can additionally be re-fetched from the
  API, which makes a seasonal backfill genuinely useful rather than a
  demonstration.
* The data model must carry explicit availability states instead of NULL-only.
* If the free tier changes, the client abstraction allows swapping the provider
  behind the same extraction interface; the raw zone remains valid.

## Failure and scale considerations

* *API unreachable / 429:* exponential back-off, then the run fails visibly;
  yesterday's curated data stays intact because loads are transactional.
* *100× data:* still trivially within Open-Meteo limits; football data would
  require a paid tier (more competitions) but no architectural change – the raw
  zone is partitioned by source/endpoint/date and BigQuery scales linearly. The
  binding constraint stays the 10 requests/minute limit, i.e. wall-clock time per
  run, not storage.
