"""HTTP client for the farm API."""

from __future__ import annotations

from typing import Any

import httpx

from .profile import Profile


class FarmClient:
    def __init__(self, profile: Profile, timeout: float = 10.0) -> None:
        self.profile = profile
        self._client = httpx.AsyncClient(
            base_url=profile.url,
            headers={"X-Farm-Token": profile.token},
            timeout=timeout,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "FarmClient":
        return self

    async def __aexit__(self, *_) -> None:
        await self.close()

    async def health(self) -> dict[str, Any]:
        r = await self._client.get("/health")
        r.raise_for_status()
        return r.json()

    async def get_config(self) -> dict[str, Any]:
        r = await self._client.get("/api/config")
        r.raise_for_status()
        return r.json()

    async def list_teams(self) -> list[dict[str, Any]]:
        r = await self._client.get("/api/teams")
        r.raise_for_status()
        return r.json()

    async def register_exploit(
        self,
        name: str,
        *,
        host: str | None = None,
        notes: str | None = None,
        enabled: bool = True,
    ) -> dict[str, Any]:
        r = await self._client.post(
            "/api/exploits",
            json={"name": name, "host": host, "notes": notes, "enabled": enabled},
        )
        r.raise_for_status()
        return r.json()

    async def report_run(
        self,
        *,
        sploit: str,
        team: str | None,
        target_ip: str | None,
        host: str | None,
        flags_found: int,
        duration_ms: int | None,
        exit_code: int | None,
        stdout_tail: str | None,
        stderr_tail: str | None,
    ) -> None:
        r = await self._client.post(
            "/api/runs",
            json={
                "sploit": sploit,
                "team": team,
                "target_ip": target_ip,
                "host": host,
                "flags_found": flags_found,
                "duration_ms": duration_ms,
                "exit_code": exit_code,
                "stdout_tail": stdout_tail,
                "stderr_tail": stderr_tail,
            },
        )
        r.raise_for_status()

    async def submit_flags(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        r = await self._client.post("/api/flags", json={"items": items})
        r.raise_for_status()
        return r.json()

    async def submit_manual(
        self, text: str, *, sploit: str | None = "manual", team: str | None = None
    ) -> dict[str, Any]:
        r = await self._client.post(
            "/api/flags/manual",
            json={"text": text, "sploit": sploit, "team": team},
        )
        r.raise_for_status()
        return r.json()
