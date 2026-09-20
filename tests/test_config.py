import pytest

from deng.config import Settings


def test_defaults_are_sane(clean_env):
    settings = Settings(_env_file=None)
    assert settings.football_data_competition == "CL"
    assert settings.postgres_port == 5432
    assert settings.football_data_base_url.startswith("https://")


def test_environment_overrides_defaults(clean_env, monkeypatch):
    monkeypatch.setenv("POSTGRES_HOST", "db")
    monkeypatch.setenv("POSTGRES_PASSWORD", "s3cret")
    settings = Settings(_env_file=None)
    assert settings.postgres_host == "db"
    assert settings.postgres_dsn == "postgresql://deng:s3cret@db:5432/cl_intelligence"


def test_secret_is_not_leaked_in_repr(clean_env, monkeypatch):
    monkeypatch.setenv("FOOTBALL_DATA_API_KEY", "super-secret-key")
    settings = Settings(_env_file=None)
    assert "super-secret-key" not in repr(settings)
    assert settings.require_football_api_key() == "super-secret-key"


def test_missing_api_key_gives_actionable_error(clean_env):
    settings = Settings(_env_file=None)
    with pytest.raises(ValueError, match="FOOTBALL_DATA_API_KEY"):
        settings.require_football_api_key()
