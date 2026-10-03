"""Flag intake / browse API."""

from __future__ import annotations

import asyncio
import random
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import desc, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models, schemas
from ..config import get_config
from ..core.flag_extractor import extract_flags, is_well_formed
from ..db import get_session
from ..deps import require_token
from ..ws import hub

router = APIRouter(prefix="/api/flags", tags=["flags"])

_INGEST_RETRIES = 5
_INGEST_CHUNK_SIZE = 1000
_FLAG_MAX_LEN = 256  # models.Flag.flag column width


def _clip(value: str | None, limit: int) -> str | None:
    return value[:limit] if value else value


def _dedupe_and_sort_rows(
    rows: list[dict[str, str | None]],
) -> list[dict[str, str | None]]:
    """Keep first metadata for each flag and lock unique index keys stably."""
    by_flag: dict[str, dict[str, str | None]] = {}
    for row in rows:
        flag = row.get("flag")
        if flag and flag not in by_flag:
            by_flag[flag] = row
    return [by_flag[flag] for flag in sorted(by_flag)]


def _is_retryable_ingest_error(exc: DBAPIError) -> bool:
    text = str(exc.orig).lower()
    return "deadlock detected" in text or "could not serialize access" in text


def _chunks(
    rows: list[dict[str, str | None]],
    size: int,
) -> Iterator[list[dict[str, str | None]]]:
    for i in range(0, len(rows), size):
        yield rows[i : i + size]


async def _ingest_flags(
    sess: AsyncSession,
    rows: list[dict[str, str | None]],
) -> tuple[int, int]:
    """Bulk-insert candidate flags. Returns (new, duplicate).

    `duplicate` = how many of the candidates already existed in the DB
    (dedup against the unique index). Intra-batch repeats are collapsed
    before the insert and so don't inflate the count.
    """
    if not rows:
        return 0, 0

    insert_rows = _dedupe_and_sort_rows(rows)
    for attempt in range(_INGEST_RETRIES):
        try:
            inserted = []
            for chunk in _chunks(insert_rows, _INGEST_CHUNK_SIZE):
                stmt = (
                    pg_insert(models.Flag)
                    .values(chunk)
                    .on_conflict_do_nothing(index_elements=[models.Flag.flag])
                    .returning(models.Flag.id, models.Flag.flag)
                )
                result = await sess.execute(stmt)
                inserted.extend(result.fetchall())
            new = len(inserted)
            dup = len(insert_rows) - new
            return new, dup
        except DBAPIError as exc:
            await sess.rollback()
            if not _is_retryable_ingest_error(exc) or attempt == _INGEST_RETRIES - 1:
                raise
            await asyncio.sleep(0.05 * (2**attempt) + random.uniform(0, 0.05))

    raise RuntimeError("unreachable ingest retry state")


@router.post(
    "",
    response_model=schemas.FlagSubmitResponse,
    dependencies=[Depends(require_token)],
)
async def submit_flags(
    payload: schemas.FlagSubmitRequest,
    request: Request,
    sess: AsyncSession = Depends(get_session),
) -> schemas.FlagSubmitResponse:
    """Receive flags from a client.

    Each item is either a pre-extracted `flag`, or a chunk of `output` we
    will regex against the configured `flag_format`.
    """
    cfg = get_config()
    alias_by_ip = {t.ip: t.alias for t in cfg.expanded_teams()}
    candidates: list[dict[str, str | None]] = []
    invalid = 0

    for item in payload.items:
        team = item.team or alias_by_ip.get(item.target_ip or "")
        flags: list[str] = []
        if item.flag:
            if is_well_formed(item.flag, cfg.flag_format):
                flags.append(item.flag)
            else:
                invalid += 1
        if item.output:
            flags.extend(extract_flags(item.output, cfg.flag_format))

        for f in flags:
            if len(f) > _FLAG_MAX_LEN:
                # Would fail the whole insert — and every flag sent with it.
                invalid += 1
                continue
            candidates.append(
                {
                    "flag": f,
                    "status": models.FlagStatus.QUEUED.value,
                    "sploit": _clip(item.sploit, 128),
                    "team": _clip(team, 64),
                    "target_ip": _clip(item.target_ip, 64),
                }
            )

    new, dup = await _ingest_flags(sess, candidates)
    await sess.commit()

    if new:
        await hub.publish(
            "flags",
            {
                "new": new,
                "duplicate": dup,
                "client": request.client.host if request.client else None,
            },
        )

    return schemas.FlagSubmitResponse(new=new, duplicate=dup, invalid=invalid)


