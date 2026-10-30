"""Tests for the settings object (deng.config).

Claims defended: defaults work without any configuration, the environment
overrides them, the API key never shows up in a repr or log line, a missing
key produces an actionable message, and the connection URL survives
passwords with special characters.

Test names are written as statements of the behaviour they prove - the same
convention as in every test module of this repository.
"""

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


def test_dsn_survives_special_characters_in_the_password(clean_env, monkeypatch):
    from psycopg.conninfo import conninfo_to_dict

    monkeypatch.setenv("POSTGRES_PASSWORD", "p@ss:w/rd#1")
    parsed = conninfo_to_dict(Settings(_env_file=None).postgres_dsn)
    assert parsed["password"] == "p@ss:w/rd#1"
    assert parsed["host"] == "localhost"


def test_plural_competitions_normalize_deduplicate_and_override_singular(clean_env):
    settings = Settings(
        _env_file=None,
        football_data_competition="CL",
        football_data_competitions=" pl, BL1,pl, pd ",
    )
    assert settings.football_data_competition_list == ["PL", "BL1", "PD"]
    assert Settings(
        _env_file=None, football_data_competition="sa"
    ).football_data_competition_list == ["SA"]


@pytest.mark.parametrize("value", ["../CL", "CL?season=2024", "CL/teams", "C L", "123"])
def test_invalid_competition_codes_are_rejected(clean_env, value):
    with pytest.raises(ValueError, match="competition codes"):
        Settings(_env_file=None, football_data_competitions=value)


@pytest.mark.parametrize("value", ["202", "2023/24", "1849", "2999", "year"])
def test_invalid_season_start_years_are_rejected(clean_env, value):
    with pytest.raises(ValueError, match="FOOTBALL_DATA_SEASONS"):
        Settings(_env_file=None, football_data_seasons=value)


def test_seasons_are_deduplicated_and_optional_context_can_be_empty(clean_env):
    settings = Settings(
        _env_file=None, football_data_seasons="2023, 2024,2023", team_context_csv_path=""
    )
    assert settings.football_data_season_list == ["2023", "2024"]
    assert settings.team_context_csv_path is None


def test_odds_sports_deduplicate_and_reject_url_parameters(clean_env):
    config = Settings(_env_file=None, odds_api_sports="soccer_epl, soccer_epl,soccer_italy_serie_a")
    assert config.odds_api_sport_list == ["soccer_epl", "soccer_italy_serie_a"]
    assert Settings(_env_file=None).odds_api_sport_list == ["soccer_uefa_champs_league"]
    with pytest.raises(ValueError):
        Settings(_env_file=None, odds_api_sports="soccer_epl?apiKey=oops")
