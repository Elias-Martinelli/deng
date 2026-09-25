# Reading this code in ten minutes

This page exists for one purpose: so that a person can open the repository,
follow **one match** from the API to the row a model would read, and explain
every stop along the way. Nine stops, in the order you should open the files.

If you only remember one sentence, remember this one:

> **`sources/` asks, `sql/` builds — and nothing in `sources/` may read what
> `sql/` built.**

That is the whole design. Everything below is that sentence in detail.

---

## Stop 1 — The entry point: `src/deng/pipeline.py`

Seven commands, and that is the entire surface of the pipeline:

```bash
init  ingest  transform  dq  run  backfill  verify
```

`run` is just the other three in order: **ingest → transform → dq**. Nothing
clever happens in this file; it parses arguments, opens a database connection
and calls the next stop. Every `make` target is a one-line wrapper around one
of these commands.

*What to say:* "The CLI is deliberately thin. If you can read seven commands,
you know everything the pipeline can do."

---

## Stop 2 — The ingestion: `src/deng/ingestion/runner.py`

About 150 lines, and the most important list in the repository:

```python
STEPS: tuple[Step, ...] = (
    Step("football", "ingest_football_raw", _football),
    Step("openstreetmap", "ingest_osm_venues", _openstreetmap),
    Step("crests", "fetch_crests", _crests, best_effort=True),
    Step("weather", "ingest_weather", _weather),
    Step("odds", "ingest_odds", _odds, best_effort=True),
)
```

Two things are worth pointing at:

* **The order is a dependency, not a preference.** Football comes first because
  it is the only step that needs nothing: it tells the later steps which matches
  and clubs exist. OpenStreetMap comes before the weather because the weather
  needs coordinates.
* **`best_effort=True` is the failure policy in one word.** Crests and odds are
  extras: if they fail, the failure is recorded and reported, but the run still
  counts. Football, stadiums and weather are not extras — if football fails,
  the run fails, because everything else rests on it.

*What to say:* "This file is the answer to 'what does a daily run do'. Five
steps, in an order the data forces, with two of them allowed to fail."

---

## Stop 3 — One source: `src/deng/sources/football_data.py`

Every source file answers the same two questions, and this one shows the shape:

| Question | Where it is answered |
|---|---|
| **What** should we fetch, and why? | `DAILY_ENDPOINTS` — a list of four endpoints, each carrying its own `rationale` and `load_strategy` in the code |
| **How** do we ask? | `FootballDataClient` — one class, HTTP, retries, pacing |

They are kept apart on purpose: adding an endpoint is one more entry in a list,
not a change to networking code. And the justification lives next to the thing
it justifies, so it cannot quietly drift away from the implementation.

The load strategy is where the interesting question hides:

* the four daily endpoints are **FULL** — one request returns the whole
  competition (~210 KB), it self-heals after a missed day, and asking "what
  changed?" would cost an extra request *and* still miss the matches the API
  **adds** mid-season (the knockout draw in December);
* a **finished season is fetched ONCE** (`season_endpoints`), because it can
  never change again. That is the incremental case, and it is exactly where
  incremental is right.

*What to say:* "We did not pick one loading strategy for everything. We picked
per source, and the reason is written in the code next to the choice."

---

## Stop 4 — Where every answer lands: `src/deng/database/raw_loader.py`

One row per **(source, endpoint, parameters, day)**. That key is the whole
idempotency story: running the same day twice updates that row instead of adding
a copy, so a rerun is safe and a backfill is boring.

Two details worth knowing when asked:

* The loader compares the new payload's hash with the stored one and reports
  **UNCHANGED / UPDATED / INSERTED**. So "did anything actually change today?"
  is a value in the run log, not a guess.
* **The loader never commits.** The caller owns the transaction, so a run's
  payloads land together or not at all.

*What to say:* "The raw zone is our only archive. The sources overwrite
yesterday; we do not."

---

## Stop 5 — How a source knows what to ask for: `src/deng/ingestion/raw_reads.py`

This is the file that makes the headline sentence true. The later steps need to
know things — which matches are coming up, which clubs exist, where the stadiums
are. Before the restructure they read the finished tables for that, which meant
a transformation had to run *inside* the ingestion.

Now they ask the **raw zone** instead, through three read-only views
(`sql/schema/009_raw_planning_views.sql`, `010_raw_osm_venues.sql`):

| View | Answers | Used by |
|---|---|---|
| `raw.match_calendar` | which matches exist, when they kick off, are they finished | weather, odds |
| `raw.team_catalog` | which clubs exist | stadiums, crests |
| `raw.venue_coordinates` | where a club's stadium is | weather |

