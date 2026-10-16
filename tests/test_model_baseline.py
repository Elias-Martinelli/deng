"""Temporal separation and preprocessing isolation for the optional baseline."""

import pytest

pytest.importorskip("sklearn")
import numpy as np
import pandas as pd

from deng.model_baseline import FEATURES, NUMERIC, TARGET, build_model, chronological_split


def frame():
    dates = [
        "2024-01-01",
        "2024-01-02",
        "2024-01-03",
        "2025-06-30T22:00:00Z",
        "2025-07-01",
        "2025-07-01",
        "2025-07-02",
    ]
    rows = []
    for i, date in enumerate(dates):
        row = dict.fromkeys(NUMERIC, float(i))
        row.update(
            match_id=i,
            utc_kickoff=pd.Timestamp(date).isoformat(),
            competition_code="PL",
            label_outcome_90min=["AWAY_WIN", "DRAW", "HOME_WIN"][i % 3],
            audit_home_history_last_available_at=None,
            audit_away_history_last_available_at=None,
        )
        rows.append(row)
    result = pd.DataFrame(rows)
    result["utc_kickoff"] = pd.to_datetime(result.utc_kickoff, utc=True, format="mixed").astype(str)
    return result


def test_split_purges_unavailable_results_and_keeps_same_kickoff_together():
    train, test = chronological_split(frame(), "2025-07-01", "2026-07-01", "2026-01-01")
    assert list(train.match_id) == [0, 1, 2]
    assert list(test.match_id) == [4, 5, 6]
    assert set(train.match_id).isdisjoint(test.match_id)


def test_split_rejects_future_history_and_duplicate_matches():
    data = frame()
    data.loc[0, "audit_home_history_last_available_at"] = "2024-01-02"
    with pytest.raises(ValueError, match="History"):
        chronological_split(data, "2025-07-01", "2026-07-01")
    with pytest.raises(ValueError, match="Duplicate"):
        chronological_split(pd.concat([frame(), frame()]), "2025-07-01", "2026-07-01")


def test_test_values_cannot_change_training_imputer_or_scaler():
    train, test = chronological_split(frame(), "2025-07-01", "2026-07-01", "2026-01-01")
    train.loc[0, NUMERIC[0]] = np.nan
    model = build_model().fit(train[FEATURES], train[TARGET])
    numeric = model.named_steps["preprocess"].named_transformers_["numeric"]
    before = numeric.named_steps["scale"].mean_.copy()
    assert numeric.named_steps["impute"].statistics_[0] == 1.5
    test.loc[:, NUMERIC] = 999999.0
    test["competition_code"] = "UNSEEN"
    probabilities = model.predict_proba(test[FEATURES])
    np.testing.assert_array_equal(before, numeric.named_steps["scale"].mean_)
    np.testing.assert_allclose(probabilities.sum(axis=1), 1)
    assert not any(f.startswith(("label_", "audit_")) for f in FEATURES)