@router.post(
    "/manual",
    response_model=schemas.FlagSubmitResponse,
    dependencies=[Depends(require_token)],
)
async def submit_manual(
    payload: schemas.ManualFlagsRequest,
    sess: AsyncSession = Depends(get_session),
) -> schemas.FlagSubmitResponse:
    """Manual input from the UI: paste arbitrary text, get flags out."""
    cfg = get_config()
    flags = extract_flags(payload.text, cfg.flag_format)
    candidates = [
        {
            "flag": f,
            "status": models.FlagStatus.QUEUED.value,
            "sploit": _clip(payload.sploit or "manual", 128),
            "team": _clip(payload.team, 64),
        }
        for f in flags
        if len(f) <= _FLAG_MAX_LEN
    ]
    new, dup = await _ingest_flags(sess, candidates)
    await sess.commit()
    if new:
        await hub.publish("flags", {"new": new, "duplicate": dup, "manual": True})
    return schemas.FlagSubmitResponse(new=new, duplicate=dup, invalid=0)


_LIKE_ESCAPE = str.maketrans({"\\": "\\\\", "%": "\\%", "_": "\\_"})


@router.get("", response_model=list[schemas.FlagOut], dependencies=[Depends(require_token)])
async def list_flags(
    response: Response,
    status: str | None = Query(default=None),
    sploit: str | None = None,
    team: str | None = None,
    q: str | None = Query(default=None, description="Substring of the flag."),
    limit: int = Query(default=200, le=2000),
    offset: int = 0,
    sess: AsyncSession = Depends(get_session),
) -> list[models.Flag]:
    """Browse flags; the unpaginated match count is in `X-Total-Count`."""
    conds = []
    if status:
        conds.append(models.Flag.status == status)
    if sploit:
        conds.append(models.Flag.sploit == sploit)
    if team:
        conds.append(models.Flag.team == team)
    if q:
        conds.append(models.Flag.flag.ilike(f"%{q.translate(_LIKE_ESCAPE)}%", escape="\\"))

    total = await sess.scalar(select(func.count()).select_from(models.Flag).where(*conds))
    response.headers["X-Total-Count"] = str(total or 0)

    res = await sess.execute(
        select(models.Flag)
        .where(*conds)
        .order_by(desc(models.Flag.captured_at))
        .limit(limit)
        .offset(offset)
    )
    return list(res.scalars().all())


_BULK_REQUEUE_STATUSES = {
    models.FlagStatus.REJECTED.value,
    models.FlagStatus.ERROR.value,
    models.FlagStatus.EXPIRED.value,
}


@router.post(
    "/requeue",
    response_model=schemas.FlagRequeueResponse,
    dependencies=[Depends(require_token)],
)
async def requeue_flags(
    payload: schemas.FlagRequeueRequest,
    sess: AsyncSession = Depends(get_session),
) -> schemas.FlagRequeueResponse:
    """Requeue every matching flag that the jury may still accept.

    `captured_at` is kept, so anything past `flag_lifetime` is skipped —
    resubmitting it would only waste the jury rate limit.
    """
    if payload.status not in _BULK_REQUEUE_STATUSES:
        raise HTTPException(
            400, f"status must be one of {sorted(_BULK_REQUEUE_STATUSES)}"
        )
    cutoff = datetime.now(UTC) - timedelta(seconds=get_config().flag_lifetime)
    stmt = (
        update(models.Flag)
        .where(
            models.Flag.status == payload.status,
            models.Flag.captured_at >= cutoff,
        )
        .values(
            status=models.FlagStatus.QUEUED,
            submitted_at=None,
            response=None,
            attempts=0,
        )
        .returning(models.Flag.id)
    )
    if payload.sploit:
        stmt = stmt.where(models.Flag.sploit == payload.sploit)
    if payload.team:
        stmt = stmt.where(models.Flag.team == payload.team)
    requeued = len((await sess.execute(stmt)).fetchall())
    await sess.commit()
    if requeued:
        await hub.publish("requeue", {"flags": requeued, "from": payload.status})
    return schemas.FlagRequeueResponse(requeued=requeued)


@router.delete(
    "/{flag_id}",
    dependencies=[Depends(require_token)],
)
async def delete_flag(
    flag_id: int,
    sess: AsyncSession = Depends(get_session),
) -> dict[str, bool]:
    flag = await sess.get(models.Flag, flag_id)
    if flag is None:
        return {"ok": False}
    await sess.delete(flag)
    await sess.commit()
    return {"ok": True}


@router.post(
    "/{flag_id}/requeue",
    dependencies=[Depends(require_token)],
)
async def requeue_flag(
    flag_id: int,
    sess: AsyncSession = Depends(get_session),
) -> dict[str, bool]:
    flag = await sess.get(models.Flag, flag_id)
    if flag is None:
        return {"ok": False}
    flag.status = models.FlagStatus.QUEUED
    flag.submitted_at = None
    flag.response = None
    flag.attempts = 0
    # A manual single-flag requeue is an explicit "try this one again":
    # restart its lifetime so the expirer doesn't retire it immediately.
    flag.captured_at = datetime.now(UTC)
    await sess.commit()
    return {"ok": True}
