"""The raw zone behind one interface, and its GCS half (backlog 9.1-9.3).

Claims defended:

* the object name is a function of the business key: a rerun of the same day
  overwrites its own object, a new day or a new question gets a new one (9.2);
* the body is one line of JSON with the envelope of a raw.football_data row;
* INSERTED / UPDATED / UNCHANGED mean in GCS what they mean in PostgreSQL;
* the answer goes from memory into one upload - no file on the way (9.3);
* RAW_TARGETS picks the raw zones; GCS without a bucket, or without
  PostgreSQL, fails at start-up instead of at the first write (9.1);
* with both targets, a sample run lands the same answers in both, a rerun adds
  nothing, and a GCS failure rolls the PostgreSQL writes back;
* weather, odds and stadium answers are mirrored with their own table's key:
  one object per venue per day, per odds fetch, per club per day.

GCS is an in-memory bucket with the three calls the writer makes, so nothing
here needs a network or credentials.
"""

import json
import tempfile
import uuid
from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from deng.config import Settings
from deng.database.raw_loader import RawLoader, hash_payload
from deng.raw_zone import FanOutWriter, GcsRawWriter, object_name, open_raw_writer
from deng.raw_zone import gcs as gcs_module
from deng.raw_zone.gcs import key_hash, partition_value

DAY = date(2026, 11, 17)
FIXED_NOW = datetime(2026, 11, 17, 5, 0, tzinfo=timezone.utc)


class FakeBlob:
    def __init__(self, bucket, name):
        self.bucket = bucket
        self.name = name
        self.metadata = None

    def upload_from_string(self, data, content_type):
        assert isinstance(data, bytes), "the body is uploaded from memory, as bytes"
        if self.bucket.fail_uploads:
            raise RuntimeError("GCS is unavailable")
        self.bucket.objects[self.name] = {
            "data": data,
            "content_type": content_type,
            "metadata": dict(self.metadata or {}),
        }
        self.bucket.uploads += 1


class FakeBucket:
    """Holds objects in a dict; offers blob(), get_blob() and nothing else."""

    name = "test-raw"

    def __init__(self, fail_uploads=False):
        self.objects = {}
        self.uploads = 0
        self.fail_uploads = fail_uploads

    def blob(self, name):
        return FakeBlob(self, name)

    def get_blob(self, name):
        stored = self.objects.get(name)
        if stored is None:
            return None
        blob = FakeBlob(self, name)
        blob.metadata = dict(stored["metadata"])
        return blob

    def body(self, name):
        data = self.objects[name]["data"].decode("utf-8")
        assert data.endswith("\n") and data.count("\n") == 1, "one NDJSON line"
        return json.loads(data)


def write(writer, payload, *, endpoint="competitions/CL/matches", params=None, day=DAY):
    return writer.load(
        run_id=uuid.uuid4(),
        endpoint=endpoint,
        request_params=params or {},
        request_url=f"https://api.football-data.org/v4/{endpoint}",
        payload=payload,
        ingestion_date=day,
    )


# --- object names (9.2) ------------------------------------------------------


def test_object_name_is_hive_partitioned_by_source_endpoint_and_day():
    name = object_name("football-data.org", "competitions/CL/matches", {}, DAY)
    assert name.startswith(
        "raw/source=football-data.org/endpoint=competitions.CL.matches/ingestion_date=2026-11-17/"
    )
    assert name.endswith(".json")


def test_the_same_question_on_the_same_day_always_gets_the_same_name():
    first = object_name("football-data.org", "competitions/CL/matches", {"a": 1, "b": 2}, DAY)
    again = object_name("football-data.org", "competitions/CL/matches", {"b": 2, "a": 1}, DAY)
    assert first == again


def test_another_day_question_or_source_gets_another_name():
    base = object_name("football-data.org", "competitions/CL/matches", {}, DAY)
    assert base != object_name(
        "football-data.org", "competitions/CL/matches", {}, date(2026, 11, 18)
    )
    assert base != object_name(
        "football-data.org", "competitions/CL/matches", {"season": "2024"}, DAY
    )
    assert base != object_name("football-data.org", "competitions/PL/matches", {}, DAY)
    assert base != object_name("football-data.org (sample)", "competitions/CL/matches", {}, DAY)


