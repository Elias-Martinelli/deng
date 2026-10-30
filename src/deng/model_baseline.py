"""Train and evaluate a fixed logistic baseline on a chronological holdout."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, log_loss
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

TARGET = "label_outcome_90min"
CLASSES = ["AWAY_WIN", "DRAW", "HOME_WIN"]
# Explicit allowlist: no scores, target-match statistics, IDs, names, standings,
# current roster observations, weather or sparse newly captured bookmaker odds.
NUMERIC = [
    f"{side}_{feature}"
    for side in ("home", "away")
    for feature in (
        "history_matches",
        "rest_days",
        "played_last_7_days",
        "played_last_14_days",
        "matches_last_5",
        "goals_for_per_match_last_5",
        "goals_against_per_match_last_5",
        "points_per_match_last_5",
        "matches_last_10",
        "goals_for_per_match_last_10",
        "goals_against_per_match_last_10",
        "points_per_match_last_10",
        "venue_points_per_match_last_5",
        "season_matches",
        "season_points_per_match",
        "h2h_matches_last_5",
    )
]
FEATURES = NUMERIC + ["competition_code"]


def chronological_split(frame, train_before, test_before, available_at=None):
    """Keep labels known at training time and test only later, completed games."""
    data = frame.copy()
    if data.match_id.duplicated().any():
        raise ValueError("Duplicate match IDs in dataset")
    kickoff = pd.to_datetime(data.utc_kickoff, utc=True, errors="raise")
    start, end = pd.Timestamp(train_before), pd.Timestamp(test_before)
    if start.tzinfo is None:
        start = start.tz_localize("UTC")
    if end.tzinfo is None:
        end = end.tz_localize("UTC")
    if start >= end:
        raise ValueError("train-before must precede test-before")
    now = pd.Timestamp(available_at or datetime.now(timezone.utc))
    if now.tzinfo is None:
        now = now.tz_localize("UTC")
    completed = data[TARGET].isin(CLASSES) & (kickoff + pd.Timedelta(hours=3) < now)
    train = data[completed & (kickoff + pd.Timedelta(hours=3) < start)].copy()
    test = data[completed & (kickoff >= start) & (kickoff < end)].copy()
    if train.empty or test.empty:
        raise ValueError("Chronological split needs nonempty train and test periods")
    if set(train[TARGET]) != set(CLASSES):
        raise ValueError("Training period must contain all three outcomes")
    # The feature builder uses completed earlier matches as they become available.
    # Validate that contract independently rather than trusting column names.
    for side in ("home", "away"):
        name = f"audit_{side}_history_last_available_at"
        history = pd.to_datetime(data[name], utc=True, errors="raise")
        if (history.notna() & (history >= kickoff)).any():
            raise ValueError("History contains information unavailable before kickoff")
    return train.sort_values(["utc_kickoff", "match_id"]), test.sort_values(
        ["utc_kickoff", "match_id"]
    )


def build_model():
    """Fit missing-value replacement, scaling and encoding on training rows only."""
    numeric = Pipeline(
        [
            ("impute", SimpleImputer(strategy="median", keep_empty_features=True)),
            ("scale", StandardScaler()),
        ]
    )
    preprocessing = ColumnTransformer(
        [
            ("numeric", numeric, NUMERIC),
            ("league", OneHotEncoder(handle_unknown="ignore"), ["competition_code"]),
        ]
    )
    return Pipeline(
        [
            ("preprocess", preprocessing),
            ("classifier", LogisticRegression(C=1.0, max_iter=2000, random_state=0)),
        ]
    )


def metrics(labels, probabilities):
    """Report classification and probability quality in the declared class order."""
    predicted = np.asarray(CLASSES)[probabilities.argmax(axis=1)]
    truth = np.array([[int(y == c) for c in CLASSES] for y in labels])
    return {
        "rows": len(labels),
        "accuracy": float(accuracy_score(labels, predicted)),
        "macro_f1": float(
            f1_score(labels, predicted, labels=CLASSES, average="macro", zero_division=0)
        ),
        "log_loss": float(log_loss(labels, probabilities, labels=CLASSES)),
        "brier_multiclass_sum": float(np.mean(np.sum((probabilities - truth) ** 2, axis=1))),
        "confusion_matrix_true_rows_predicted_columns": confusion_matrix(
            labels, predicted, labels=CLASSES
        ).tolist(),
    }


def evaluate(dataset: Path, output: Path, train_before: str, test_before: str):
    """Save a reproducible experiment, predictions and fitted model in a new folder."""
    if output.exists():
        raise FileExistsError(f"Output exists: {output}; choose a new directory")
    frame = pd.read_csv(dataset, low_memory=False)
    train, test = chronological_split(frame, train_before, test_before)
    model = build_model().fit(train[FEATURES], train[TARGET])
    assert list(model.classes_) == CLASSES
    prior = DummyClassifier(strategy="prior").fit(train[FEATURES], train[TARGET])
    probabilities = model.predict_proba(test[FEATURES])
    prior_probabilities = prior.predict_proba(test[FEATURES])
    report = {
        "model": "multinomial-logistic-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
        "target": TARGET,
        "classes": CLASSES,
        "features": FEATURES,
        "train_before": train_before,
        "test_before": test_before,
        "train_rows": len(train),
        "test_rows": len(test),
        "train_kickoff_min": str(train.utc_kickoff.min()),
        "train_kickoff_max": str(train.utc_kickoff.max()),
        "test_kickoff_min": str(test.utc_kickoff.min()),
        "test_kickoff_max": str(test.utc_kickoff.max()),
        "train_class_counts": {str(k): int(v) for k, v in train[TARGET].value_counts().items()},
        "versions": {
            "sklearn": sklearn.__version__,
            "pandas": pd.__version__,
            "numpy": np.__version__,
        },
        "logistic": metrics(test[TARGET], probabilities),
        "training_class_prior": metrics(test[TARGET], prior_probabilities),
        "by_competition": {},
        "limitations": [
            "Retrospective reconstructed results; original publication times unverified.",
            "Model frozen at split; form updates with earlier completed test-period matches.",
            "Three-hour completion assumption; not a fixed 24-hour-before-kickoff forecast.",
            "Fixed C=1; no tuning on test data; no claim of betting profitability.",
            "Sparse roster, coach, value, weather and odds history excluded from model.",
        ],
    }
    for competition in sorted(test.competition_code.unique()):
        selected = (test.competition_code == competition).to_numpy()
        report["by_competition"][competition] = {
            "logistic": metrics(test.loc[selected, TARGET], probabilities[selected]),
            "training_class_prior": metrics(
                test.loc[selected, TARGET], prior_probabilities[selected]
            ),
        }
    output.mkdir(parents=True)
    predictions = test[["match_id", "utc_kickoff", "competition_code", TARGET]].copy()
    for index, label in enumerate(CLASSES):
        predictions[f"prob_{label.lower()}"] = probabilities[:, index]
        predictions[f"prior_prob_{label.lower()}"] = prior_probabilities[:, index]
    predictions.to_csv(output / "test_predictions.csv", index=False)
    joblib.dump(model, output / "model.joblib")
    (output / "metrics.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main():
    """CLI for an optional, separately installed dataset consumer."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--train-before", default="2025-07-01")
    parser.add_argument("--test-before", default="2026-07-01")
    args = parser.parse_args()
    report = evaluate(args.dataset, args.output, args.train_before, args.test_before)
    print(
        json.dumps(
            {k: report[k] for k in ("train_rows", "test_rows", "logistic", "training_class_prior")},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
