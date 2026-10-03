"""Expirer — moves stale queued flags to EXPIRED and purges old run reports.

A flag is stale when it was captured more than `flag_lifetime` seconds ago
and is still QUEUED/PENDING. Submitting an expired flag is pointless: most
juries will reject it and we burn rate-limit slots that could go to fresh
flags instead.

Run reports (stdout/stderr tails) are only useful while debugging the
current state of an exploit, so ones older than `runs_retention` seconds
are deleted to keep the table small.
"""

from __future__ import annotations

import asyncio
import logging
import signal
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, or_, update

from .. import events
from ..config import get_config, reload_config
from ..db import init_db, session_scope
from ..models import Flag, FlagStatus, Run

log = logging.getLogger("farm.expirer")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

_PENDING_LEASE_SECONDS = 60.0


async def _expire_once() -> tuple[int, int, int]:
    """Returns (expired flags, requeued stale claims, purged runs)."""
    cfg = get_config()
    now = datetime.now(UTC)
    lifetime_cutoff = now - timedelta(seconds=cfg.flag_lifetime)
    pending_cutoff = now - timedelta(
        seconds=max(_PENDING_LEASE_SECONDS, cfg.submitter.period * 5)
    )
    async with session_scope() as sess:
        requeued = await sess.execute(
            update(Flag)
            .where(
                Flag.status == FlagStatus.PENDING,
                Flag.captured_at >= lifetime_cutoff,
                or_(Flag.submitted_at.is_(None), Flag.submitted_at < pending_cutoff),
            )
            .values(
                status=FlagStatus.QUEUED,
                submitted_at=None,
                response="stale pending claim requeued",
            )
            .returning(Flag.id)
        )
        expired = await sess.execute(
            update(Flag)
            .where(
                Flag.status.in_([FlagStatus.QUEUED, FlagStatus.PENDING]),
                Flag.captured_at < lifetime_cutoff,
            )
            .values(status=FlagStatus.EXPIRED)
            .returning(Flag.id)
        )
        purged = 0
        if cfg.runs_retention > 0:
            res = await sess.execute(
                delete(Run).where(
                    Run.started_at < now - timedelta(seconds=cfg.runs_retention)
                )
            )
            purged = res.rowcount or 0
        return len(expired.fetchall()), len(requeued.fetchall()), purged


async def main() -> None:
    reload_config()
    await init_db()
    stop = asyncio.Event()

    def _stop(*_: object) -> None:
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _stop)
    loop.add_signal_handler(
        signal.SIGHUP, lambda: (reload_config(), log.info("config reloaded"))
    )

    log.info("expirer started")
    while not stop.is_set():
        try:
            expired, requeued, purged = await _expire_once()
            if expired:
                log.info("expired %d flags", expired)
                await events.publish("expired", {"flags": expired})
            if requeued:
                log.info("requeued %d stale pending flags", requeued)
            if purged:
                log.info("purged %d old run reports", purged)
        except Exception:
            log.exception("expire tick failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=10.0)
        except asyncio.TimeoutError:
            pass

    log.info("expirer stopping")


if __name__ == "__main__":
    asyncio.run(main())
