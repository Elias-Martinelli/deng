# Training enrichment evidence — 15 October 2026

This run addresses the five requested training-data gaps. Full explanation,
source references and remaining work: [training-data-gaps.md](../training-data-gaps.md).

## Executed work

- Real sport catalogue returned all eight configured sports as active.
- The existing CL fetch was reused. Seven additional odds calls stored 125 events;
  total 143 real events and 492 remaining credits. Every event matched a fixture.
- Added explicit Rennes alias after comparing both team identities and fixtures.
- Forecast ingestion stored 110/110 venue responses. MISSING fell from 101 to 1;
  213 matches now carry an eligible temperature. The remaining target hour for
  match 559639 contains NULL in the provider response at the 16-day horizon.
- Ten Betfair exchange quotes exceed the documented margin bounds. Kept in raw
  and observations, warned by DQ, excluded from the canonical training consensus.
- Quote cadence is per sport/request, quota reserve global. Separate competitions
  no longer invalidate each other's latest quotes. Daily cron uses 0 0 * * *.
- Updated .env locally without printing or committing credentials. No provider
  plan was purchased; Docker daemons/containers were not restarted.

## Reproducible outputs

- data/processed/training-ready-2026-10-15/: 10,103 rows, 292 columns;
  matches.csv, manifest.json, data_dictionary.json and coverage.json.
- data/processed/baseline-final-2026-10-15/: fitted model.joblib, test_predictions.csv,
  metrics.json. Source checksum and versions are recorded.
- [Committed small metrics report](baseline-2026-10-15.json): 5,040 train / 2,552
  test matches, accuracy 50.63% vs 44.16%, macro-F1 0.3861 vs 0.2042,
  log loss 1.0313 vs 1.0709. Only 6/642 test draws predicted correctly.

The earlier enriched-2026-10-15 export is marked SUPERSEDED because it predates
exclusion of anomalous odds. Older dated exports are historical snapshots.

## Validation

- Full automated suite: **203 passed**, two existing Dagster deprecation warnings.
- Code lint and formatting checks passed.
- SQL verification: 4/4 files passed, including no API key in raw URLs/params,
  no future observations and one training row per match.
- DQ: 27/29 passed, zero critical failures. Two warnings deliberately remain:
  one missing horizon forecast and ten questionable source odds.
- Regression tests cover separate sport cadence, shared reserve, one daily global
  quota probe, sport-scoped withdrawal, anomalous latest quotes without fallback,
  chronological split boundaries and preprocessing isolation.
- Existing weather/odds tests now use explicit simulated times rather than
  relying on September fixture dates still being in the future. The production
  receipt timestamps continue to use the actual wall clock.

Compose YAML and odds environment mappings parsed successfully. A Docker CLI
validation could not run because Docker is unavailable in the current WSL distro.
No current Docker rebuild or fresh second-machine reproduction was performed;
those are distinct from the earlier 3 October container smoke test. Changes
remain local for review; no commit, push, paid subscription or submission made.
