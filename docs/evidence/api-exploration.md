# Evidence: football-data.org API exploration

Run on **20 September 2026** with `make explore` (script:
[`scripts/explore_football_api.py`](../../scripts/explore_football_api.py)) plus three
targeted probes. Raw payloads are committed under
[`data/sample/football-data/`](../../data/sample/football-data/) and serve as test
fixtures. Account tier: free (the API reports `"permission": "TIER_ONE"` in the
`filters` block of several responses).

This document records what the API **actually** returns, as opposed to what its
documentation suggests. Two documented assumptions turned out to be wrong; both
are corrected here and in [`docs/data-sources.md`](../data-sources.md).

## 1. Endpoints called and volumes

| Endpoint | Rows | File | Size |
|---|---|---|---|
| `GET /competitions/CL` | 47 seasons | `competition.json` | 9 KB |
| `GET /competitions/CL/teams` | 36 teams | `teams.json` | 49 KB |
| `GET /competitions/CL/standings` | 1 table, 36 rows | `standings.json` | 18 KB |
| `GET /competitions/CL/matches` | 144 matches | `matches_all.json` | 212 KB |
| `GET /competitions/CL/matches?status=SCHEDULED` | 126 matches | `matches_scheduled.json` | 183 KB |
| `GET /competitions/CL/matches?status=FINISHED` | 18 matches | `matches_finished.json` | 29 KB |
| `GET /teams/4/matches?status=FINISHED&limit=20` | 5 matches | `team_matches.json` | 8 KB |
| `GET /matches/575341/head2head?limit=10` | 0 matches | `head2head.json` | <1 KB |

Rate-limit headers behaved exactly as documented and counted down per request
(`9 requests left, reset in 60s` → `5 requests left, reset in 27s`), which
confirms that throttling on `X-Requests-Available-Minute` is viable.

## 2. Correction 1 — historical seasons ARE accessible

Assumed (from the pricing page and third-party write-ups): free tier serves the
current season only.

Probe:

```console
$ curl -s -w "\nHTTP %{http_code}\n" -H "X-Auth-Token: $KEY" \
    "https://api.football-data.org/v4/competitions/CL/matches?season=2023"
{"filters":{"season":2023},
 "resultSet":{"count":125,"first":"2023-09-19","last":"2024-06-01","played":125}, ...
HTTP 200
```

125 matches of the 2023/24 season, complete including the knockout rounds. The
`seasons` array of `/competitions/CL` lists **47 seasons back to 1980-09-16**.

Consequences, all positive:

* Multi-season team form and head-to-head become computable.
* A backfill over past seasons is real work, not a demonstration.
* An ML training set with several thousand matches is realistic
  (≈ 47 × 125–144 ≈ 5 000–6 500 matches, still far under 1 GB raw).

Not yet verified: whether every one of the 47 seasons is served, or only recent
ones. To be probed before relying on it (backlog 1.8).

## 3. Correction 2 — referees are included, odds are not

`referees` was assumed unavailable on the free tier. It is populated:

```json
"referees": [
  {"id": 31823, "name": "Sandro Schärer", "type": "REFEREE", "nationality": "Switzerland"}
]
```

`odds`, by contrast, is a **stub object carrying a marketing message**, not a
number:

```json
"odds": {"msg": "Activate Odds-Package in User-Panel to retrieve odds."}
```

This is a schema trap: the field is always present and always a `dict`, so a
naive "field exists → parse it" check passes and then fails on the contents. Our
raw validation must check for the *expected keys*, not merely for presence.

## 4. Schema of the central object (`match`)

```json
{
  "id": 575323,                          // business key, unique across seasons
  "utcDate": "2026-09-08T16:45:00Z",     // kick-off, always UTC, never null in this sample
  "status": "FINISHED",                  // TIMED | FINISHED (in this sample)
  "matchday": 1,                         // 1..8 in the league phase
  "stage": "LEAGUE_STAGE",
  "group": null,                         // null in all 144 rows - see §5
  "lastUpdated": "2026-09-20T00:20:29Z", // candidate for incremental loading
  "homeTeam": {"id": 851, "name": "...", "shortName": "...", "tla": "BRU", "crest": "..."},
  "awayTeam": {"id": 58,  "...": "..."},
  "score": {
    "winner": "AWAY_TEAM",               // HOME_TEAM | AWAY_TEAM | DRAW | null
    "duration": "REGULAR",
    "fullTime": {"home": 2, "away": 3},
    "halfTime": {"home": 1, "away": 3}
  },
  "season": {"id": 2557, "startDate": "2026-09-08", "endDate": "2027-01-27",
             "currentMatchday": 2, "winner": null},
  "area": {...}, "competition": {...}, "referees": [...], "odds": {...}
}
```

Observations that shape the data model:

* **Business keys** are stable integers and unique in every sample:
  `match.id`, `team.id`, `season.id`, `competition.id`, `referee.id`.
  → natural `UNIQUE` constraints for idempotent upserts.
* **Nested team references** carry only 5 fields (`id`, `name`, `shortName`,
  `tla`, `crest`) — full team attributes come from `/competitions/CL/teams`.
  → `dim_team` is fed from the teams endpoint, matches reference it by id.
