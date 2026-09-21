"""Central configuration loaded from environment variables / `.env`.

Why a single settings object?
    Every pipeline component (API clients, database loader, cloud writers)
    reads its configuration from the same validated place. Secrets never live
    in code; they come from the environment (see `.env.example`).
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for the pipeline.

    Values are read from environment variables first and from a `.env` file
    in the current working directory as a fallback. Unknown variables in the
    environment are ignored so the settings work inside Docker as well.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- football-data.org -------------------------------------------------
    football_data_api_key: SecretStr = Field(default=SecretStr(""))
    football_data_base_url: str = "https://api.football-data.org/v4"
    football_data_competition: str = "CL"

    # --- Open-Meteo --------------------------------------------------------
    open_meteo_forecast_url: str = "https://api.open-meteo.com/v1/forecast"
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
    ingest_source: Literal["api", "samples"] = "api"
    local_raw_dir: Path = Path("data/raw")
    log_level: str = "INFO"

    # --- Google Cloud (final milestone) ------------------------------------
    gcp_project_id: str = ""
    gcp_region: str = "europe-west6"
    gcs_raw_bucket: str = ""
    bigquery_dataset: str = "cl_intelligence"

    @property
    def postgres_dsn(self) -> str:
        """Return a libpq-style connection string for PostgreSQL."""
        password = self.postgres_password.get_secret_value()
        return (
            f"postgresql://{self.postgres_user}:{password}"
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
    """Build a fresh `Settings` instance (kept as a function so tests can override env vars)."""
    return Settings()
