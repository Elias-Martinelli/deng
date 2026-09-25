# Evidence: one file per source, one ingestion, then the transformation

Recorded on **25 September 2026**, against the repository at commits
`c0d38ca` (the restructure), `8b324c3` (past seasons) and `d4eb769` (the
dashboard). The numbers below were measured, not estimated; where something is
only argued rather than measured, section 7 says so.

The product is the data pipeline. A model that predicts the winner is what the
data is **for**, and is not part of this project.

## 1. The rule, and the 14 places that broke it

The sentence the whole restructure is about:

> Ingestion reads the APIs, the files under `data/` and the raw zone - never
> staging, never curated.

Why it matters, in one breath: if fetching the weather needs a *finished* table,
then a transformation has to run in the middle of the ingestion, and the data
product can no longer be rebuilt from the stored answers alone. "Ingest
everything first, transform afterwards" stops being true.

Before the restructure it was not true. Grepping the old ingestion package for
references to the later layers finds **14 lines in 3 files**:

```console
$ git grep -nE '\b(staging|curated)\.[a-z_]+' 6436c2d -- src/deng/ingestion
6436c2d:src/deng/ingestion/crests.py:56:              FROM curated.dim_team d
6436c2d:src/deng/ingestion/odds.py:256:                "SELECT utc_kickoff FROM curated.fact_match "
6436c2d:src/deng/ingestion/odds.py:261:            cursor.execute("SELECT utc_kickoff FROM curated.fact_match WHERE NOT is_finished")
6436c2d:src/deng/ingestion/odds.py:553:              FROM curated.fact_match m
6436c2d:src/deng/ingestion/odds.py:554:              JOIN curated.dim_team h ON h.team_id = m.home_team_id
6436c2d:src/deng/ingestion/odds.py:555:              JOIN curated.dim_team a ON a.team_id = m.away_team_id
6436c2d:src/deng/ingestion/odds.py:586:              FROM staging.bookmaker_odds s
6436c2d:src/deng/ingestion/odds.py:587:              LEFT JOIN staging.odds_event_match x ON x.event_id = s.event_id
6436c2d:src/deng/ingestion/odds.py:604:                INSERT INTO staging.odds_event_match AS x
6436c2d:src/deng/ingestion/weather.py:21:`staging.venues` at the start of every weather run.
6436c2d:src/deng/ingestion/weather.py:113:    """Upsert data/reference/venues.csv into staging.venues. Returns the row count."""
6436c2d:src/deng/ingestion/weather.py:130:            INSERT INTO staging.venues AS v
6436c2d:src/deng/ingestion/weather.py:173:              FROM curated.fact_match m
6436c2d:src/deng/ingestion/weather.py:174:              JOIN staging.venues v ON v.team_id = m.home_team_id AND v.status = 'RESOLVED'
```

Honest reading of those 14: **12 are SQL, 2 are docstring lines** describing
them (`weather.py:21` and `:113`). And they are not all the same mistake:

| Lines | What it was | What happened to it |
|---|---|---|
| 8 (`crests:56`, `odds:256/261`, `weather:21/113/130/173/174`) | ingestion genuinely reading or writing a transformed table | replaced by two views over the raw zone (below) |
| 6 (`odds:553-604`) | the event matcher, which really *is* a transformation | **moved**, not rewritten, to `src/deng/transformation/odds_matching.py` |

The two views that made the first group unnecessary are in
[`sql/schema/009_raw_planning_views.sql`](../../sql/schema/009_raw_planning_views.sql):
`raw.match_calendar` (one row per match) and `raw.team_catalog` (one row per
club). Both unpack the JSON answers the *same run* stored minutes earlier and
keep the newest one per object:

```sql
SELECT DISTINCT ON (match_id) ...
  FROM raw.football_data r
  CROSS JOIN LATERAL jsonb_array_elements(r.payload -> 'matches') AS m
 ORDER BY match_id, r.ingestion_date DESC, r.ingested_at DESC;
```

