"""AltayCTF raw TCP jury protocol.

The jury accepts one flag per line at ``10.80.80.10:3333`` and answers each
with one line. A batch goes over a single connection, strictly
request/response (send a flag, read its reply), which works the same
whether the server keeps the connection open or closes it after every
flag — in the latter case we simply reconnect for the next one.

Whatever the server says right after connecting is drained and discarded,
so it is never mistaken for the first flag's verdict. The live jury greets
with two lines::

    Welcome from flag service, your team: <name>.
    Please send your flags.

The first connection waits up to ``greeting_timeout`` for that; if no
banner came, later reconnects in the same batch don't wait at all. As a
safety net against a banner slower than ``greeting_timeout``, a reply line
that reads as a greeting is skipped rather than classified.

Failure handling, so a dead jury can't stall the submitter for minutes:

* connection refused / connect timeout -> ERROR for every remaining flag;
* no reply within ``timeout`` -> ERROR for that flag, reconnect; after
  ``max_failures`` such failures in a row the rest of the batch is ERROR.

ERROR flags are retried by the submitter until they expire.

Config example::

    protocols.altayctf_tcp:
      host: "10.80.80.10"
      port: 3333
      # timeout: 5.0             # connect / per-reply seconds
      # greeting_timeout: 0.5    # how long to drain a banner after connect
      # max_failures: 3
"""
from __future__ import annotations

import asyncio
import contextlib
import re

from ._altayctf import classify_text
from .base import BaseProtocol, FlagVerdict, SubmissionResult


# After a banner line, keep draining until the server is quiet this long.
_BANNER_IDLE = 0.1

# Greeting lines the jury prints on connect, seen as:
#
#     Welcome from flag service, your team: <name>.
#     Please send your flags.
#
# The timed drain in _connect normally eats them, but it can miss one on a
# slow link, or on a reconnect after the first connect saw no banner. Such a
# line is never a verdict, so _exchange skips it by content as well.
_GREETING = re.compile(r"welcome|please\s+send|your\s+(?:team|flags)", re.I)


class _Disconnected(Exception):
    """The server closed the connection before replying."""


class AltayCtfTcpProtocol(BaseProtocol):
    """Adapter for the AltayCTF raw TCP flag submission endpoint."""

    display_name = "AltayCTF (TCP)"

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._host = str(kwargs.get("host", "10.80.80.10"))
        self._port = int(kwargs.get("port", 3333))
        self._timeout = float(kwargs.get("timeout", 5.0))
        self._greeting_timeout = float(kwargs.get("greeting_timeout", 0.5))
        self._max_failures = max(1, int(kwargs.get("max_failures", 3)))
        self._has_banner: bool | None = None  # learned on the first connect

    async def submit(self, flags: list[str]) -> list[SubmissionResult]:
        results: list[SubmissionResult] = []
        conn: tuple[asyncio.StreamReader, asyncio.StreamWriter] | None = None
        failures = 0
        try:
            for i, flag in enumerate(flags):
                if conn is None:
                    try:
                        conn = await self._connect()
                    except (OSError, asyncio.TimeoutError) as exc:
                        message = f"cannot connect to {self._host}:{self._port}: {exc!r}"
                        results += [
                            SubmissionResult(f, FlagVerdict.ERROR, message) for f in flags[i:]
                        ]
                        break
                try:
                    reply = await self._exchange(*conn, flag)
                except _Disconnected:
                    # The server may close after each answer; retry this
                    # flag once on a fresh connection.
                    await _close(conn[1])
                    conn = None
                    try:
                        conn = await self._connect()
                        reply = await self._exchange(*conn, flag)
                    except (OSError, asyncio.TimeoutError, _Disconnected) as exc:
                        reply = None
                        error = f"no reply: {exc!r}"
                except (OSError, asyncio.TimeoutError) as exc:
                    reply = None
                    error = f"no reply: {exc!r}"

                if reply is None:
                    results.append(SubmissionResult(flag, FlagVerdict.ERROR, error))
                    if conn is not None:
                        await _close(conn[1])
                        conn = None
                    failures += 1
                    if failures >= self._max_failures:
                        message = f"giving up after {failures} failed replies in a row"
                        results += [
                            SubmissionResult(f, FlagVerdict.ERROR, message)
                            for f in flags[i + 1 :]
                        ]
                        break
                    continue

                failures = 0
                results.append(SubmissionResult(flag, classify_text(reply, flag), reply))
        finally:
            if conn is not None:
                await _close(conn[1])
        return results

    async def _connect(self) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(self._host, self._port), timeout=self._timeout
        )
        if self._has_banner is False:
            return reader, writer
        # Drain a banner, if any, so it isn't read as the first verdict:
        # wait for its first line, then until the server goes quiet.
        got_banner = False
        wait = self._greeting_timeout
        while True:
            try:
                line = await asyncio.wait_for(reader.readline(), timeout=wait)
            except asyncio.TimeoutError:
                break
            if not line:
                break
            got_banner = True
            wait = _BANNER_IDLE
        if self._has_banner is None:
            self._has_banner = got_banner
        return reader, writer

    async def _exchange(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, flag: str
    ) -> str:
        if reader.at_eof():
            raise _Disconnected("closed by server")
        try:
            writer.write(flag.encode() + b"\n")
            await asyncio.wait_for(writer.drain(), timeout=self._timeout)
            while True:
                line = await asyncio.wait_for(reader.readline(), timeout=self._timeout)
                if not line:
                    raise _Disconnected("closed by server")
                reply = line.decode("utf-8", errors="replace").strip()
                if not reply or _GREETING.search(reply):
                    continue  # blank separator or a leaked greeting line
                return reply
        except (ConnectionResetError, BrokenPipeError) as exc:
            raise _Disconnected(repr(exc)) from exc


async def _close(writer: asyncio.StreamWriter) -> None:
    writer.close()
    with contextlib.suppress(Exception):
        await asyncio.wait_for(writer.wait_closed(), timeout=1.0)
