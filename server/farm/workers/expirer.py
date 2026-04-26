"""Expirer — moves stale queued flags to EXPIRED.

A flag is stale when it was captured more than `flag_lifetime` seconds ago
and is still QUEUED/PENDING. Submitting an expired flag is pointless: most
juries will reject it and we burn rate-limit slots that could go to fresh
flags instead.
"""

from __future__ import annotations

import asyncio
import logging
import signal
from datetime import UTC, datetime, timedelta

from sqlalchemy import update

from ..config import get_config, reload_config
from ..db import init_db, session_scope
from ..models import Flag, FlagStatus

log = logging.getLogger("farm.expirer")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")


async def _expire_once() -> int:
    cfg = get_config()
    cutoff = datetime.now(UTC) - timedelta(seconds=cfg.flag_lifetime)
    async with session_scope() as sess:
        result = await sess.execute(
            update(Flag)
            .where(
                Flag.status.in_([FlagStatus.QUEUED, FlagStatus.PENDING]),
                Flag.captured_at < cutoff,
            )
            .values(status=FlagStatus.EXPIRED)
            .returning(Flag.id)
        )
        return len(result.fetchall())


async def main() -> None:
    reload_config()
    await init_db()
    stop = asyncio.Event()

    def _stop(*_: object) -> None:
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _stop)

    log.info("expirer started")
    while not stop.is_set():
        try:
            n = await _expire_once()
            if n:
                log.info("expired %d flags", n)
        except Exception:
            log.exception("expire tick failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=10.0)
        except asyncio.TimeoutError:
            pass

    log.info("expirer stopping")


if __name__ == "__main__":
    asyncio.run(main())
