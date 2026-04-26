"""RuCTF jury protocol — POST one flag per request, plain text reply."""

from __future__ import annotations

import asyncio
import logging

import httpx

from .base import BaseProtocol, FlagVerdict, SubmissionResult

log = logging.getLogger(__name__)


class RuCTFProtocol(BaseProtocol):
    display_name = "RuCTF"

    def __init__(
        self,
        url: str,
        team_token: str = "",
        timeout: float = 10.0,
        concurrency: int = 5,
        **kwargs,
    ) -> None:
        super().__init__(url=url, team_token=team_token, timeout=timeout, **kwargs)
        self.url = url
        self.token = team_token
        self.timeout = timeout
        self.concurrency = max(1, int(concurrency))

    async def submit(self, flags: list[str]) -> list[SubmissionResult]:
        if not flags:
            return []
        sem = asyncio.Semaphore(self.concurrency)

        async with httpx.AsyncClient(timeout=self.timeout) as client:

            async def one(flag: str) -> SubmissionResult:
                headers = {"X-Team-Token": self.token} if self.token else {}
                async with sem:
                    try:
                        resp = await client.post(self.url, content=flag, headers=headers)
                    except httpx.HTTPError as exc:
                        return SubmissionResult(
                            flag=flag, verdict=FlagVerdict.ERROR, response=str(exc)
                        )
                msg = (resp.text or "").strip()
                low = msg.lower()
                if "accepted" in low or "captured" in low:
                    return SubmissionResult(flag=flag, verdict=FlagVerdict.ACCEPTED, response=msg)
                return SubmissionResult(flag=flag, verdict=FlagVerdict.REJECTED, response=msg)

            return await asyncio.gather(*(one(f) for f in flags))
