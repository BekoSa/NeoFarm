"""FaustCTF protocol.

Faust uses a line-oriented TCP submission server: connect, send one flag
per line, read one ack line per flag. The classic header lines ("Welcome
to FaustCTF flag submission service") are skipped.
"""

from __future__ import annotations

import asyncio
import logging

from .base import BaseProtocol, FlagVerdict, SubmissionResult

log = logging.getLogger(__name__)


class FaustCTFProtocol(BaseProtocol):
    display_name = "FaustCTF"

    def __init__(
        self,
        host: str,
        port: int,
        team_token: str = "",
        timeout: float = 10.0,
        **kwargs,
    ) -> None:
        super().__init__(host=host, port=port, team_token=team_token, **kwargs)
        self.host = host
        self.port = int(port)
        self.token = team_token
        self.timeout = timeout

    async def submit(self, flags: list[str]) -> list[SubmissionResult]:
        if not flags:
            return []

        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port), timeout=self.timeout
            )
        except (OSError, asyncio.TimeoutError) as exc:
            log.warning("faust connect failed: %s", exc)
            return [
                SubmissionResult(flag=f, verdict=FlagVerdict.ERROR, response=str(exc))
                for f in flags
            ]

        try:
            # Skip greeting lines until a blank line.
            while True:
                line = await asyncio.wait_for(reader.readline(), timeout=self.timeout)
                if not line or line.strip() == b"":
                    break

            if self.token:
                writer.write(f"{self.token}\n".encode())
                await writer.drain()

            results: list[SubmissionResult] = []
            for f in flags:
                writer.write(f"{f}\n".encode())
                await writer.drain()
                line = await asyncio.wait_for(reader.readline(), timeout=self.timeout)
                msg = line.decode("utf-8", "replace").strip()
                low = msg.lower()
                if "ok" in low or "accepted" in low:
                    verdict = FlagVerdict.ACCEPTED
                elif "err" in low or "invalid" in low or "denied" in low or "old" in low or "own" in low:
                    verdict = FlagVerdict.REJECTED
                else:
                    verdict = FlagVerdict.REJECTED
                results.append(SubmissionResult(flag=f, verdict=verdict, response=msg))
            return results
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
