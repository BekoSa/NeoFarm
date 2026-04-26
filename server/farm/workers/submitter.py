"""Submitter worker — periodically drains queued flags to the jury.

Behaviour:

* Wakes every `submitter.period` seconds.
* Picks up to `submitter.batch_size` queued flags (oldest first).
* Marks them PENDING within the same transaction so a crash mid-flight
  doesn't double-submit.
* Calls the configured protocol; updates each row with verdict + response.
* If the protocol raises before producing any result, the flags are
  rolled back to QUEUED.
"""

from __future__ import annotations

import asyncio
import logging
import signal
from datetime import UTC, datetime

from sqlalchemy import select, update

from ..config import get_config, reload_config
from ..db import init_db, session_scope
from ..models import Flag, FlagStatus
from ..protocols import build_protocol
from ..protocols.base import FlagVerdict

log = logging.getLogger("farm.submitter")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")


_VERDICT_MAP = {
    FlagVerdict.ACCEPTED: FlagStatus.ACCEPTED,
    FlagVerdict.REJECTED: FlagStatus.REJECTED,
    FlagVerdict.ERROR: FlagStatus.ERROR,
}


async def _claim_batch(batch_size: int) -> list[Flag]:
    async with session_scope() as sess:
        q = (
            select(Flag)
            .where(Flag.status == FlagStatus.QUEUED)
            .order_by(Flag.captured_at.asc())
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
        rows = (await sess.execute(q)).scalars().all()
        if not rows:
            return []
        ids = [f.id for f in rows]
        await sess.execute(
            update(Flag).where(Flag.id.in_(ids)).values(status=FlagStatus.PENDING)
        )
        # Detach so the caller can read attributes after the session closes.
        for f in rows:
            sess.expunge(f)
    return list(rows)


async def _apply_results(flags: list[Flag], outcomes_by_flag: dict[str, tuple[str, str]]) -> None:
    async with session_scope() as sess:
        now = datetime.now(UTC)
        for f in flags:
            verdict, response = outcomes_by_flag.get(
                f.flag, (FlagVerdict.ERROR, "no verdict from protocol")
            )
            new_status = _VERDICT_MAP.get(verdict, FlagStatus.ERROR)
            await sess.execute(
                update(Flag)
                .where(Flag.id == f.id)
                .values(status=new_status, response=response[:4000], submitted_at=now)
            )


async def _rollback_pending(flags: list[Flag]) -> None:
    if not flags:
        return
    async with session_scope() as sess:
        await sess.execute(
            update(Flag)
            .where(Flag.id.in_([f.id for f in flags]))
            .values(status=FlagStatus.QUEUED)
        )


async def _tick() -> None:
    cfg = get_config()
    batch = await _claim_batch(cfg.submitter.batch_size)
    if not batch:
        return

    proto_name = cfg.protocol
    proto_kwargs = cfg.protocols.get(proto_name, {})
    log.info("submitting %d flags via '%s'", len(batch), proto_name)

    try:
        proto = build_protocol(proto_name, **proto_kwargs)
        results = await proto.submit([f.flag for f in batch])
    except Exception:
        log.exception("protocol crashed; requeueing batch")
        await _rollback_pending(batch)
        return

    by_flag = {r.flag: (r.verdict, r.response) for r in results}
    await _apply_results(batch, by_flag)


async def main() -> None:
    # Make sure the config is loaded before the loop, and re-read on SIGHUP.
    reload_config()
    # The workers can outrace the API container's lifespan migrations, so
    # they ensure the schema themselves. `create_all` is idempotent.
    await init_db()

    stop = asyncio.Event()

    def _stop(*_: object) -> None:
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _stop)
    loop.add_signal_handler(signal.SIGHUP, lambda: (reload_config(), log.info("config reloaded")))

    log.info("submitter started")
    while not stop.is_set():
        cfg = get_config()
        try:
            await _tick()
        except Exception:
            log.exception("submitter tick failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=cfg.submitter.period)
        except asyncio.TimeoutError:
            pass

    log.info("submitter stopping")


if __name__ == "__main__":
    asyncio.run(main())
