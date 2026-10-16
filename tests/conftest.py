"""Shared fixtures.

Integration tests need a PostgreSQL. They skip automatically when none is
reachable, so `make test` stays green on a machine without Docker; `make
test-integration` runs them against the Compose stack.
"""

import json
import os
import uuid
from datetime import date
from pathlib import Path

import pytest

SAMPLE_DIR = Path(__file__).resolve().parents[1] / "data" / "sample" / "football-data"


def postgres_available() -> bool:
    """Return True when a PostgreSQL matching the environment can be reached."""
    try:
        import psycopg

        from deng.config import get_settings

        with psycopg.connect(get_settings().postgres_dsn, connect_timeout=3):
            return True
    except Exception:  # noqa: BLE001 - any failure means "not available"
        return False


def pytest_configure(config):
    """Register the marker so `-m postgres` works and pytest does not warn."""
    config.addinivalue_line(
        "markers", "postgres: needs a reachable PostgreSQL (started with `make up`)"
    )


def pytest_collection_modifyitems(config, items):
    """Skip every test marked `postgres` when no database is reachable.

    Implemented as a hook rather than an importable constant on purpose: a test
    module that does `from tests.conftest import ...` only works when the
    repository root happens to be on sys.path, which is true for
    `python -m pytest` and false for a bare `pytest` - exactly the difference
    that made CI fail while local runs passed.
    """
    if postgres_available():
        return
    skip = pytest.mark.skip(reason="no PostgreSQL reachable - start it with `make up`")
    for item in items:
        if "postgres" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def isolated_database():
    """Create a disposable database; never truncate the configured warehouse."""
    import psycopg
    from psycopg import sql

    from deng.config import get_settings

    settings = get_settings()
    database = "deng_test_" + uuid.uuid4().hex
    try:
        admin = psycopg.connect(settings.postgres_dsn, autocommit=True)
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
    except psycopg.Error as exc:
        pytest.fail(
            "Integration tests require CREATEDB permission to create an isolated database. "
            "The configured warehouse has not been modified. "
            f"Database error type: {type(exc).__name__}"
        )
    try:
        yield database
    finally:
        # Only the exact random name created by this fixture may be removed.
        admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database)))
        admin.close()


@pytest.fixture
def connection(isolated_database, monkeypatch):
    """An open connection to empty tables in the disposable test database."""
    import psycopg
    from psycopg import sql

    from deng.config import get_settings
    from deng.database import apply_sql_files

    monkeypatch.setenv("POSTGRES_DB", isolated_database)
    monkeypatch.setenv("FOOTBALL_DATA_COMPETITIONS", "CL")
    monkeypatch.setenv("TEAM_CONTEXT_CSV_PATH", "")
    monkeypatch.setenv("FOOTBALL_DATA_TEAM_DETAILS", "false")
    conn = psycopg.connect(get_settings().postgres_dsn)
    apply_sql_files(conn)
    tables = conn.execute(
        "SELECT schemaname, tablename FROM pg_tables "
        "WHERE schemaname IN ('raw', 'staging', 'curated', 'meta')"
    ).fetchall()
    if tables:
        conn.execute(
            sql.SQL("TRUNCATE {} CASCADE").format(
                sql.SQL(", ").join(sql.Identifier(schema, table) for schema, table in tables)
            )
        )
    conn.commit()
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def sample_payload() -> dict:
    """A real committed API payload (the full season fixture list)."""
    if not (SAMPLE_DIR / "matches_all.json").exists():
        pytest.skip("API samples not present - run `make explore`")
    return json.loads((SAMPLE_DIR / "matches_all.json").read_text())


@pytest.fixture
def all_samples() -> dict:
    """Every committed payload, keyed by the endpoint it came from."""
    mapping = {
        "competitions/CL": "competition.json",
        "competitions/CL/teams": "teams.json",
        "competitions/CL/standings": "standings.json",
        "competitions/CL/matches": "matches_all.json",
    }
    payloads = {}
    for endpoint, filename in mapping.items():
        path = SAMPLE_DIR / filename
        if not path.exists():
            pytest.skip(f"sample {filename} missing - run `make explore`")
        payloads[endpoint] = json.loads(path.read_text())
    return payloads


@pytest.fixture
def run_id(connection) -> uuid.UUID:
    """A committed pipeline run that raw rows can reference."""
    new_id = uuid.uuid4()
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO meta.pipeline_runs (run_id, pipeline_name, logical_date, status)
            VALUES (%s, 'test', %s, 'RUNNING')
            """,
            (new_id, date(2026, 9, 20)),
        )
    connection.commit()
    return new_id


@pytest.fixture(autouse=True)
def _quiet_logging(monkeypatch):
    """Keep test output readable."""
    monkeypatch.setenv("LOG_LEVEL", os.environ.get("LOG_LEVEL", "WARNING"))


# Prefixes of every environment variable the settings object reads.
SETTINGS_ENV_PREFIXES = (
    "POSTGRES_",
    "FOOTBALL_DATA_",
    "OPEN_METEO_",
    "GCP_",
    "GCS_",
    "BIGQUERY_",
    "LOCAL_RAW_",
    "ODDS_",
)


@pytest.fixture
def clean_env(monkeypatch):
    """Remove every settings variable from the environment.

    Unit tests must assert our *defaults*, which is impossible if the developer
    (or CI, or a Compose shell) happens to export POSTGRES_PORT. Without this a
    reviewer would see a failure that says nothing about our code.
    """
    for name in list(os.environ):
        if name.startswith(SETTINGS_ENV_PREFIXES):
            monkeypatch.delenv(name, raising=False)
