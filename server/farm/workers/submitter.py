"""Submitter worker — periodically drains queued flags to the jury.

Behaviour:

* Picks up to `submitter.batch_size` queued flags — fresh ones (fewest
  attempts) first, oldest first within that — and marks them PENDING in
  the same transaction, so concurrent submitters never double-submit.
* Calls the configured protocol and records each verdict.
* ERROR verdicts (jury unreachable, 5xx, 4xx from a misconfigured team
  token/id, ...) are never final: the flag goes back to QUEUED with its
  attempt counter bumped, and is retried until the expirer retires it.
  Fixing the config mid-game therefore loses nothing.
* If the protocol raises, the whole batch is requeued the same way.
* After a submission it waits `submitter.period` (the jury rate limit);
  while the queue is empty it polls every `submitter.idle_period`.
"""

from __future__ import annotations

import asyncio
import logging
import signal
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import bindparam, select, update

from .. import events
from ..config import FarmConfig, get_config, reload_config
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
}

_APPLY_CHUNK_SIZE = 1000
_RESPONSE_LIMIT = 4000


@dataclass(slots=True)
class BatchOutcome:
    rows: list[dict[str, object]] = field(default_factory=list)
    accepted: int = 0
    rejected: int = 0
    retry: int = 0
    sample_error: str | None = None


def plan_updates(
    flags: list[tuple[int, str]],
    outcomes_by_flag: dict[str, tuple[str, str]],
    now: datetime,
) -> BatchOutcome:
    """Turn protocol verdicts for (id, flag) pairs into row updates."""
    out = BatchOutcome()
    for flag_id, flag in flags:
        verdict, response = outcomes_by_flag.get(
            flag, (FlagVerdict.ERROR, "no verdict from protocol")
        )
        response = (response or "")[:_RESPONSE_LIMIT]
        status = _VERDICT_MAP.get(verdict)
        if status is None:
            out.retry += 1
            out.sample_error = out.sample_error or response
            out.rows.append(
                {
                    "flag_id": flag_id,
                    "status_value": FlagStatus.QUEUED.value,
                    "response_value": response,
                    "submitted_at_value": None,
                }
            )
            continue
        if status is FlagStatus.ACCEPTED:
            out.accepted += 1
        else:
            out.rejected += 1
        out.rows.append(
            {
                "flag_id": flag_id,
                "status_value": status.value,
                "response_value": response,
                "submitted_at_value": now,
            }
        )
    return out


def _chunks(rows: list[dict[str, object]], size: int) -> Iterator[list[dict[str, object]]]:
    for i in range(0, len(rows), size):
        yield rows[i : i + size]


async def _claim_batch(batch_size: int, flag_lifetime: int) -> list[tuple[int, str]]:
    now = datetime.now(UTC)
    async with session_scope() as sess:
        q = (
            select(Flag.id, Flag.flag)
            .where(
                Flag.status == FlagStatus.QUEUED,
                # Leave already-dead flags to the expirer instead of
                # spending jury rate limit on them.
                Flag.captured_at >= now - timedelta(seconds=flag_lifetime),
            )
            .order_by(Flag.attempts.asc(), Flag.captured_at.asc())
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
        rows = [(r.id, r.flag) for r in (await sess.execute(q)).all()]
        if not rows:
            return []
        await sess.execute(
            update(Flag)
            .where(Flag.id.in_([flag_id for flag_id, _ in rows]))
            .values(status=FlagStatus.PENDING, submitted_at=now)
        )
    return rows


async def _apply(rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    table = Flag.__table__
    stmt = (
        update(table)
        .where(table.c.id == bindparam("flag_id"))
        .values(
            status=bindparam("status_value"),
            response=bindparam("response_value"),
            submitted_at=bindparam("submitted_at_value"),
            attempts=table.c.attempts + 1,
        )
    )
    async with session_scope() as sess:
        for chunk in _chunks(rows, _APPLY_CHUNK_SIZE):
            await sess.execute(stmt, chunk)


async def _tick(cfg: FarmConfig) -> bool:
    batch = await _claim_batch(cfg.submitter.batch_size, cfg.flag_lifetime)
    if not batch:
        return False

    proto_name = cfg.protocol
    proto_kwargs = cfg.protocols.get(proto_name, {})
    log.debug("submitting %d flags via '%s'", len(batch), proto_name)

    try:
        proto = build_protocol(proto_name, **proto_kwargs)
        results = await proto.submit([flag for _, flag in batch])
        by_flag = {r.flag: (r.verdict, r.response) for r in results}
    except Exception as exc:
        log.exception("protocol '%s' crashed; requeueing batch", proto_name)
        message = f"protocol crashed: {exc!r}"
        by_flag = {flag: (FlagVerdict.ERROR, message) for _, flag in batch}

    outcome = plan_updates(batch, by_flag, datetime.now(UTC))
    await _apply(outcome.rows)

    if outcome.retry and not (outcome.accepted or outcome.rejected):
        # Nothing got a verdict — the jury is down or refuses our requests
        # (wrong token / team id). Shout: this costs points until fixed.
        log.warning(
            "jury gave no verdict for any of %d flags via '%s' (e.g. %r) — "
            "check protocols.%s in config.yml; flags stay queued",
            len(batch), proto_name, outcome.sample_error, proto_name,
        )
        await events.publish(
            "submitter_error",
            {"protocol": proto_name, "flags": len(batch), "error": outcome.sample_error},
        )
    await events.publish(
        "submit",
        {
            "protocol": proto_name,
            "accepted": outcome.accepted,
            "rejected": outcome.rejected,
            "retry": outcome.retry,
        },
    )
    return True


async def main() -> None:
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
            had_work = await _tick(cfg)
        except Exception:
            log.exception("submitter tick failed")
            had_work = True  # back off for a full period, don't spin on a broken DB
        sleep_for = cfg.submitter.period if had_work else cfg.submitter.idle_period
        try:
            await asyncio.wait_for(stop.wait(), timeout=sleep_for)
        except asyncio.TimeoutError:
            pass

    log.info("submitter stopping")


if __name__ == "__main__":
    asyncio.run(main())
