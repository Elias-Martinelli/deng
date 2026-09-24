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


@pytest.fixture
def connection():
    """An open connection to a test-isolated schema state."""
    import psycopg

    from deng.config import get_settings
    from deng.database import apply_sql_files

    conn = psycopg.connect(get_settings().postgres_dsn)
    apply_sql_files(conn)
    # Each test starts from empty pipeline tables; the DDL itself stays. Staging
    # and curated too: a `make run-samples` before `make test` stamps them with
    # today's date, which a test about "newer data wins" must not inherit.
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
