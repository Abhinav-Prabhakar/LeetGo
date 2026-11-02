"""Configuration validation tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from leetgo.config import Settings


def test_settings_defaults() -> None:
    settings = Settings(bot_token="test-token", _env_file=None)
    assert settings.token == "test-token"
    assert settings.database_path.name == "leetgo.db"
    assert settings.default_timezone == "UTC"
    assert settings.environment == "production"
    assert settings.guild_id is None


def test_empty_token_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(bot_token="   ", _env_file=None)


def test_invalid_timezone_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(bot_token="test-token", default_timezone="Nowhere/City", _env_file=None)


def test_empty_optional_values_become_none() -> None:
    settings = Settings(bot_token="test-token", log_file="", guild_id="", _env_file=None)
    assert settings.log_file is None
    assert settings.guild_id is None


def test_log_level_normalised() -> None:
    settings = Settings(bot_token="test-token", log_level="debug", _env_file=None)
    assert settings.log_level == "DEBUG"
    with pytest.raises(ValidationError):
        Settings(bot_token="test-token", log_level="verbose", _env_file=None)


def test_health_port_bounds() -> None:
    with pytest.raises(ValidationError):
        Settings(bot_token="test-token", health_port=70000, _env_file=None)
