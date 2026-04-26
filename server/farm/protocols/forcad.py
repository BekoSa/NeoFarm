"""Forcad jury protocol.

Forcad accepts flags via HTTP, posting a JSON array of flag strings to
the configured `/flags` endpoint and authenticating the team via the
``X-Team-Token`` header. Per-flag verdicts come back as a JSON list with
``msg`` / ``flag`` / ``status`` fields.

Reference: https://github.com/pomo-mondreganto/ForcAD
"""

from __future__ import annotations

import logging
import re

import httpx

from .base import BaseProtocol, FlagVerdict, SubmissionResult

log = logging.getLogger(__name__)


# These come from Forcad's `flag_submitter` source.
_ACCEPT_KEYWORDS = ("accepted", "ok")
_DUPLICATE_KEYWORDS = ("already", "duplicate")
_INVALID_KEYWORDS = ("invalid", "no such", "own", "nop", "not in")


def _classify(msg: str) -> str:
    text = msg.lower()
    if any(k in text for k in _ACCEPT_KEYWORDS):
        return FlagVerdict.ACCEPTED
    if any(k in text for k in _DUPLICATE_KEYWORDS):
        # Forcad treats duplicates as "already submitted"; we map to REJECTED so
        # the UI shows them out-of-queue without a noisy ACCEPTED count.
        return FlagVerdict.REJECTED
    if any(k in text for k in _INVALID_KEYWORDS):
        return FlagVerdict.REJECTED
    return FlagVerdict.REJECTED


class ForcadProtocol(BaseProtocol):
    display_name = "Forcad"

    def __init__(
        self,
        url: str,
        team_token: str,
        timeout: float = 10.0,
        **kwargs,
    ) -> None:
        super().__init__(url=url, team_token=team_token, timeout=timeout, **kwargs)
        self.url = url
        self.token = team_token
        self.timeout = timeout

    async def submit(self, flags: list[str]) -> list[SubmissionResult]:
        if not flags:
            return []

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                resp = await client.put(
                    self.url,
                    json=flags,
                    headers={"X-Team-Token": self.token},
                )
            except httpx.HTTPError as exc:
                log.warning("forcad transport error: %s", exc)
                return [
                    SubmissionResult(flag=f, verdict=FlagVerdict.ERROR, response=str(exc))
                    for f in flags
                ]

        if resp.status_code >= 500:
            return [
                SubmissionResult(
                    flag=f,
                    verdict=FlagVerdict.ERROR,
                    response=f"http {resp.status_code}",
                )
                for f in flags
            ]

        try:
            payload = resp.json()
        except ValueError:
            payload = None

        results: dict[str, SubmissionResult] = {}
        if isinstance(payload, list):
            for item in payload:
                if not isinstance(item, dict):
                    continue
                flag = item.get("flag") or _flag_from_msg(item.get("msg", ""))
                if not flag:
                    continue
                msg = item.get("msg", "")
                verdict = _classify(msg)
                results[flag] = SubmissionResult(
                    flag=flag, verdict=verdict, response=msg
                )

        # Make sure we return one result per input flag, even if the jury was
        # terse and only listed accepted ones.
        out: list[SubmissionResult] = []
        for f in flags:
            if f in results:
                out.append(results[f])
            else:
                out.append(
                    SubmissionResult(
                        flag=f,
                        verdict=FlagVerdict.REJECTED if resp.status_code < 400 else FlagVerdict.ERROR,
                        response=f"no verdict in jury reply (http {resp.status_code})",
                    )
                )
        return out


_FLAG_IN_MSG = re.compile(r"[A-Z0-9]{31}=")


def _flag_from_msg(msg: str) -> str | None:
    m = _FLAG_IN_MSG.search(msg or "")
    return m.group(0) if m else None
