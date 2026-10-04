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
    if cfg.paused:
        # On a break: never age flags out (the game clock is stopped), but
        # still purge old run reports — that is disk hygiene, not game state.
        return 0, 0, await _purge_runs(now, cfg.runs_retention)
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
        n_expired = len(expired.fetchall())
        n_requeued = len(requeued.fetchall())
    return n_expired, n_requeued, await _purge_runs(now, cfg.runs_retention)


async def _purge_runs(now: datetime, retention: int) -> int:
    """Delete run reports older than `retention` seconds (0 keeps all)."""
    if retention <= 0:
        return 0
    async with session_scope() as sess:
        res = await sess.execute(
            delete(Run).where(Run.started_at < now - timedelta(seconds=retention))
        )
        return res.rowcount or 0


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
