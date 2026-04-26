"""User profile — where to find the farm.

Stored under ~/.config/farm-cli/profile.yml. Env vars FARM_URL / FARM_TOKEN
override the file. The file is created on `farm-cli login`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

DEFAULT_PATH = Path.home() / ".config" / "farm-cli" / "profile.yml"


@dataclass(slots=True)
class Profile:
    url: str
    token: str

    @property
    def ws_url(self) -> str:
        if self.url.startswith("https://"):
            return "wss://" + self.url[len("https://") :]
        if self.url.startswith("http://"):
            return "ws://" + self.url[len("http://") :]
        return self.url


def load(path: Path = DEFAULT_PATH) -> Profile:
    url = os.environ.get("FARM_URL")
    token = os.environ.get("FARM_TOKEN")

    if (not url or not token) and path.exists():
        data = yaml.safe_load(path.read_text()) or {}
        url = url or data.get("url")
        token = token or data.get("token")

    if not url or not token:
        raise SystemExit(
            "No farm credentials. Run `farm-cli login URL --token TOKEN` "
            "or set FARM_URL and FARM_TOKEN env vars."
        )
    return Profile(url=url.rstrip("/"), token=token)


def save(profile: Profile, path: Path = DEFAULT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump({"url": profile.url, "token": profile.token}, sort_keys=False)
    )
    path.chmod(0o600)
