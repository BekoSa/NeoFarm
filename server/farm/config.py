"""Runtime configuration.

Two layers:

* `Settings` (env vars) — immutable per-process: DB/Redis/auth.
* `FarmConfig` (config.yml) — hot-reloadable: regex, TTL, jury protocol.
  The YAML is read on startup and re-read on PUT /api/config; consumers
  always go through `get_config()` so a swap is atomic.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Static, env-driven settings."""

    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_db: str = "farm"
    postgres_user: str = "farm"
    postgres_password: str = "farm"
    postgres_pool_size: int = 10
    postgres_max_overflow: int = 20

    redis_host: str = "redis"
    redis_port: int = 6379

    farm_api_token: str = "change-me-please"
    farm_host: str = "0.0.0.0"
    farm_port: int = 5000
    farm_config: str = "/app/config.yml"
    farm_cors_origins: str = "*"
    farm_role: str = "api"

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/0"

    @property
    def cors_origins(self) -> list[str]:
        raw = self.farm_cors_origins.strip()
        if raw in ("", "*"):
            return ["*"]
        return [o.strip() for o in raw.split(",") if o.strip()]


class TeamConfig(BaseModel):
    alias: str
    ip: str


class SubmitterConfig(BaseModel):
    period: float = 5.0
    idle_period: float = 0.5
    batch_size: int = 100


class FarmConfig(BaseModel):
    """The hot-reloadable, YAML-backed configuration."""

    flag_format: str = r"[A-Z0-9]{31}="
    flag_lifetime: int = Field(900, ge=10)
    round_length: int = Field(60, ge=1)
    protocol: str = "dummy"
    protocols: dict[str, dict[str, Any]] = Field(default_factory=dict)
    submitter: SubmitterConfig = Field(default_factory=SubmitterConfig)
    teams: list[TeamConfig] = Field(default_factory=list)

    @field_validator("flag_format")
    @classmethod
    def _validate_regex(cls, value: str) -> str:
        import re

        re.compile(value)  # raises if invalid
        return value


_lock = threading.Lock()
_settings: Settings | None = None
_config: FarmConfig | None = None
_config_path: Path | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def _load_yaml(path: Path) -> FarmConfig:
    if not path.exists():
        return FarmConfig()
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return FarmConfig.model_validate(data)


def get_config() -> FarmConfig:
    """Return the active farm config. Loads on first call."""
    global _config, _config_path
    if _config is None:
        with _lock:
            if _config is None:
                _config_path = Path(get_settings().farm_config)
                _config = _load_yaml(_config_path)
    return _config


def reload_config() -> FarmConfig:
    """Re-read the YAML from disk and return the new value."""
    global _config, _config_path
    with _lock:
        _config_path = Path(get_settings().farm_config)
        _config = _load_yaml(_config_path)
        return _config


def replace_config(new_cfg: FarmConfig, *, persist: bool = True) -> FarmConfig:
    """Replace the in-memory config and (optionally) write it back to disk."""
    global _config, _config_path
    with _lock:
        _config = new_cfg
        if persist:
            _config_path = _config_path or Path(get_settings().farm_config)
            _config_path.parent.mkdir(parents=True, exist_ok=True)
            with _config_path.open("w", encoding="utf-8") as fh:
                yaml.safe_dump(
                    new_cfg.model_dump(mode="python"),
                    fh,
                    sort_keys=False,
                    allow_unicode=True,
                )
        return _config


def team_alias_for_ip(ip: str) -> str | None:
    for team in get_config().teams:
        if team.ip == ip:
            return team.alias
    return None
