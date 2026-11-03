"""Tests for streaming exports, target separation and preservation of prior exports."""

import csv
import gzip
import hashlib
import json
from datetime import date

import pytest

from deng.database import RawLoader
from deng.export import column_role, export_dataset
from deng.pipeline import command_transform


@pytest.mark.parametrize(
    "column",
    [
        "label_outcome_90min",
        "label_home_goals_90min",
        "label_available",
    ],
)
def test_target_columns_never_become_features(column):
    assert column_role(column) == "label"


@pytest.mark.parametrize(
    "column",
    [
        "audit_result_duration",
        "audit_match_status",
        "home_squad_observed_at",
        "audit_feature_version",
        "home_team_id",
    ],
)
def test_metadata_never_becomes_features(column):
    assert column_role(column) != "feature"


@pytest.mark.postgres
def test_export_preserves_grain_coverage_and_checksum(connection, run_id, all_samples, tmp_path):
    logical_date = date(2026, 9, 20)
    loader = RawLoader(connection)
    for endpoint, payload in all_samples.items():
        loader.load(
            run_id=run_id,
            endpoint=endpoint,
            request_params={},
            request_url="test://sample",
            payload=payload,
            ingestion_date=logical_date,
        )
    connection.commit()
    assert command_transform(logical_date) == 0
    destination = tmp_path / "dataset"
    report = export_dataset(connection, destination)
    with gzip.open(destination / report["file"], "rt") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == report["rows"] == 144
    assert len({row["match_id"] for row in rows}) == 144
    assert report["columns"] > 200
    assert "home_world_rating_points" in report["feature_columns"]
    assert "audit_home_world_ranking_observed_at" in report["audit_columns"]
    assert report["source_attributions"][0]["license"] == "CC BY-SA 4.0"
    assert (
        hashlib.sha256((destination / report["file"]).read_bytes()).hexdigest() == report["sha256"]
    )
    assert not any(c.startswith(("label_", "audit_")) for c in report["feature_columns"])
    coverage = json.loads((destination / "coverage.json").read_text())
    target = next(row for row in coverage if row["column"] == report["target"])
    assert target["present"] == sum(bool(row[report["target"]]) for row in rows)
    with pytest.raises(FileExistsError):
        export_dataset(connection, destination)
    labelled = export_dataset(connection, tmp_path / "labelled", labelled_only=True, compress=False)
    assert labelled["rows"] == target["present"]
    assert "UNLABELLED" not in labelled["labels"]
