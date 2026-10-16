# Multi-league dataset — measured evidence

## Later enrichment run — 15 October 2026

The measurements below describe the 3 October snapshot. For the later eight-league odds import, refreshed weather, quality exclusions and trained baseline see [training-enrichment-2026-10-15.md](training-enrichment-2026-10-15.md).

Date: 3 October 2026. Local PostgreSQL and the repository's Python environment.
All counts below are measured, not estimates.

## Result

| Competition | Matches | 90-minute labels |
|---|---:|---:|
| BL1 | 1,224 | 953 |
| CL | 647 | 521 |
| DED | 1,224 | 981 |
| FL1 | 1,224 | 961 |
| PD | 1,520 | 1,209 |
| PL | 1,520 | 1,190 |
| PPL | 1,224 | 980 |
| SA | 1,520 | 1,190 |

Total: **10,103 matches, 292 columns, 203 teams**.
There are 244 candidate predictor columns; an analyst
must still select useful features and fit preprocessing on the training period.
The export covers 2023-08-11 19:30:00+02:00 through 2027-05-30 17:00:00+02:00.

## Measured enrichment

- 7,324 player observations (player × snapshot; not unique people).
- 408 team snapshots; 272 with squads, 326 with coaches.
- 2,082 rows have a home squad size; 1,705 have a home coach age.
- 8,434 rows have ten prior 90-minute results for both sides.
- 113 rows have an eligible pre-kickoff temperature forecast.
- 0 rows have home market values: no dated valuation source was supplied.
- 0 rows have real bookmaker consensus. No ODDS_API_KEY is configured.
- Venue states: {'NOT_AVAILABLE': 37, 'RESOLVED': 166}. Unresolved grounds have explicit missing status.
- Synthetic odds samples are excluded from the training product; retained only
  in the demonstration history.

The delivered CSV and complete per-column coverage are in the ignored folder
[data/processed/midterm-ready-2026-10-03](../../data/processed/midterm-ready-2026-10-03/).
Its manifest, dictionary and coverage report are delivered alongside the CSV.
The earlier preliminary export is marked SUPERSEDED and must not be used.

## Validation

- **194 tests passed**, including real PostgreSQL integration and in-process Dagster.
- Ruff check and formatting check pass; git diff whitespace check passes.
- Container image builds. Docker init, offline run and verification execute in a
  separate disposable database; no live data is truncated.
- Both Streamlit views were executed against the live 10,103-match warehouse;
  no application exception occurred.
- Verification: four SQL verification files pass.
- Data quality: 28/29 pass,
  **zero critical failures**. Remaining warnings:
- no_forecast_missing_inside_horizon: 9 match(es) MISSING

## Observed failures and fixes

The first expanded venue run timed out on a Nominatim request. Venue requests
now retry bounded transient errors and commit independent successful answers,
so reruns resume missing clubs. All 143 additional clubs were subsequently processed.
The provider returned empty forecast values at the forecast horizon; these now
remain missing instead of being marked AVAILABLE and violating the constraint.
Both behaviours have regression tests.

An old RUNNING test record from 30 September predates this work. With no active
database sessions, it was marked FAILED with an explanatory note; its data was
retained. New tests always use a disposable database.

## Reproduce

Run make init, configure the league/season profile, then make dataset.
Run make run for current venue/weather/crest collection.
Run make test, make lint, make verify and make export.
See the README and midterm runbook for a key-free demonstration.

Remaining human tasks: independent peer reproduction, oral rehearsal by both
students, course submission and assessment. Cloud and Terraform remain final work.
