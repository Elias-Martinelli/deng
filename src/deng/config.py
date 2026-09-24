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
    # Past seasons to fetch once, comma-separated start years ("2023,2024").
    # Empty means "only the current season", which is what a daily run needs.
    # The training data for a model lives here: one season is one request.
    football_data_seasons: str = ""

    # --- Open-Meteo --------------------------------------------------------
    open_meteo_forecast_url: str = "https://api.open-meteo.com/v1/forecast"
    # Reserved for post-match weather actuals (backlog 2.7); not used yet.
    open_meteo_archive_url: str = "https://archive-api.open-meteo.com/v1/archive"

    # --- The Odds API (bookmaker odds, free tier) --------------------------
    # Optional: without a key the odds step skips itself and says so; nothing
    # else in the pipeline depends on it.
    odds_api_key: SecretStr = Field(default=SecretStr(""))
    odds_api_base_url: str = "https://api.the-odds-api.com/v4"
    odds_api_sport: str = "soccer_uefa_champs_league"
    # Bookmaker regions; one region x one market costs one credit per request.
    odds_api_regions: str = "eu"
    # Optional comma-separated bookmaker keys to narrow the answer (empty = all
    # bookmakers of the regions). Does not change the credit cost.
    odds_api_bookmakers: str = ""
    # How often the interval job may fetch while a watched match is close:
    # every 15 min for the last 48 h before kick-off. The daily run always
    # fetches once a day regardless. All three are documented in .env.example.
    odds_refresh_minutes: int = Field(default=15, ge=1)
    odds_watch_hours_before_kickoff: int = Field(default=48, ge=0)
    # Optional comma-separated match ids to watch; empty = every unfinished
    # match inside the window.
    odds_watch_match_ids: str = ""
    # Stop fetching when the API reports fewer credits than this (free tier:
    # 500 per month). The last stored state stays visible with its age.
    odds_quota_reserve: int = Field(default=50, ge=0)

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
    def football_data_season_list(self) -> list[str]:
        """The past seasons to fetch, as a clean list of start years."""
        return [part.strip() for part in self.football_data_seasons.split(",") if part.strip()]

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

    @property
    def odds_watch_match_id_set(self) -> frozenset[int]:
        """The watched match ids as integers; empty means "every match in the window"."""
        return frozenset(int(part) for part in self.odds_watch_match_ids.split(",") if part.strip())

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
