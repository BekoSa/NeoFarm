"""AltayCTF HTTP jury protocol.

Flags are submitted as one JSON batch::

    POST http://10.80.80.10/api/v1/flags
    {"flags": ["alt_...", ...]}

The reply format isn't published, so the common shapes are understood:

* a list (bare, or under ``results``/``flags``/``data``) of per-flag items —
  objects carrying a ``flag`` field are matched by it, anything else
  only positionally and only when the list length equals the batch;
* an object keyed by flag (``{"alt_...": "accepted", ...}``);
* a single verdict (string or object) when the batch had one flag.

A flag the reply doesn't clearly cover gets ERROR, which the submitter
retries — guessing a verdict for it could silently lose the flag. Non-2xx
replies and transport failures are ERROR for the whole batch as well.

Config example::

    protocols.altayctf_http:
      url: "http://10.80.80.10"      # /api/v1/flags is appended if missing
      # timeout: 5.0
      # headers: {"X-Team-Token": "..."}   # if the jury wants auth
"""
from __future__ import annotations

import json
from typing import Any

import httpx

from ._altayctf import classify, describe
from .base import BaseProtocol, FlagVerdict, SubmissionResult

_LIST_KEYS = ("results", "flags", "data", "items")


class AltayCtfHttpProtocol(BaseProtocol):
    """Adapter for the AltayCTF HTTP flag submission endpoint."""

    display_name = "AltayCTF (HTTP)"

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)

        url = str(kwargs.get("url", "http://10.80.80.10"))
        if "://" not in url:
            url = "http://" + url
        url = url.rstrip("/")
        self._url = url if url.endswith("/api/v1/flags") else url + "/api/v1/flags"
        self._timeout = float(kwargs.get("timeout", 5.0))
        self._headers = {str(k): str(v) for k, v in (kwargs.get("headers") or {}).items()}

    async def submit(self, flags: list[str]) -> list[SubmissionResult]:
        if not flags:
            return []

        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout), follow_redirects=False
            ) as client:
                response = await client.post(
                    self._url, json={"flags": flags}, headers=self._headers
                )
        except httpx.HTTPError as exc:
            message = f"HTTP request failed: {exc!r}"
            return [SubmissionResult(flag, FlagVerdict.ERROR, message) for flag in flags]

        body = response.text.strip()
        if not 200 <= response.status_code < 300:
            message = f"HTTP {response.status_code}: {body[:500]}"
            return [SubmissionResult(flag, FlagVerdict.ERROR, message) for flag in flags]

        return parse_results(flags, body)


def parse_results(flags: list[str], body: str) -> list[SubmissionResult]:
    """Per-flag results in input order (see the module docstring)."""
    try:
        payload: Any = json.loads(body)
    except json.JSONDecodeError:
        payload = body  # plain-text reply

    by_flag = _match(flags, payload)
    out: list[SubmissionResult] = []
    for flag in flags:
        if flag in by_flag:
            item = by_flag[flag]
            out.append(SubmissionResult(flag, classify(item, flag), describe(item)))
        else:
            out.append(
                SubmissionResult(
                    flag, FlagVerdict.ERROR, f"no verdict for this flag in reply: {body[:500]}"
                )
            )
    return out


def _match(flags: list[str], payload: Any) -> dict[str, Any]:
    items: Any = payload
    if isinstance(payload, dict):
        listed = next(
            (payload[k] for k in _LIST_KEYS if isinstance(payload.get(k), list)), None
        )
        if listed is not None:
            items = listed
        elif any(flag in payload for flag in flags):
            return {flag: payload[flag] for flag in flags if flag in payload}

    if isinstance(items, list):
        keyed: dict[str, Any] = {}
        for item in items:
            if isinstance(item, dict) and isinstance(item.get("flag"), str):
                keyed[item["flag"]] = item
            elif isinstance(item, str):
                # e.g. "[alt_...] Accepted" — the reply echoes the flag.
                keyed.update((flag, item) for flag in flags if flag in item)
        if keyed:
            return keyed
        if len(items) == len(flags):
            return dict(zip(flags, items))
        return {}

    # One verdict for the whole reply: only unambiguous for a single flag.
    if len(flags) == 1:
        return {flags[0]: payload}
    return {}
