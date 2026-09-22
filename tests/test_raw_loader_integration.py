"""Integration tests for the raw loader against a real PostgreSQL.

The central claim these tests defend: running the pipeline twice for the same
logical date does not duplicate data and does not lose data.
"""

from datetime import date

import pytest

from deng.database import RawLoader
from deng.database.raw_loader import count_records, hash_payload

pytestmark = pytest.mark.postgres

INGESTION_DATE = date(2026, 9, 20)
ENDPOINT = "competitions/CL/matches"


def row_count(connection) -> int:
    with connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM raw.football_data")
        return cursor.fetchone()[0]


def test_first_load_inserts_the_payload(connection, run_id, sample_payload):
    loader = RawLoader(connection)
    result = loader.load(
        run_id=run_id,
        endpoint=ENDPOINT,
        request_params={},
        request_url="https://api.football-data.org/v4/competitions/CL/matches",
        payload=sample_payload,
        ingestion_date=INGESTION_DATE,
    )
    connection.commit()

    assert result.inserted is True
    assert result.record_count == 144
    assert row_count(connection) == 1


def test_second_run_same_day_does_not_duplicate(connection, run_id, sample_payload):
    """The idempotency claim: run twice, same row count, row updated in place."""
    loader = RawLoader(connection)
    common = {
        "run_id": run_id,
        "endpoint": ENDPOINT,
        "request_params": {},
        "request_url": "https://api.football-data.org/v4/competitions/CL/matches",
        "payload": sample_payload,
        "ingestion_date": INGESTION_DATE,
    }

    first = loader.load(**common)
    connection.commit()
    after_first = row_count(connection)

    second = loader.load(**common)
    connection.commit()
    after_second = row_count(connection)

    assert first.inserted is True
    assert second.inserted is False
    assert second.updated is True
    assert after_first == after_second == 1
    assert first.payload_hash == second.payload_hash


def test_different_days_are_separate_rows(connection, run_id, sample_payload):
    """Two logical dates are two observations of the source, not a duplicate."""
    loader = RawLoader(connection)
    for day in (date(2026, 9, 19), date(2026, 9, 20)):
        loader.load(
            run_id=run_id,
            endpoint=ENDPOINT,
            request_params={},
            request_url="https://api.football-data.org/v4/competitions/CL/matches",
            payload=sample_payload,
            ingestion_date=day,
        )
    connection.commit()
    assert row_count(connection) == 2


def test_different_params_are_separate_rows(connection, run_id, sample_payload):
    """?status=FINISHED is a different question than no filter, so a different row."""
    loader = RawLoader(connection)
    loader.load(
        run_id=run_id,
        endpoint=ENDPOINT,
        request_params={},
        request_url="https://api.football-data.org/v4/competitions/CL/matches",
        payload=sample_payload,
        ingestion_date=INGESTION_DATE,
    )
    loader.load(
        run_id=run_id,
        endpoint=ENDPOINT,
        request_params={"status": "FINISHED"},
        request_url="https://api.football-data.org/v4/competitions/CL/matches?status=FINISHED",
        payload=sample_payload,
        ingestion_date=INGESTION_DATE,
    )
    connection.commit()
    assert row_count(connection) == 2


def test_changed_payload_replaces_the_stored_one(connection, run_id, sample_payload):
    """A rerun after the source changed must store the new state, not keep the old."""
    loader = RawLoader(connection)
    loader.load(
        run_id=run_id,
        endpoint=ENDPOINT,
        request_params={},
        request_url="https://api.football-data.org/v4/competitions/CL/matches",
        payload=sample_payload,
        ingestion_date=INGESTION_DATE,
    )
    changed = {**sample_payload, "matches": sample_payload["matches"][:10]}
    result = loader.load(
        run_id=run_id,
        endpoint=ENDPOINT,
        request_params={},
        request_url="https://api.football-data.org/v4/competitions/CL/matches",
        payload=changed,
        ingestion_date=INGESTION_DATE,
    )
    connection.commit()

    assert result.updated is True
    assert result.record_count == 10
    with connection.cursor() as cursor:
        cursor.execute("SELECT record_count, payload_hash FROM raw.football_data")
        stored_count, stored_hash = cursor.fetchone()
    assert stored_count == 10
    assert stored_hash == hash_payload(changed)


def test_payload_is_stored_unchanged(connection, run_id, sample_payload):
    """Raw means raw: what comes back out must equal what went in."""
    loader = RawLoader(connection)
    loader.load(
        run_id=run_id,
        endpoint=ENDPOINT,
        request_params={},
        request_url="https://api.football-data.org/v4/competitions/CL/matches",
        payload=sample_payload,
        ingestion_date=INGESTION_DATE,
    )
    connection.commit()
    with connection.cursor() as cursor:
        cursor.execute("SELECT payload FROM raw.football_data")
        stored = cursor.fetchone()[0]
    assert stored == sample_payload


def test_existing_hash_detects_an_unchanged_source(connection, run_id, sample_payload):
    loader = RawLoader(connection)
    assert loader.existing_hash(ENDPOINT, {}, INGESTION_DATE) is None
    loader.load(
        run_id=run_id,
        endpoint=ENDPOINT,
        request_params={},
        request_url="https://api.football-data.org/v4/competitions/CL/matches",
        payload=sample_payload,
        ingestion_date=INGESTION_DATE,
    )
    connection.commit()
    assert loader.existing_hash(ENDPOINT, {}, INGESTION_DATE) == hash_payload(sample_payload)


def test_raw_row_requires_a_known_run(connection, sample_payload):
    """Referential integrity: no raw data without a recorded run."""
    import uuid

    import psycopg

    loader = RawLoader(connection)
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        loader.load(
            run_id=uuid.uuid4(),
            endpoint=ENDPOINT,
            request_params={},
            request_url="https://api.football-data.org/v4/competitions/CL/matches",
            payload=sample_payload,
            ingestion_date=INGESTION_DATE,
        )
    connection.rollback()


def test_run_log_records_success(connection):
    from deng.database import PipelineRun

    with PipelineRun(connection, "test_pipeline", INGESTION_DATE) as run:
        run.add_counts(extracted=144, loaded=1)
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT status, rows_extracted, rows_loaded, finished_at IS NOT NULL "
            "FROM meta.pipeline_runs WHERE run_id = %s",
            (run.run_id,),
        )
        status, extracted, loaded, finished = cursor.fetchone()
    assert (status, extracted, loaded, finished) == ("SUCCESS", 144, 1, True)


def test_run_log_records_failure_and_reraises(connection):
    """A failing run stays visible as FAILED instead of vanishing."""
    from deng.database import PipelineRun

    with pytest.raises(RuntimeError, match="API unreachable"):
        with PipelineRun(connection, "test_pipeline", INGESTION_DATE) as run:
            raise RuntimeError("API unreachable")

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT status, error_message FROM meta.pipeline_runs WHERE run_id = %s",
            (run.run_id,),
        )
        status, message = cursor.fetchone()
    assert status == "FAILED"
    assert "API unreachable" in message


def test_hash_is_stable_regardless_of_key_order():
    assert hash_payload({"a": 1, "b": 2}) == hash_payload({"b": 2, "a": 1})
    assert hash_payload({"a": 1}) != hash_payload({"a": 2})


def test_record_count_finds_the_main_list():
    assert count_records({"matches": [1, 2, 3]}) == 3
    assert count_records({"teams": []}) == 0
    assert count_records({"nothing": "here"}) is None
