"""Central configuration loaded from environment variables / `.env`.

Why a single settings object?
    Every pipeline component (API clients, database loader, cloud writers)
    reads its configuration from the same validated place. Secrets never live
    in code; they come from the environment (see `.env.example`).
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal
from urllib.parse import quote

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for the pipeline.

    Values are read from environment variables first and from a `.env` file
    in the current working directory as a fallback. Unknown variables in the
    environment are ignored so the settings work inside Docker as well.
    """

    # Precedence: a real environment variable beats `.env`. That is what lets
    # Docker Compose set POSTGRES_HOST=postgres for the containers while the
    # same `.env` says localhost for the host. extra="ignore": the environment
    # holds many unrelated variables (PATH, HOME, ...), which must not fail
    # validation.
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- football-data.org -------------------------------------------------
    # SecretStr instead of str: printing or logging the settings shows
    # '**********', so the key cannot leak into a log file or a traceback by
    # accident. The value is only unwrapped where it is sent (get_secret_value).
    football_data_api_key: SecretStr = Field(default=SecretStr(""))
    football_data_base_url: str = "https://api.football-data.org/v4"
    football_data_competition: str = "CL"

    # --- Open-Meteo --------------------------------------------------------
    open_meteo_forecast_url: str = "https://api.open-meteo.com/v1/forecast"
    # Reserved for post-match weather actuals (backlog 2.7); not used yet.
    open_meteo_archive_url: str = "https://archive-api.open-meteo.com/v1/archive"

    # --- PostgreSQL --------------------------------------------------------
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "cl_intelligence"
    postgres_user: str = "deng"
    postgres_password: SecretStr = Field(default=SecretStr(""))

    # --- Pipeline behaviour ------------------------------------------------
    # Where the orchestrated ingestion reads from. "samples" replays the
    # committed payloads, so a reviewer without an API key can run schedules and
    # backfills end to end. The CLI keeps its explicit `--from-samples` flag.
    # Literal: any other value fails at start-up with a clear validation error
    # instead of silently behaving like "api".
    ingest_source: Literal["api", "samples"] = "api"
    # Reserved for a local file cache of raw payloads; the raw zone is the
    # database today, so nothing writes here yet.
    local_raw_dir: Path = Path("data/raw")
    log_level: str = "INFO"

    # --- Google Cloud (final milestone) ------------------------------------
    # Declared now so .env.example documents them from the start; read by the
    # cloud path in the final milestone. europe-west6 is Zurich: data stays in
    # Switzerland and latency from HSLU is lowest.
    gcp_project_id: str = ""
    gcp_region: str = "europe-west6"
    gcs_raw_bucket: str = ""
    bigquery_dataset: str = "cl_intelligence"

    @property
    def postgres_dsn(self) -> str:
        """Return a libpq-style connection string for PostgreSQL.

        User and password are percent-encoded: a password containing @, / or :
        would otherwise be read as part of the host or path of the URL.
        """
        user = quote(self.postgres_user, safe="")
        password = quote(self.postgres_password.get_secret_value(), safe="")
        return (
            f"postgresql://{user}:{password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    def require_football_api_key(self) -> str:
        """Return the football-data.org key or fail with an actionable message."""
        key = self.football_data_api_key.get_secret_value()
        if not key:
            raise ValueError(
                "FOOTBALL_DATA_API_KEY is not set. Copy .env.example to .env and add your key "
                "(free registration: https://www.football-data.org/client/register)."
            )
        return key


def get_settings() -> Settings:
    """Build a fresh `Settings` instance (kept as a function so tests can override env vars).

    Deliberately not cached: reading a few environment variables costs
    microseconds, and a cached object would ignore `monkeypatch.setenv` in tests
    and INGEST_SOURCE changes between Dagster runs.
    """
    return Settings()