All three unpack the JSON answers the same run stored minutes earlier.

*What to say:* "A view over the raw zone is still raw data — it is the stored
answer, read differently. That is what lets us ingest everything first."

---

## Stop 6 — The three interesting source files

Open them only if asked; each is one page and one idea:

* **`openstreetmap.py`** — asks once per club, never daily, paced to one request
  per second. Searching stadiums blindly once put Napoli in Novara, so every hit
  was reviewed by a human **once** and the verdict is stored *next to the
  untouched answer*, never instead of it.
* **`open_meteo.py`** — one request per stadium that has a match inside the
  16-day forecast horizon. A past date would return what the weather *turned
  out to be*, not what was predicted, so a backfill fetches no weather at all.
  Saying that out loud is better than pretending we have history we do not have.
* **`the_odds_api.py`** — 500 credits a month, so the file decides whether to
  spend one: once a day always, more often only while a watched match is close
  to kick-off, never below a reserve.

---

## Stop 7 — The transformation: `src/deng/transformation/runner.py` + `sql/transform/`

Thirteen SQL files, run in the order their numbers give. The hundreds digit
groups the chain: 1xx/2xx football, 3xx weather, 4xx odds - and inside a group
staging comes before the curated files that read it. The Python here only
executes them in order and counts rows; the logic is SQL, because it is set
logic.

They run in **three transactions** — football (1–7), weather (8–11), odds
(12–13) — because the later files read what the earlier ones wrote. Each
transaction lands completely or not at all, so a table is never half-built.

One Python step sits between the odds files: `transformation/odds_matching.py`
resolves a bookmaker's event to our fixture by kick-off time and name
similarity. It is Python because it is string matching, not set logic — and it
lives in `transformation/`, not in `sources/`, because it reads curated tables.
That file is the proof the rule is real: the code was *moved*, not rewritten.

---

## Stop 8 — Where it arrives: `sql/schema/011_model_features.sql`

One row per match: the label plus every feature that was known **before**
kick-off. This is the answer to "what is your data product".

It is a **view**, not a table, and that is a deliberate, defensible limitation:
it adds no logic, it only joins what the curated tables already hold, so there
is nothing to keep in sync. Its point-in-time correctness is inherited, not
claimed — the form counts only matches finished before this kick-off (230), the
weather is the newest forecast fetched before kick-off (330), the odds the
newest quote before kick-off (420).

`outcome` is NULL until a match has been played. That single column separates
the training set from the upcoming fixtures.

---

## Stop 9 — What keeps it honest: `src/deng/quality/checks.py` and `tests/test_layering.py`

* **24 data-quality checks** after every run, their results written into the
  database. 16 are CRITICAL and fail the run, 8 are WARNINGs and stay visible.
  Two of the CRITICAL ones are the leakage guards, and both are written to
  distrust our own SQL: `form_uses_no_future_matches` counts independently how
  many matches a team had actually finished before that kick-off and fails if
  the form row used more, and `weather_fetched_before_kickoff` asks the same
  question of the forecasts.
* **`tests/test_layering.py`** greps the ingestion code for `staging.` and
  `curated.` and fails if either appears. Before the restructure the same
  search found 14 lines in 3 files
  ([evidence](evidence/restructure.md)).

*What to say:* "The rule at the top of this page is not a promise in a README.
It is a failing test if we break it."

---

## If you are asked about X, open Y

| Question | File |
|---|---|
| "What does a run do?" | `src/deng/ingestion/runner.py` |
| "Full or incremental, and why?" | `src/deng/sources/football_data.py` (the comment above `DAILY_ENDPOINTS`) |
| "What if you run it twice?" | `src/deng/database/raw_loader.py` |
| "What if a source is down?" | `src/deng/sources/http.py` + `best_effort` in `runner.py` |
| "How do you avoid data leakage?" | `sql/transform/230_fact_team_match_form.sql`, then check 'form window' in `quality/checks.py` |
| "What is the data product?" | `sql/schema/011_model_features.sql` |
| "Where is the history?" | `sql/schema/003_raw_tables.sql` — the key with `ingestion_date` |
| "Prove the architecture rule" | `tests/test_layering.py` |

Longer versions of the same reasoning: the [README](../README.md) for the
design, [`docs/evidence/restructure.md`](evidence/restructure.md) for the
measurements, and [`docs/pitch/speaker-notes.md`](pitch/speaker-notes.md) for
the questions and short answers in German.
