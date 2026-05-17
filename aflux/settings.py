from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables and .env."""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="AFLUX_", extra="ignore")

    access_code: str = Field(min_length=8)
    token_secret: str = Field(min_length=32)
    token_expire_minutes: int = 1440
    scan_timeout_seconds: int = 120


@lru_cache
def get_settings() -> Settings:
    return Settings()
