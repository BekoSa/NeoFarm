"""Runtime configuration.

Two layers:

* `Settings` (env vars) — immutable per-process: DB/Redis/auth.
* `FarmConfig` (config.yml) — hot-reloadable: regex, TTL, jury protocol.
  Every process (API and workers) goes through `get_config()`, which
  re-reads the YAML whenever the file changes on disk — whether it was
  saved from the UI or edited by hand. A file that fails to parse or
  validate never replaces a config that is already loaded.
"""

from __future__ import annotations

import io
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator
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
    """Single team — explicit alias + IP."""

    model_config = ConfigDict(extra="forbid")

    alias: str
    ip: str


class TeamRange(BaseModel):
    """Compact form for declaring many teams at once.

    Templates use Python's str.format syntax. The integer team number is
    bound to ``{i}``; e.g. ``{i:02d}`` zero-pads to 2 digits.
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    from_: int = Field(alias="from", ge=0)
    to: int = Field(ge=0)
    alias: str = "team-{i}"
    ip: str = "10.60.{i}.2"

    @field_validator("to")
    @classmethod
    def _check_to(cls, v: int, info) -> int:
        lo = info.data.get("from_")
        if lo is not None and v < lo:
            raise ValueError(f"'to' ({v}) must be >= 'from' ({lo})")
        return v

    def expand(self) -> list[TeamConfig]:
        out: list[TeamConfig] = []
        for i in range(self.from_, self.to + 1):
            try:
                a = self.alias.format(i=i)
                ip = self.ip.format(i=i)
            except (KeyError, IndexError, ValueError) as e:
                raise ValueError(
                    f"team range template error at i={i}: {e}. "
                    "Use {i} or {i:02d}."
                ) from e
            out.append(TeamConfig(alias=a, ip=ip))
        return out


class SubmitterConfig(BaseModel):
    period: float = Field(5.0, gt=0)        # min seconds between two submissions
    idle_period: float = Field(0.5, gt=0)   # queue poll interval while it is empty
    batch_size: int = Field(100, ge=1)


class FarmConfig(BaseModel):
    """The hot-reloadable, YAML-backed configuration."""

    flag_format: str = r"[A-Z0-9]{31}="
    flag_lifetime: int = Field(900, ge=10)
    round_length: int = Field(60, ge=1)
    protocol: str = "dummy"
    protocols: dict[str, dict[str, Any]] = Field(default_factory=dict)
    submitter: SubmitterConfig = Field(default_factory=SubmitterConfig)
    teams: list[TeamRange | TeamConfig] = Field(default_factory=list)
    # Aliases or IPs that are never attacked: our own team, the NOP team.
    exclude_teams: list[str] = Field(default_factory=list)
    # Exploit run reports older than this many seconds are purged; 0 keeps all.
    runs_retention: int = Field(7200, ge=0)

    @field_validator("flag_format")
    @classmethod
    def _validate_regex(cls, value: str) -> str:
        import re

        re.compile(value)  # raises if invalid
        return value

    def expanded_teams(self) -> list[TeamConfig]:
        """Flatten ranges into concrete teams; later entries win on alias clash."""
        seen: dict[str, TeamConfig] = {}
        for item in self.teams:
            if isinstance(item, TeamRange):
                for t in item.expand():
                    seen[t.alias] = t
            else:
                seen[item.alias] = item
        return list(seen.values())

    def target_teams(self) -> list[TeamConfig]:
        """Teams to attack: everything except `exclude_teams`."""
        excluded = set(self.exclude_teams)
        return [
            t for t in self.expanded_teams()
            if t.alias not in excluded and t.ip not in excluded
        ]


log = logging.getLogger("farm.config")

# How often get_config() stats the file for changes.
_CHECK_INTERVAL = 1.0

_lock = threading.Lock()
_settings: Settings | None = None
_config: FarmConfig | None = None
# (mtime_ns, size) of the file `_config` was loaded from; size catches
# rewrites that land within the filesystem's mtime granularity.
_config_stamp: tuple[int, int] | None = None
_last_check = 0.0


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def config_path() -> Path:
    return Path(get_settings().farm_config)


def _stamp(path: Path) -> tuple[int, int] | None:
    try:
        st = path.stat()
    except FileNotFoundError:
        return None
    return st.st_mtime_ns, st.st_size


def _load_locked(*, force: bool) -> FarmConfig:
    """Load the YAML if it changed (or `force`). Caller holds `_lock`."""
    global _config, _config_stamp, _last_check
    path = config_path()
    stamp = _stamp(path)
    _last_check = time.monotonic()
    if _config is not None and not force and stamp == _config_stamp:
        return _config

    if stamp is None:
        if _config is None:
            log.warning("config %s not found; using built-in defaults", path)
            _config = FarmConfig()
        else:
            log.error("config %s disappeared; keeping the last good config", path)
        _config_stamp = None
        return _config

    try:
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        if not data and _config is not None:
            # Most likely caught mid-rewrite (truncated, not yet written).
            raise ValueError("file is empty")
        new = FarmConfig.model_validate(data or {})
    except Exception as exc:
        if _config is None:
            raise
        log.error("config %s is invalid, keeping the last good one: %s", path, exc)
        # Don't re-parse the same broken file on every call; any further
        # write changes the stamp and triggers another attempt.
        _config_stamp = stamp
        return _config

    if _config is not None:
        log.info("config reloaded from %s", path)
    _config = new
    _config_stamp = stamp
    return _config


def get_config() -> FarmConfig:
    """Return the active farm config, picking up on-disk changes."""
    if _config is not None and time.monotonic() - _last_check < _CHECK_INTERVAL:
        return _config
    with _lock:
        return _load_locked(force=False)


def reload_config() -> FarmConfig:
    """Re-read the YAML from disk now (e.g. on SIGHUP)."""
    with _lock:
        return _load_locked(force=True)


def _merge_into(dst: Any, src: dict[str, Any]) -> None:
    """Update a ruamel round-trip mapping in place so comments survive."""
    for key in [k for k in dst if k not in src]:
        del dst[key]
    for key, value in src.items():
        if isinstance(value, dict) and isinstance(dst.get(key), dict):
            _merge_into(dst[key], value)
        elif key not in dst or dst[key] != value:
            dst[key] = value


def _render_yaml(path: Path, data: dict[str, Any]) -> str:
    """Serialize `data`, keeping the comments/layout of the existing file."""
    from ruamel.yaml import YAML

    rt = YAML()
    rt.indent(mapping=2, sequence=4, offset=2)
    rt.width = 4096
    doc: Any = None
    try:
        doc = rt.load(path.read_text(encoding="utf-8"))
    except Exception:
        doc = None
    if isinstance(doc, dict):
        _merge_into(doc, data)
    else:
        doc = data
    buf = io.StringIO()
    rt.dump(doc, buf)
    return buf.getvalue()


def _write_file(path: Path, text: str) -> None:
    """Write atomically where possible.

    A single-file docker bind mount (our default) can't be renamed over
    (EBUSY), so fall back to one in-place write; readers protect
    themselves via the last-good-config logic in `_load_locked`.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
        return
    except OSError:
        tmp.unlink(missing_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())


def replace_config(new_cfg: FarmConfig, *, persist: bool = True) -> FarmConfig:
    """Replace the in-memory config and (optionally) write it back to disk."""
    global _config, _config_stamp, _last_check
    with _lock:
        if persist:
            path = config_path()
            data = new_cfg.model_dump(mode="json", by_alias=True)
            _write_file(path, _render_yaml(path, data))
            _config_stamp = _stamp(path)
            _last_check = time.monotonic()
        _config = new_cfg
        return _config