def test_partition_values_are_path_safe_but_names_still_tell_the_keys_apart():
    assert partition_value("football-data.org (sample)") == "football-data.org-sample"
    assert partition_value("a/b") == partition_value("a.b") == "a.b"
    # Same directory, different file: the name hashes the exact values.
    assert key_hash("s", "a/b", {}) != key_hash("s", "a.b", {})


def test_a_partition_value_cannot_be_empty():
    with pytest.raises(ValueError):
        partition_value(" / ")


# --- writing ---------------------------------------------------------------


def test_the_first_write_inserts_one_object_holding_the_full_envelope():
    bucket = FakeBucket()
    writer = GcsRawWriter(bucket, now=lambda: FIXED_NOW)
    payload = {"matches": [{"id": 1}, {"id": 2}], "name": "Bodø/Glimt"}

    result = write(writer, payload, params={"season": "2024"})

    assert result.action == "INSERTED"
    assert result.record_count == 2
    (name,) = bucket.objects
    body = bucket.body(name)
    assert body["payload"] == payload  # stored unchanged, non-ASCII included
    assert body["payload_hash"] == hash_payload(payload) == result.payload_hash
    assert body["source"] == "football-data.org"
    assert body["endpoint"] == "competitions/CL/matches"
    assert body["request_params"] == {"season": "2024"}
    assert body["ingestion_date"] == "2026-11-17"
    assert body["ingested_at"] == FIXED_NOW.isoformat()
    assert body["record_count"] == 2
    uuid.UUID(body["run_id"])
    assert bucket.objects[name]["metadata"]["payload_hash"] == result.payload_hash
    assert bucket.objects[name]["content_type"] == "application/json"


def test_a_rerun_with_the_same_answer_is_unchanged_and_overwrites_in_place():
    bucket = FakeBucket()
    writer = GcsRawWriter(bucket)
    write(writer, {"matches": []})

    again = write(writer, {"matches": []})

    assert again.action == "UNCHANGED"
    assert len(bucket.objects) == 1
    assert bucket.uploads == 2  # rewritten, so it names the latest run - as in Postgres


def test_a_changed_answer_on_the_same_day_is_updated_in_place():
    bucket = FakeBucket()
    writer = GcsRawWriter(bucket)
    write(writer, {"matches": [{"id": 1, "status": "SCHEDULED"}]})

    changed = write(writer, {"matches": [{"id": 1, "status": "FINISHED"}]})

    assert changed.action == "UPDATED"
    (name,) = bucket.objects
    assert bucket.body(name)["payload"]["matches"][0]["status"] == "FINISHED"


def test_a_new_day_is_a_new_object():
    bucket = FakeBucket()
    writer = GcsRawWriter(bucket)
    write(writer, {"matches": []}, day=date(2026, 11, 16))
    assert write(writer, {"matches": []}).action == "INSERTED"
    assert len(bucket.objects) == 2


def test_existing_hash_reads_the_metadata_of_that_days_object():
    bucket = FakeBucket()
    writer = GcsRawWriter(bucket)
    assert writer.existing_hash("competitions/CL/matches", {}, DAY) is None
    stored = write(writer, {"matches": []})
    assert writer.existing_hash("competitions/CL/matches", {}, DAY) == stored.payload_hash


def test_the_answer_goes_from_memory_to_the_bucket_without_a_local_file(tmp_path, monkeypatch):
    def no_temporary_files(*args, **kwargs):
        raise AssertionError("the GCS path must not write a local intermediate file")

    for name in ("NamedTemporaryFile", "TemporaryFile", "SpooledTemporaryFile", "mkstemp"):
        monkeypatch.setattr(tempfile, name, no_temporary_files)
    monkeypatch.chdir(tmp_path)

    write(GcsRawWriter(FakeBucket()), {"matches": [{"id": 1}]})

    assert list(tmp_path.iterdir()) == []