The queries the ingestion is allowed to ask are collected in one 96-line file,
[`src/deng/ingestion/raw_reads.py`](../../src/deng/ingestion/raw_reads.py) -
four functions, each one SELECT against one of those views.

### The test that measures it

The rule is not a comment in a README. It is
[`tests/test_layering.py`](../../tests/test_layering.py), and it is
deliberately dumb - a grep, so a reviewer can check it by eye:

```python
SRC = Path(__file__).resolve().parents[1] / "src" / "deng"
INGESTION_DIRS = [SRC / "sources", SRC / "ingestion"]

# Table references of the transformed layers, e.g. "curated.fact_match".
FORBIDDEN = re.compile(r"\b(staging|curated)\.[a-z_]+")


def test_ingestion_never_reads_staging_or_curated():
    hits = offending_lines()
    assert hits == [], "ingestion must read only the APIs, data/ and the raw zone:\n" + "\n".join(
        hits
    )
```

```console
$ python -m pytest tests/test_layering.py -q
.                                                                        [100%]
```

14 offending lines before, 0 now, and the next one fails the test instead of
being discovered during a presentation. It needs no database, so it runs in
every `make test`.

## 2. What moved where

`src/deng/sources/` now holds **one module per source**, and every one of them
answers the same two questions - what should I fetch, and how do I fetch one of
them (`src/deng/sources/__init__.py` states this as the package's contract).
Storing the answer, the run log and the order are not their business; that is
`deng.ingestion`.

Honest caveat about that shape: the two functions are not literally named
`plan` and `fetch` everywhere. `openstreetmap.py` has `plan` / `fetch`,
`open_meteo.py` has `plan_requests` / `fetch_forecast`, `the_odds_api.py` has
`plan_fetch` / `fetch_odds`, `football_data.py` expresses the plan as the
constant `DAILY_ENDPOINTS` plus `season_endpoints()`, and `club_crests.py` is
small enough that `fetch_crests` does both. The *shape* is uniform - the names
are not, and nothing enforces them.

| Before (`src/deng/ingestion/`) | Lines | After | Lines |
|---|---|---|---|
| `extract.py` + `football_data_client.py` | 229 + 169 | `sources/football_data.py` | 496 |
| `weather.py` | 315 | `sources/open_meteo.py` | 258 |
| `odds.py` | 633 | `sources/the_odds_api.py` | 445 |
| `crests.py` | 125 | `sources/club_crests.py` | 129 |
| *(`scripts/build_venues.py`, run by hand)* | 229 | `sources/openstreetmap.py` | 290 |
| - | - | `sources/http.py` (the two error classes) | 26 |
| - | - | `ingestion/runner.py` (**the** ingestion) | 152 |
| - | - | `ingestion/raw_reads.py` | 96 |
| *(inside `odds.py`)* | - | `transformation/odds_matching.py` | 211 |

The whole of step 1 is now 152 lines
([`src/deng/ingestion/runner.py`](../../src/deng/ingestion/runner.py)), and the
part a layperson has to read is a five-line table:

```python
STEPS: tuple[Step, ...] = (
    Step("football", "ingest_football_raw", _football),
    Step("openstreetmap", "ingest_osm_venues", _openstreetmap),
    Step("crests", "fetch_crests", _crests, best_effort=True),
    Step("weather", "ingest_weather", _weather),
    Step("odds", "ingest_odds", _odds, best_effort=True),
)
```

Football runs first because three of the other sources need to know which
matches and clubs exist - and they read that from the raw zone, from the answer
this very run just stored. `best_effort=True` on crests and odds means a
failure there is recorded but does not fail the run; football does fail it,
because everything else rests on it.

### Why the CLI shrank from ten commands to seven

Old (`git show 6436c2d:src/deng/pipeline.py`): `init, ingest, backfill,
transform, weather, crests, odds, dq, run, verify` - **10**.
New: `init, ingest, backfill, transform, dq, run, verify` - **7**.

The three that disappeared were not features, they were symptoms. `weather`,
`crests` and `odds` each existed as its own command because each one *had* to
run after `transform`, so the sequence was ingest, transform, ingest again,
transform again. Now they are sources inside `ingest`, reachable with
`ingest --only weather|crests|odds|football|openstreetmap`, and the picture is
three words: **ingest, transform, dq**.

Makefile target names did not change - `make venues` now runs
`ingest --only openstreetmap`, `make odds` runs `ingest --only odds`.

## 3. OpenStreetMap as a source

Before, stadium coordinates came from `data/reference/venues.csv`, produced by
`scripts/build_venues.py`, which a person ran by hand. Both files are
**deleted**. Coordinates are now ingested like everything else, into
[`raw.osm_venues`](../../sql/schema/010_raw_osm_venues.sql).

Stored per club: the Nominatim answer **unchanged** (`payload`), plus the usual
raw-zone columns - what we asked (`request_params`, `request_url`), when
(`ingestion_date`, `ingested_at`), under which run (`run_id`), and the payload
hash. Plus two columns no other source needs:

```sql
review_status  TEXT NOT NULL CHECK (review_status IN ('RESOLVED', 'NOT_AVAILABLE')),
review_note    TEXT,
```

**Why the verdict sits next to the payload.** A stadium search can confidently
return the wrong stadium - the first run put Napoli in Novara, Barcelona in a
village near Girona and Roma in Turin ([`weather.md`](weather.md) §2). So a
person checked the flagged rows once, and that judgement is data: it must
survive, be queryable and be visible beside the thing it judges. Keeping it in
a CSV meant the evidence and the verdict lived in different places, and the
verdict could not be traced to the answer it was about. The payload itself is
never edited - only the question changes (`QUERY_OVERRIDES` in
`sources/openstreetmap.py`, each override carrying the reason it exists), and
the verdict is recorded next to the answer.

Cadence: `plan()` returns only clubs with no stored answer, so on a normal day
it returns nothing. Stadiums do not move. Nominatim's policy of one request per
second is respected with `PAUSE_SECONDS = 1.1`.

**The offline path.** 36 files are committed under
`data/sample/openstreetmap/`, one per club, named `venue_<team_id>.json`. 34
carry a real Nominatim answer; the two for Shakhtar (1887) and Sabah (10233) are
`{}`, 2 bytes each, because those clubs have no usable venue at all - and
`_resolve()` returns `NOT_AVAILABLE` for them before it would even look at a
sample. With `--from-samples`, `read_sample()` returns the committed answer and
no request is made, so `make run-samples` works with no network and no API key.
`make venues` is now just `python -m deng.pipeline ingest --only openstreetmap`.

The transformation side is
[`sql/transform/305_staging_venues.sql`](../../sql/transform/305_staging_venues.sql),
which builds `staging.venues` from `raw.venue_coordinates` exactly as 110
builds `staging.matches` from the football payload. That is the file that used
to be an `INSERT INTO staging.venues` inside the weather *ingestion*.

## 4. Past seasons as training data

`FOOTBALL_DATA_SEASONS` in `src/deng/config.py` - comma-separated start years,
empty means current season only. Each season costs exactly **one matches
request and one teams request**, once.

Measured:

| Season | Matches |
|---|---|
| 2023 | 125 |
| 2024 | 189 |
| current league phase | 144 |

With 2023 and 2024 ingested, the curated layer holds **458 matches, 60 clubs,
332 of them with a label, 664 form rows**, and all **24** data-quality checks
pass. The API lists **47** seasons, so the ceiling is far higher; how far back
the free tier really serves is untested (backlog 1.8).

### No new table was needed

The raw zone's key is

```sql
CONSTRAINT football_data_unique_per_day
    UNIQUE (source, endpoint, request_params, ingestion_date)
```

`request_params` is part of it. `?season=2023` is therefore a *different row*
from today's answer, in the same table, without a schema change. Past seasons
were free architecturally - they are one more question to the same endpoint.

### The DISTINCT ON that this forced

That freedom has a price one step later. On one ingestion date there are now
several matches answers and several teams answers, and they overlap: a club
plays in 2023 and 2024, a match can appear in both the sample replay and the
real answer. The staging INSERT is an upsert on the primary key, and PostgreSQL
refuses to touch the same key twice in one statement:

```text
ERROR:  ON CONFLICT DO UPDATE command cannot affect row a second time
```

So [`110_staging_matches.sql`](../../sql/transform/110_staging_matches.sql) and
[`111_staging_teams.sql`](../../sql/transform/111_staging_teams.sql) each
collapse the day's answers to one row per object before inserting:

```sql
WITH unpacked AS (
    SELECT DISTINCT ON ((m ->> 'id')::bigint) m
      FROM raw.football_data r
      CROSS JOIN LATERAL jsonb_array_elements(r.payload -> 'matches') AS m
     WHERE r.endpoint LIKE '%%/matches'
       AND r.ingestion_date = %(logical_date)s
     ORDER BY (m ->> 'id')::bigint, r.ingested_at DESC
)
```

Read aloud: *one row per match, the most recently stored one*. The `DISTINCT ON`
and the `ORDER BY` that decides which one wins are two lines; 111 has the same
two for `team_id`. Four lines of SQL in total, and they are the reason the
season setting is a setting rather than a project.

(`%%` in that snippet is not a typo. psycopg reads a single `%` as the start of
a parameter, so SQL's `LIKE` wildcard is written doubled in these files and
stands for one. `%(logical_date)s` is a real parameter - the ingestion date being
transformed, passed explicitly so a rerun for a past date produces that date's
result instead of today's.)

## 5. `curated.model_features`, and what the dashboard shows

[`sql/schema/011_model_features.sql`](../../sql/schema/011_model_features.sql)
adds one view: **one row per match, the label plus the features that were known
before kick-off.** It is what a model would read, and it is the last file in a
pipeline whose whole purpose is to produce it.

A view, not a table - it only joins curated tables that already exist, so there
is nothing to keep in sync. The label is `outcome`, which is NULL until the
match has been played; that single column is what separates the training set
from the upcoming fixtures.

Point-in-time correctness is inherited, not re-implemented: form counts only
matches finished before this kick-off (230), the weather is the newest forecast
fetched before kick-off (330), the odds are the newest quote seen before
kick-off (420), the baseline forecast uses the form table only (240).

The Streamlit app (`app/`) is now an **analysis dashboard for this view**
([`app/dataset_view.py`](../../app/dataset_view.py)), reading curated tables
only and making no API call. Three panels, then one match in detail underneath:

1. **The dataset** - matches, how many carry a label, seasons, and a per-season
   table with its date range. The caption names the lever honestly: a league
   phase is 144 matches, a finished season up to 189, and which seasons are
   fetched is one setting.
2. **Feature coverage** - for each of seven features, for how many matches it
   is present, and **the reason when it is not**: "kick-off beyond the 16-day
   forecast horizon", "first match of the season for that club", "no quote
   stored yet". Plus the breakdown of weather states. A gap with a recorded
   reason is a fact; a silently missing value is a bug.
3. **Leakage guarantees** - three rules, each **recomputed in the panel's own
   SQL** rather than quoted from the pipeline: form uses only matches finished
   before kick-off (counted independently with a correlated subquery), the
   weather was fetched before kick-off, every match has exactly two form rows.
   Each shows `ok` or a violation count.

The feature table is downloadable as CSV - what a data scientist would actually
take away.

## 6. Totals after the three commits

"Before" is `6436c2d`, the commit these three build on; "after" is `d4eb769`.

| | Before | After |
|---|---|---|
| CLI subcommands | 10 | 7 |
| Sources ingested by the pipeline | 4 | 5 (OpenStreetMap joined) |
| `sql/schema/` files | 8 | 11 |
| `sql/transform/` files | 12 | 13 |
| Data-quality checks | 24 | 24 |
| Ingestion lines touching staging/curated | 14 | 0 |
| Tests collected | - | 137 |

```console
$ python -m pytest --collect-only -q | tail -1
137 tests collected in 0.87s
```

**Correction to a claim made while this work was planned:** the data-quality
checks were described as "24, was 18". 24 is right, the "was 18" is not this
restructure's doing. Counted per commit:

```console
$ for c in 4aa0fdc 6436c2d c0d38ca 8b324c3 d4eb769; do
>   echo "$c $(git show ${c}:src/deng/quality/checks.py | grep -c 'name="')"; done
4aa0fdc 18
6436c2d 24
c0d38ca 24
8b324c3 24
d4eb769 24
```

The six new checks arrived with the odds source (`6436c2d`), one commit
*earlier*. The restructure, the seasons and the dashboard added none - and that
is the point worth making out loud: a refactor that moves 14 rule violations to
zero while the number of checks stays flat and all 24 keep passing is a refactor
that changed the shape and not the data. The same reading corrects the file
count: `sql/transform/` went from **12 to 13** (one new file, 305), not from 11.

## 7. What this does **not** prove

* **Which numbers were re-measured while writing this.** Re-run today: the
  layering grep (14 before, 0 now), the layering test, the test count (137), the
  file counts, the CLI command lists, the module line counts, the sample-file
  count and the per-commit data-quality count. **Not** re-run today: the row
  counts of the curated layer (458 / 60 / 332 / 664) and "24/24 checks pass" -
  those need a running PostgreSQL, and are taken from the run recorded when the
  seasons were ingested (`8b324c3`; the same figures in
  `docs/project-backlog.md` 1.9, `docs/use-case.md` and
  `docs/rubric-checklist.md`). They should be re-measured before the defence,
  because they change the moment another season is added to the setting.
* **No real-device or cloud run.** Everything here was measured against a local
  PostgreSQL 16 in Docker Compose. The cloud path in
  `docs/architecture-target.svg` is a target, not a run: no BigQuery, no GCS,
  no scheduled execution anywhere but this machine. The dashboard screenshots
  in [`weather.md`](weather.md) are from an earlier version of the app; the
  three new panels have not been photographed on a phone.
* **The snapshot table is still missing.** `curated.model_features` gives one
  row per match. The table a model is really trained on - `fact_match_snapshot`,
  one row per match **per day**, which is what makes "what was known N days
  before kick-off" queryable - does not exist (backlog 6.5, FINAL milestone).
  The view is honest about this in its own header comment.
* **The tests share the local database.** `tests/conftest.py` connects to the
  same PostgreSQL the pipeline uses and `TRUNCATE`s 18 tables before each test
  that needs one. Two consequences: the database tests cannot run in parallel,
  and running `make test` after `make run-samples` **destroys the sample data**
  you were looking at. They skip cleanly when no PostgreSQL is reachable, which
  keeps `make test` green without Docker - but that also means a green
  `make test` does not by itself prove the database tests ran.
* **The 14 violations were counted by grep, on line references**, which is the
  same instrument the test uses. It measures what the code *says*, not what it
  does at runtime: a table name assembled from string pieces would slip past
  both. Accepted deliberately - a rule a reader can verify in three seconds is
  worth more here than a clever import graph.
* **How far back the free tier serves seasons is untested.** 2023 and 2024
  work; 47 are listed; nothing older than 2023 has been requested.
* **The diagrams are new and unreviewed.** Three replaced the single
  `docs/architecture.svg`, which predated the odds source, the OpenStreetMap
  source and this restructure and has been deleted:
  `docs/architecture-overview.svg` (the three stages - ingest, transform, data
  product), `docs/architecture-detail.svg` (sources, ingestion, the warehouse
  with its raw / staging / curated zones, transformation, data product, platform
  row) and `docs/architecture-target.svg` (the local path today versus the cloud
  path for the final milestone, plus the platform row). They were drawn by hand
  from the code as it is now, and nobody has yet checked them box-by-box against
  it - which is exactly the kind of drift the old file is an example of.
