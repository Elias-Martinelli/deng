"""Validate dated enrichment inputs and point-in-time joins."""

import csv
import io
from datetime import date, timedelta

import pytest

from deng.database import RawLoader
from deng.sources.team_context import ingest, parse_csv
from deng.transformation import run_transformations
from deng.transformation.runner import TRAINING_TRANSFORMATION_ORDER


def _csv(rows):
    fields = sorted(set().union(*(r.keys() for r in rows)))
    handle = io.StringIO()
    writer = csv.DictWriter(handle, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    return handle.getvalue()


def _row(**overrides):
    row = {
        "team_id": 1,
        "observed_at": "2024-01-01T00:00:00Z",
        "valid_from": "2024-01-01T00:00:00Z",
        "source": "test-only",
        "source_url": "https://example.test/archive",
        "squad_market_value_eur": 100,
    }
    return row | overrides


@pytest.mark.parametrize(
    "change",
    [
        {"observed_at": "2024-01-01"},
        {"squad_market_value_eur": "nan"},
        {"squad_market_value_eur": -1},
        {"team_id": 0},
        {"valid_until": "2023-01-01T00:00:00Z"},
        {"coach_id": "x", "coach_name": "Example"},
        {"squad_size": 10, "squad_goalkeepers": 12},
    ],
)
def test_invalid_snapshot_fails_before_writes(change):
    with pytest.raises(ValueError):
        parse_csv(_csv([_row(**change)]))


def test_coach_identifiers_are_namespaced_and_timestamps_normalized():
    parsed = parse_csv(
        _csv(
            [
                _row(
                    coach_id="42",
                    coach_name="Test coach",
                    coach_namespace="provider",
                    observed_at="2024-01-01T02:00:00+02:00",
                )
            ]
        )
    )[0]
    assert parsed["coach_id"] == "provider:42"
    assert parsed["observed_at"] == "2024-01-01T00:00:00+00:00"


def test_duplicate_snapshot_is_rejected():
    with pytest.raises(ValueError, match="duplicate"):
        parse_csv(_csv([_row(), _row()]))


@pytest.mark.postgres
def test_snapshot_asof_join_expiry_future_exclusion_and_idempotence(
    connection,
    run_id,
    all_samples,
    tmp_path,
):
    day = date(2026, 9, 20)
    for endpoint, payload in all_samples.items():
        RawLoader(connection).load(
            run_id=run_id,
            endpoint=endpoint,
            request_params={},
            request_url="test://samples",
            payload=payload,
            ingestion_date=day,
        )
    connection.commit()
    run_transformations(connection, day)
    match_id, team_id, kickoff = connection.execute(
        "SELECT match_id, home_team_id, utc_kickoff FROM curated.fact_match "
        "ORDER BY utc_kickoff, match_id LIMIT 1"
    ).fetchone()
    connection.commit()
    before = (kickoff - timedelta(days=2)).isoformat()
    after = (kickoff + timedelta(hours=1)).isoformat()
    path = tmp_path / "snapshots.csv"
    path.write_text(
        _csv(
            [
                _row(
                    team_id=team_id,
                    observed_at=before,
                    valid_from=before,
                    squad_market_value_eur=100,
                    squad_size=22,
                    squad_avg_age=25,
                    coach_id="42",
                    coach_namespace="test",
                    coach_name="Coach",
                ),
                _row(
                    team_id=team_id,
                    observed_at=after,
                    valid_from=before,
                    squad_market_value_eur=999999,
                ),
                _row(
                    team_id=team_id,
                    observed_at=(kickoff - timedelta(days=1)).isoformat(),
                    valid_from=before,
                    valid_until=kickoff.isoformat(),
                    squad_market_value_eur=888888,
                ),
            ]
        )
    )
    assert ingest(connection, day, run_id, path).stored == 1
    assert ingest(connection, day, run_id, path).stored == 0
    run_transformations(connection, day, order=TRAINING_TRANSFORMATION_ORDER, counted=())
    row = connection.execute(
        "SELECT squad_market_value_eur, squad_size, coach_id, coach_prior_matches "
        "FROM curated.fact_match_team_context WHERE match_id=%s AND team_id=%s",
        (match_id, team_id),
    ).fetchone()
    assert row == (100, 22, "test:42", 0)
    # API samples were fetched now: their current coach cannot backfill an old game.
    assert (
        connection.execute(
            "SELECT count(*) FROM curated.fact_match_team_context c "
            "JOIN curated.fact_match m USING(match_id) "
            "WHERE c.coach_observed_at >= m.utc_kickoff"
        ).fetchone()[0]
        == 0
    )