# --- one interface, several raw zones (9.1) ----------------------------------


class RecordingWriter:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def load(self, **kwargs):
        if self.fail:
            raise RuntimeError("mirror down")
        self.calls.append(kwargs)
        return GcsRawWriter(FakeBucket()).load(**kwargs)


def test_fan_out_reports_the_primary_and_writes_every_mirror():
    primary, mirror = RecordingWriter(), RecordingWriter()
    result = write(FanOutWriter(primary, mirror), {"matches": [{"id": 1}]})
    assert result.record_count == 1
    assert primary.calls == mirror.calls and len(mirror.calls) == 1


def test_a_failing_mirror_fails_the_write():
    with pytest.raises(RuntimeError, match="mirror down"):
        write(FanOutWriter(RecordingWriter(), RecordingWriter(fail=True)), {"matches": []})


def test_postgres_is_the_only_raw_zone_by_default(clean_env):
    settings = Settings(_env_file=None)
    assert settings.raw_target_list == ["postgres"]
    assert isinstance(open_raw_writer(object(), settings, source="x"), RawLoader)


def test_postgres_and_gcs_open_both_raw_zones(clean_env):
    settings = Settings(_env_file=None, raw_targets=" Postgres, gcs, gcs ", gcs_raw_bucket="b")
    assert settings.raw_target_list == ["postgres", "gcs"]
    writer = open_raw_writer(object(), settings, source="football-data.org", bucket=FakeBucket())
    assert isinstance(writer, FanOutWriter)
    assert isinstance(writer.primary, RawLoader)
    (mirror,) = writer.mirrors
    assert isinstance(mirror, GcsRawWriter) and mirror.source == "football-data.org"


def test_a_gcs_target_without_a_bucket_fails_at_start_up(clean_env):
    with pytest.raises(ValidationError, match="GCS_RAW_BUCKET"):
        Settings(_env_file=None, raw_targets="postgres,gcs")


@pytest.mark.parametrize("value", ["gcs", "", "postgres,s3"])
def test_raw_targets_must_be_known_and_include_postgres(clean_env, value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, raw_targets=value, gcs_raw_bucket="b")


# --- end to end against PostgreSQL -------------------------------------------


@pytest.fixture
def mirrored(monkeypatch):
    """RAW_TARGETS=postgres,gcs with the bucket replaced by an in-memory one."""
    from deng.config import get_settings

    monkeypatch.setenv("RAW_TARGETS", "postgres,gcs")
    monkeypatch.setenv("GCS_RAW_BUCKET", "test-raw")
    bucket = FakeBucket()
    monkeypatch.setattr(gcs_module, "bucket_from_settings", lambda project, name: bucket)
    return bucket, get_settings()


def football_rows(connection):
    return connection.execute(
        "SELECT source, endpoint, request_params, ingestion_date, payload_hash "
        "FROM raw.football_data ORDER BY endpoint"
    ).fetchall()


@pytest.mark.postgres
def test_a_mirrored_sample_run_lands_the_same_answers_in_both_raw_zones(
    connection, run_id, mirrored
):
    from deng.sources import football_data

    bucket, settings = mirrored
    day = date(2026, 9, 20)

    football_data.ingest(connection, day, run_id, settings, from_samples=True)
    rows = football_rows(connection)

    assert rows and len(bucket.objects) == len(rows)
    for source, endpoint, params, ingestion_date, payload_hash in rows:
        name = object_name(source, endpoint, params, ingestion_date)
        assert bucket.objects[name]["metadata"]["payload_hash"] == payload_hash

    # The rerun of the same day: same objects, nothing added on either side.
    result = football_data.ingest(connection, day, run_id, settings, from_samples=True)
    assert len(bucket.objects) == len(football_rows(connection)) == len(rows)
    assert all(" UNCHANGED " in line for line in result.lines)


