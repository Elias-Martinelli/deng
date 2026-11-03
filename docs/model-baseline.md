# Reproducible match-result baseline

This is a dataset consumer, separate from the dashboard's existing form-Poisson
forecast. It trains a multinomial logistic regression for HOME_WIN / DRAW /
AWAY_WIN after 90 minutes, including stoppage time.

## Run

```bash
.venv/bin/python -m pip install -e ".[ml]"
.venv/bin/python -m deng.model_baseline \
  --dataset data/processed/training-ready-2026-10-15/matches.csv \
  --output data/processed/my-baseline-run \
  --train-before 2025-07-01 --test-before 2026-07-01
```

The output must be a new directory. For a clean checkout, first generate a live
export with make dataset / make run / make export and pass its matches.csv or
matches.csv.gz path. The committed samples do not span these train/test periods
and deliberately fail the nonempty-split check.

Outputs: metrics.json (including source SHA-256 and library versions),
test_predictions.csv (actual outcomes and model/reference probabilities) and
model.joblib (fitted preprocessing and classifier). Only load model files you
trust. Small measured results are retained in
[evidence/baseline-2026-10-15.json](evidence/baseline-2026-10-15.json).

## Evaluation contract

- Fixed train cutoff 2025-07-01 UTC; held-out test ends before 2026-07-01 UTC.
- Train labels must have kickoff + 3 hours strictly before the cutoff. Equal
  kickoffs are never split across train/test; future/unlabelled games excluded.
- 32 explicit numeric form, rest, workload and covered-history features plus
  competition. Team IDs, names, target scores, result metadata, sparse current
  squads/coaches/values, weather and odds are excluded.
- Median imputation, scaling and league encoding are fitted on training only.
- Fixed C=1, no tuning on test results. Compare against training class priors
  on the identical test matches. Per-competition metrics and class confusion
  matrices prevent the headline accuracy from hiding poor draw predictions.
- Model parameters stay fixed during the test season. Form can use earlier
  completed test-season matches as they become available before each kickoff.
  This is a sequential retrospective evaluation, not a forecast of an entire
  season with knowledge frozen at its first day.
- Audit timestamps are checked independently. Historical results are still
  reconstructed from the current warehouse with a three-hour availability
  assumption; original publication times/corrections were not archived.
- No fixed 24-hour lead time, calibrated betting edge or profit claim.

## Measured result, 15 October 2026

5,040 training matches; 2,552 test matches. Accuracy 50.63% vs 44.16% for
training class priors; macro-F1 0.3861 vs 0.2042; log loss 1.0313 vs 1.0709.
Multiclass Brier score (sum over classes) 0.6154 vs 0.6477.
Only 6 of 642 draws classified correctly. Further work should use a separate
validation period, rolling time splits and calibration assessment. This
already-inspected test period must not be used as a fresh unbiased test after tuning.

Implementation: src/deng/model_baseline.py. Tests cover label availability at
the boundary, equal kickoff grouping, duplicate IDs, future-history rejection,
and training-only preprocessing with unseen test leagues.
