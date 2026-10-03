"""ctf01d jury protocol.

Thin adapter for a ctf01d (sea5kg) attack-defence jury — the scoreboard used
by CyberSibir 2025 (image ``sea5kg/ctf01d:v0.5.5``).

The jury takes one flag per HTTP GET; there is no batch endpoint::

    GET http://{HOST}:{PORT}/flag?teamid={TEAM_ID}&flag={FLAG}

    200  accepted                                  -> ACCEPTED
    403  rejected (old / already accepted / not     -> REJECTED
         found; reason in the response body)
    *    400 / 5xx / network error / timeout       -> ERROR

This class only knows how to reach the jury and how to read its verdicts.
Batch size, submit cadence and re-submission of ERROR flags belong to the
submitter — ``submit()`` just pushes whatever batch it is handed and returns
one verdict per flag, in input order.

Config (``config.yml``) — only what a submission needs::

    protocols.ctf01d:
      url: "http://10.10.0.1:8080"   # or host: + port:
      team_id: 7                     # your team id from the scoreboard
      # timeout: 5.0                 # optional, per-request seconds
"""
from __future__ import annotations

import asyncio

import httpx

# Adjust to wherever the base classes live (e.g. `from . import ...` if they
# are in the package __init__ rather than a sibling base.py).
from .base import BaseProtocol, FlagVerdict, SubmissionResult


class Ctf01dProtocol(BaseProtocol):
    """Adapter for the ctf01d (sea5kg) attack-defence jury."""

    display_name = "ctf01d"

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)

        url = kwargs.get("url")
        if not url:
            host = kwargs.get("host")
            if not host:
                raise ValueError(
                    "ctf01d: set 'url' or 'host' under protocols.ctf01d in config.yml"
                )
            url = f"http://{host}:{kwargs.get('port', 8080)}"
        if "://" not in url:
            url = "http://" + url
        self._flag_url = url.rstrip("/") + "/flag"

        team_id = kwargs.get("team_id", kwargs.get("teamid"))
        if team_id in (None, ""):
            raise ValueError("ctf01d: 'team_id' is required (see the scoreboard)")
        self._team_id = str(team_id)

        self._timeout = float(kwargs.get("timeout", 5.0))

    async def submit(self, flags: list[str]) -> list[SubmissionResult]:
        if not flags:
            return []
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(self._timeout), follow_redirects=False
        ) as client:
            # Push exactly the batch we were given — its size is the submitter's
            # call. gather preserves order; a per-flag error stays per-flag.
            # (Swap for a sequential `for` loop if you want zero in-call fan-out.)
            return list(
                await asyncio.gather(*(self._submit_one(client, f) for f in flags))
            )

    async def _submit_one(
        self, client: httpx.AsyncClient, flag: str
    ) -> SubmissionResult:
        try:
            resp = await client.get(
                self._flag_url, params={"teamid": self._team_id, "flag": flag}
            )
        except httpx.HTTPError as exc:
            return SubmissionResult(flag, FlagVerdict.ERROR, f"request failed: {exc!r}")

        body = resp.text.strip()
        if resp.status_code == 200:
            return SubmissionResult(flag, FlagVerdict.ACCEPTED, body)
        if resp.status_code == 403:
            # terminal: old / already accepted / not found
            return SubmissionResult(flag, FlagVerdict.REJECTED, body)
        # 400 (usually a wrong team_id), 5xx, etc. -> let the submitter retry
        return SubmissionResult(
            flag, FlagVerdict.ERROR, f"HTTP {resp.status_code}: {body}"
        )