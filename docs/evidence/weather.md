# Evidence: weather, venues and crests (21 September 2026)

## 1. Open-Meteo, measured

Request for RC Lens (`data/sample/open-meteo/forecast_team546_2026-09-21.json`,
a real answer):

| Finding | Consequence |
|---|---|
| `timezone=GMT` returns hourly `time` in UTC, columnar arrays aligned by position | kick-off hour = `date_trunc('hour', utc_kickoff, 'UTC')`, no time-zone arithmetic |
| 16 days × 24 hours = 384 values per variable | `HORIZON_DAYS = 16` (today + 15) |
| `start_date=2026-10-13` → **HTTP 400** `"out of allowed range from 2026-06-20 to 2026-10-06"` | never request beyond the horizon; such matches are `NOT_YET_AVAILABLE`; 400 is a permanent error (no retry) |
| past dates back to ~3 months are served | a backfill would get analysis data, not a forecast known before the match → weather is fetched for *today's* partition only |
| coordinates snap to the model grid (50.43282 → 50.44) | metre precision of stadium coordinates is irrelevant; city-level errors are not |

Matchday 2 is on 13/14 October, 22 days after this run. **The first run that
can fetch a real forecast for a Champions League match is 28 September.**
Until then every upcoming match is honestly `NOT_YET_AVAILABLE`.

## 2. Venues: why the API's venue fields could not be geocoded blindly

`make venues` searches OpenStreetMap (Nominatim) for each club. The first,
naive run with the API's venue names returned **four wrong stadiums**:

| Club | API venue | Naive result | Why wrong |
|---|---|---|---|
| Napoli | Stadio San Paolo | Stadio Silvio Piola, **Novara** | renamed 2020 |
| Barcelona | Camp Nou | village pitch in **Palau-saverdera** (Girona), ~130 km away | ambiguous name |
| Roma | Stadio Olimpico | Stadio Olimpico, **Turin** | ambiguous name |
| Galatasaray | Türk Telekom Arena | (no hit) → "Ali Sami Yen": site of the **demolished** old ground | outdated names |

Also not found under the API's name: Atlético (Wanda Metropolitano), Fenerbahçe,
AEK (plays at OPAP Arena since 2022), Viking (former sponsor name). Several API
*addresses* are training grounds (Bayern, Roma, Napoli, LASK).

Result after justified search overrides (each with its reason in
`scripts/build_venues.py`) and a plausibility check (a place name from the API
address must appear in OSM's address):

```text
36 clubs: 34 RESOLVED (29 plausibility OK, 5 flagged and checked by hand), 2 NOT_AVAILABLE
```

`NOT_AVAILABLE`: Shakhtar (home matches outside Ukraine since 2022, venue for
2026/27 unknown) and Sabah (no venue in the API). Their 8 home matches get
`VENUE_UNKNOWN` - no forecast rather than one for a guessed city.

Rome's stadium object is not returned by Nominatim's search; the row uses the
OSM node "Stadio Olimpico" at the adjacent junction (~0.6 km) - irrelevant at
1-11 km model resolution, and better than typed-in coordinates without a source.

## 3. Pipeline run with weather

Local, `make run-samples`, and live in Docker (`make dagster-backfill
FROM=2026-09-21 TO=2026-09-21`, real football-data.org answer):

```text
weather 0/0 venue forecast(s) stored         ← no match inside 16 days
  NOT_CAPTURED         18 matches           ← matchday 1, played 8-10 Sep
  NOT_YET_AVAILABLE   118 matches
  VENUE_UNKNOWN         8 matches           ← Shakhtar and Sabah home games
data quality: 17/18 checks passed           ← the known form-window WARNING
```

A run for a past date: `weather skipped: logical date 2026-09-20 is not today
(2026-09-21); a forecast fetched now would not be what was known then`, and the
curated weather state is not rolled back (`as_of_date` guard).

## 4. The AVAILABLE path, tested

Live data cannot show it before 28 September, so
`tests/test_weather_integration.py` runs the pipeline for logical date
1 October against a fake session whose answers have exactly the real payload's
shape. Proven there:

* every one of the 144 matches gets exactly one status; matchday 2 at resolved
  venues is `AVAILABLE`;
* the value is the one for the **kick-off hour in UTC** (the fake temperature
  encodes the hour);
* **one request per venue**, not per match;
* **leakage guard:** when every forecast is marked as fetched after the matches,
  none is used - the matches become `MISSING`, which a WARNING check reports;
* a rerun on the same day adds no raw rows; HTTP 400 is a non-retryable error;
  a past logical date makes no request.

Data-quality checks added: `every_match_has_a_weather_row`,
`weather_fetched_before_kickoff` (recomputes the leakage guard independently),
`weather_values_plausible` (all CRITICAL), `no_forecast_missing_inside_horizon`,
`every_team_has_a_venue_row` (WARNING).

## 5. Crests

`python -m deng.pipeline crests`: first run `36 fetched, 0 failed` (all PNG,
~18 KB each), second run `0 fetched` - no request at all. Stored in
`raw.team_crests`, read by the viewer through `curated.team_crest`, embedded as
data URIs: the page still loads nothing from a third-party server.

## 6. Viewer

| Desktop | iPhone 15 | Pixel 7 |
|---|---|---|
| ![desktop](streamlit-app.png) | ![iPhone](streamlit-iphone.png) | ![Android](streamlit-android.png) |

Rendered from the Docker app container. No horizontal overflow at 1280 / 393 /
412 px. Weather shows its state and the date from which a forecast will exist;
the footer carries the attributions Open-Meteo (CC BY 4.0) and OpenStreetMap
(ODbL) require.
