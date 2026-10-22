"""Shared fixtures.

Integration tests need a PostgreSQL. They skip automatically when none is
reachable, so `make test` stays green on a machine without Docker; `make
test-integration` runs them against the Compose stack. They run in their own
database, `<POSTGRES_DB>_test`, created on first use: they empty the pipeline
tables, and the database `make run-samples` fills must keep its data.
"""

import json
import os
import uuid
from datetime import date
from pathlib import Path

import pytest

SAMPLE_DIR = Path(__file__).resolve().parents[1] / "data" / "sample" / "football-data"
TEST_DATABASE_SUFFIX = "_test"


def use_a_separate_test_database() -> None:
    """Point every connection of this test session at `<POSTGRES_DB>_test`.

    The integration tests TRUNCATE raw, staging and curated. Against the
    pipeline's own database that would cost the ingested seasons and the odds
    credits already spent. An environment variable beats `.env` (config.py), so
    this one setting redirects the fixtures, the CLI and the Dagster assets alike.
    """
    from deng.config import get_settings

    name = get_settings().postgres_db
    if not name.endswith(TEST_DATABASE_SUFFIX):
        os.environ["POSTGRES_DB"] = name + TEST_DATABASE_SUFFIX


def create_test_database_if_missing(dsn: str) -> None:
    """Create the test database on the same server, connecting via `postgres`."""
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    name = conninfo_to_dict(dsn)["dbname"]
    with psycopg.connect(
        make_conninfo(dsn, dbname="postgres"), connect_timeout=3, autocommit=True
    ) as conn:
        if conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone():
            return
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))


def postgres_unavailable_reason() -> str | None:
    """None when the test database is reachable, otherwise why it is not."""
    try:
        import psycopg

        from deng.config import get_settings

        dsn = get_settings().postgres_dsn
        create_test_database_if_missing(dsn)
        with psycopg.connect(dsn, connect_timeout=3):
            return None
    except Exception as error:  # noqa: BLE001 - any failure means "not available"
        if getattr(error, "sqlstate", None) == "42501":  # insufficient_privilege
            name = os.environ.get("POSTGRES_DB")
            return f"cannot create the test database {name} - create it once, or grant CREATEDB"
        return "no PostgreSQL reachable - start it with `make up`"


def pytest_configure(config):
    """Register the marker and move the session onto the test database."""
    config.addinivalue_line(
        "markers", "postgres: needs a reachable PostgreSQL (started with `make up`)"
    )
    use_a_separate_test_database()


def pytest_collection_modifyitems(config, items):
    """Skip every test marked `postgres` when no database is reachable.

    Implemented as a hook rather than an importable constant on purpose: a test
    module that does `from tests.conftest import ...` only works when the
    repository root happens to be on sys.path, which is true for
    `python -m pytest` and false for a bare `pytest` - exactly the difference
    that made CI fail while local runs passed.
    """
    reason = postgres_unavailable_reason()
    if reason is None:
        return
    skip = pytest.mark.skip(reason=reason)
    for item in items:
        if "postgres" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
def connection():
    """An open connection to the test database, its pipeline tables emptied."""
    import psycopg

    from deng.config import get_settings
    from deng.database import apply_sql_files

    conn = psycopg.connect(get_settings().postgres_dsn)
    apply_sql_files(conn)
    # Each test starts from empty pipeline tables; the DDL itself stays. Staging
    # and curated too: a previous test's rows carry their own dates, which a
    # test about "newer data wins" must not inherit.
    with conn.cursor() as cursor:
        cursor.execute(
            "TRUNCATE raw.football_data, meta.dq_results, meta.pipeline_runs, "
            "staging.matches, staging.teams, staging.standings, "
            "curated.dim_team, curated.fact_match, curated.fact_team_match_form, "
            "raw.open_meteo, staging.weather_forecast, curated.dim_venue, "
            "curated.fact_match_weather, raw.odds_api, staging.bookmaker_odds, "
            "staging.odds_event_match, curated.fact_match_prediction, "
            "curated.fact_bookmaker_odds CASCADE"
        )
    conn.commit()
    yield conn
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