* **No nulls** in any team reference across 144 matches.
* **`lastUpdated`** exists per match → usable as the incremental-load watermark,
  to be validated over several days before relying on it.
* **`score.winner`** is the natural ML target label.
* Kick-off times: **zero** matches with a `00:00:00Z` placeholder in this sample,
  i.e. all league-phase times are already fixed. The `TBD` case still has to be
  handled for knockout fixtures (§5).

## 5. The 2024/25 format change is visible in the data

| | 2023/24 season | 2026/27 season |
|---|---|---|
| Matches in the season | 125 | 144 (so far) |
| Structure | 32 teams, 8 groups | 36 teams, single league phase |
| `stage` | `GROUP_STAGE`, `LAST_16`, … | `LEAGUE_STAGE` (all 144) |
| `group` in matches | populated | **`null` in all 144 rows** |

Two consequences:

1. We do **not** model a group dimension. A textbook fact/dimension design would
   have produced a table that is empty for every current-season row.
2. The same competition has different semantics across seasons. Any multi-season
   transformation must key on `season.id` and treat `stage` as season-dependent.

Inconsistent naming worth noting: in `matches`, `group` is `null`; in
`standings`, the same concept appears as the string `"League phase"`.

## 6. Fixtures appear during the season

`resultSet` of the current season: `{"count": 144, "first": "2026-09-08",
"last": "2027-01-27", "played": 18}`, and `currentSeason.endDate` is
**2027-01-27** — the end of the *league phase*, not of the competition.

The knockout fixtures do not exist yet; they are drawn in December. The fixture
list therefore **grows mid-season**, which is a direct argument for a scheduled
daily batch rather than a one-off load, and for keeping raw payloads per
ingestion date so the moment of appearance is traceable.

## 7. The `status` filter does not mean what it says

```console
GET /competitions/CL/matches?status=SCHEDULED   → 126 matches
```

…but every one of those 126 rows has `"status": "TIMED"`. `SCHEDULED` acts as a
broader query filter, while the stored value is `TIMED` once a kick-off time is
fixed.

Consequence: a SQL predicate `WHERE status = 'SCHEDULED'` on our own tables
would return **zero rows**. Upcoming matches must be selected by
`status IN ('SCHEDULED','TIMED')` or, better, by `utcDate > now()`.

## 8. Do not trust the API's aggregates

`/teams/{id}/matches` returns a `resultSet` summary. It does not add up:

| Team | count | played | wins | draws | losses | sum |
|---|---|---|---|---|---|---|
| 4 (Borussia Dortmund) | 5 | 5 | 3 | 0 | 0 | **3** |
| 86 (Real Madrid) | 5 | 5 | 4 | 0 | 2 | **6** |

Neither sums to the number of matches, and the two errors point in opposite
directions. Similarly, `form` is `null` for every row of the standings table.

Consequence: **we compute form ourselves** from the individual match rows, which
we would want anyway for point-in-time correctness — but now the decision rests
on measured evidence rather than preference.

## 9. Quantified limitation: domestic coverage is asymmetric

`/teams/{id}/matches` silently restricts results to competitions in our tier —
visible in the response: `"filters": {"competitions": "BL1,CL", "permission":
"TIER_ONE", ...}`.

Of the 36 league-phase clubs, **25 play in a domestic league covered by the free
tier; 11 do not**:

> Galatasaray (TSL), Fenerbahçe (TSL), Club Brugge (BJL), Slavia Praha, Shakhtar
> Donetsk (UPL), AEK Athens (GSL), LASK (ABL), Viking (TIP), Bodø/Glimt (TIP),
> Slovan Bratislava, Sabah FK

For those 11 clubs, "form over the last 5 matches" can only draw on Champions
League matches — currently one or two per club. Any form feature must therefore
carry the number of matches it is based on, and analyses must not silently
compare a 5-match form against a 1-match form.

This is the most consequential data-quality finding of the exploration and is
recorded in the known limitations.

## 10. Early-season sparsity

Sampled on 20 September 2026: one league-phase matchday played (18 matches), and
the sampled clubs had 5 completed matches in total across all covered
competitions. The rolling-5 window is therefore `PARTIAL` for most teams for the
first weeks of the season — the partial state designed into
`fact_team_match_form` is the normal case in September, not an edge case.

## 11. Inconclusive

`GET /matches/575341/head2head` returned `{"resultSet": {"count": 0},
"matches": []}`. Match 575341 is **Lens vs Sporting CP**, a pairing that
plausibly never met, so this does not show whether head-to-head is restricted.
Retest with a pairing known to have met (e.g. Real Madrid vs Bayern) before
building on the endpoint — backlog 2.5.

## 12. What changes because of this exploration

| Decision | Before | After |
|---|---|---|
| ADR-001 status | PROPOSED | **ACCEPTED** |
| Historical depth | "current season only" | 47 seasons listed, 2023/24 verified |
| Referees | assumed unavailable | available, usable as a match attribute |
| Odds | assumed unavailable | stub object — schema trap |
| Group dimension | planned as possible | dropped (null since 2024/25) |
| Form computation | our own, by preference | our own, because the API's aggregates are inconsistent |
| Upcoming-match predicate | `status = 'SCHEDULED'` | `utcDate > now()` |
| Coverage limitation | qualitative | quantified: 11 of 36 clubs without domestic data |
