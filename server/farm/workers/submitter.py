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
from collections.abc import Iterator
from datetime import UTC, datetime

from sqlalchemy import bindparam, select, update

from ..config import FarmConfig, reload_config
from ..db import init_db, session_scope
from ..models import Flag, FlagStatus
from ..protocols import build_protocol
from ..protocols.base import FlagVerdict

log = logging.getLogger("farm.submitter")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)


_VERDICT_MAP = {
    FlagVerdict.ACCEPTED: FlagStatus.ACCEPTED,
    FlagVerdict.REJECTED: FlagStatus.REJECTED,
    FlagVerdict.ERROR: FlagStatus.ERROR,
}

_NON_RETRYABLE_HTTP = (400, 401, 403, 404)
_APPLY_CHUNK_SIZE = 1000


def _is_retryable_error(response: str) -> bool:
    text = (response or "").lower()
    if any(f"http {code}" in text for code in _NON_RETRYABLE_HTTP):
        return False
    return True


def _chunks(rows: list[dict[str, object]], size: int) -> Iterator[list[dict[str, object]]]:
    for i in range(0, len(rows), size):
        yield rows[i : i + size]


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
        now = datetime.now(UTC)
        await sess.execute(
            update(Flag)
            .where(Flag.id.in_(ids))
            .values(status=FlagStatus.PENDING, submitted_at=now)
        )
        # Detach so the caller can read attributes after the session closes.
        for f in rows:
            sess.expunge(f)
    return list(rows)


async def _apply_results(flags: list[Flag], outcomes_by_flag: dict[str, tuple[str, str]]) -> None:
    rows: list[dict[str, object]] = []
    now = datetime.now(UTC)
    for f in flags:
        verdict, response = outcomes_by_flag.get(
            f.flag, (FlagVerdict.ERROR, "no verdict from protocol")
        )
        if verdict == FlagVerdict.ERROR and _is_retryable_error(response):
            rows.append(
                {
                    "flag_id": f.id,
                    "status_value": FlagStatus.QUEUED.value,
                    "response_value": response[:4000],
                    "submitted_at_value": None,
                }
            )
            continue
        new_status = _VERDICT_MAP.get(verdict, FlagStatus.ERROR)
        rows.append(
            {
                "flag_id": f.id,
                "status_value": new_status.value,
                "response_value": response[:4000],
                "submitted_at_value": now,
            }
        )

    if not rows:
        return

    stmt = (
        update(Flag.__table__)
        .where(Flag.id == bindparam("flag_id"))
        .values(
            status=bindparam("status_value"),
            response=bindparam("response_value"),
            submitted_at=bindparam("submitted_at_value"),
        )
    )
    async with session_scope() as sess:
        for chunk in _chunks(rows, _APPLY_CHUNK_SIZE):
            await sess.execute(stmt, chunk)


async def _rollback_pending(flags: list[Flag]) -> None:
    if not flags:
        return
    async with session_scope() as sess:
        await sess.execute(
            update(Flag)
            .where(Flag.id.in_([f.id for f in flags]))
            .values(status=FlagStatus.QUEUED)
        )


async def _tick(cfg: FarmConfig) -> bool:
    batch = await _claim_batch(cfg.submitter.batch_size)
    if not batch:
        return False

    proto_name = cfg.protocol
    proto_kwargs = cfg.protocols.get(proto_name, {})
    log.debug("submitting %d flags via '%s'", len(batch), proto_name)

    try:
        proto = build_protocol(proto_name, **proto_kwargs)
        results = await proto.submit([f.flag for f in batch])
    except Exception:
        log.exception("protocol crashed; requeueing batch")
        await _rollback_pending(batch)
        return True

    by_flag = {r.flag: (r.verdict, r.response) for r in results}
    await _apply_results(batch, by_flag)
    return True


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
        cfg = reload_config()
        had_work = False
        try:
            had_work = await _tick(cfg)
        except Exception:
            log.exception("submitter tick failed")
        sleep_for = cfg.submitter.period if had_work else max(
            cfg.submitter.period,
            cfg.submitter.idle_period,
        )
        try:
            await asyncio.wait_for(stop.wait(), timeout=sleep_for)
        except asyncio.TimeoutError:
            pass

    log.info("submitter stopping")


if __name__ == "__main__":
    asyncio.run(main())