@pytest.mark.postgres
def test_a_gcs_failure_rolls_back_the_postgres_writes_of_the_run(connection, run_id, mirrored):
    from deng.sources import football_data

    bucket, settings = mirrored
    bucket.fail_uploads = True

    with pytest.raises(RuntimeError, match="GCS is unavailable"):
        football_data.ingest(connection, date(2026, 9, 20), run_id, settings, from_samples=True)

    assert football_rows(connection) == []


# --- the other sources: weather, odds, stadiums --------------------------------


def objects_of(bucket, source):
    prefix = f"raw/source={partition_value(source)}/"
    return [name for name in bucket.objects if name.startswith(prefix)]


@pytest.mark.postgres
def test_a_mirrored_sample_run_writes_every_raw_row_of_every_source_to_gcs(connection, mirrored):
    from deng import clock, pipeline

    bucket, _ = mirrored
    tables = {
        "football-data.org (sample)": "raw.football_data",
        "openstreetmap.org": "raw.osm_venues",
        "open-meteo.com": "raw.open_meteo",
        "the-odds-api.com (sample)": "raw.odds_api",
    }

    assert pipeline.command_ingest(clock.SAMPLES_DATE, from_samples=True) == 0
    counts = {
        source: connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        for source, table in tables.items()
    }

    # The replay plans no forecast (no sample venue hosts a match in its
    # horizon), so weather is 0 = 0 here and has a test of its own below.
    assert counts["football-data.org (sample)"] and counts["openstreetmap.org"]
    assert counts["the-odds-api.com (sample)"]
    assert {source: len(objects_of(bucket, source)) for source in tables} == counts
    # The rerun replays the same answers: same rows, same objects, nothing added.
    assert pipeline.command_ingest(clock.SAMPLES_DATE, from_samples=True) == 0
    assert {source: len(objects_of(bucket, source)) for source in tables} == counts
    assert len(bucket.objects) == sum(counts.values())


@pytest.mark.postgres
def test_a_weather_object_has_the_rows_key_hash_and_parameters_and_a_rerun_overwrites_it(
    connection, run_id
):
    from deng.sources import open_meteo

    zone = gcs_module.GcsRawZone(FakeBucket())
    request = open_meteo.ForecastRequest(546, 39.94, -0.10, date(2026, 9, 23), date(2026, 9, 24))
    payload = {"hourly": {"time": [], "temperature_2m": []}}
    for day in (date(2026, 9, 21), date(2026, 9, 21), date(2026, 9, 22)):
        open_meteo.store(
            connection, request, "https://example.test/forecast", payload, day, run_id, zone
        )

    rows = connection.execute(
        "SELECT venue_team_id, ingestion_date, payload_hash, request_params FROM raw.open_meteo"
    ).fetchall()
    assert len(rows) == len(zone.bucket.objects) == 2  # the rerun of the 21st overwrote
    venue, day, payload_hash, params = rows[0]
    body = zone.bucket.body(
        object_name(open_meteo.SOURCE, open_meteo.ENDPOINT, {"venue_team_id": venue}, day)
    )
    assert body["payload_hash"] == payload_hash
    assert body["key"] == {"venue_team_id": venue}
    assert body["request_params"] == params


@pytest.mark.postgres
def test_every_odds_fetch_is_its_own_object_and_a_replayed_one_overwrites_itself(
    connection, run_id
):
    from deng.sources import the_odds_api

    zone = gcs_module.GcsRawZone(FakeBucket())
    request = the_odds_api.OddsRequest(sport="soccer_uefa_champs_league", regions="eu")
    morning = datetime(2026, 11, 17, 7, 0, tzinfo=timezone.utc)
    noon = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)

    for fetched_at in (morning, noon, noon):
        the_odds_api.store(
            connection, request, "https://example.test/odds", [], run_id, fetched_at, mirror=zone
        )

    rows = connection.execute("SELECT count(*) FROM raw.odds_api").fetchone()[0]
    assert rows == len(zone.bucket.objects) == 2
    body = zone.bucket.body(next(iter(zone.bucket.objects)))
    assert set(body["attributes"]) == {"requests_remaining", "requests_used", "requests_last"}
    assert body["payload"] == [] and body["record_count"] == 0
