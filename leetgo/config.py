"""Validated application configuration."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables and ``.env``."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Discord -----------------------------------------------------------
    bot_token: SecretStr = Field(description="Discord bot token from the developer portal.")
    guild_id: int | None = Field(
        default=None,
        description="Sync slash commands to this guild instantly (development only).",
    )
    cohort_category: str = Field(default="Cohorts", min_length=1, max_length=100)

    # --- Storage -----------------------------------------------------------
    database_path: Path = Field(default=Path("data/leetgo.db"))
    default_timezone: str = Field(default="UTC")

    # --- LeetCode API ------------------------------------------------------
    leetcode_cache_ttl: int = Field(default=300, ge=0, le=3600)
    leetcode_timeout: float = Field(default=15.0, gt=0, le=60)
    leetcode_retries: int = Field(default=3, ge=1, le=5)

    # --- Behaviour ---------------------------------------------------------
    max_cohorts_per_guild: int = Field(default=50, ge=1, le=500)
    max_leaderboard_users: int = Field(default=50, ge=5, le=250)
    reminder_poll_seconds: int = Field(default=30, ge=10, le=300)

    # --- Observability -----------------------------------------------------
    log_level: str = Field(default="INFO")
    log_file: Path | None = Field(default=Path("logs/leetgo.log"))
    log_json: bool = False
    health_host: str = Field(default="0.0.0.0")
    health_port: int = Field(default=0, ge=0, le=65535)
    environment: Literal["development", "production"] = "production"

    @field_validator("bot_token")
    @classmethod
    def _token_must_not_be_empty(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("BOT_TOKEN is empty. Create a token in the Discord Developer Portal.")
        return value

    @field_validator("default_timezone")
    @classmethod
    def _timezone_must_exist(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"Unknown timezone: {value!r}") from exc
        return value

    @field_validator("log_level")
    @classmethod
    def _normalise_log_level(cls, value: str) -> str:
        level = value.upper()
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if level not in allowed:
            raise ValueError(f"LOG_LEVEL must be one of {sorted(allowed)}")
        return level

    @field_validator("log_file", "guild_id", mode="before")
    @classmethod
    def _empty_string_is_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @property
    def token(self) -> str:
        """Return the raw token for the Discord client."""
        return self.bot_token.get_secret_value()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached settings instance."""
    return Settings()  # type: ignore[call-arg]
