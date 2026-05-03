"""Flag intake / browse API."""

from __future__ import annotations

import asyncio
import random
from collections.abc import Iterator
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import desc, select
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
    candidates: list[dict[str, str | None]] = []
    invalid = 0

    for item in payload.items:
        flags: list[str] = []
        if item.flag:
            if is_well_formed(item.flag, cfg.flag_format):
                flags.append(item.flag)
            else:
                invalid += 1
        if item.output:
            flags.extend(extract_flags(item.output, cfg.flag_format))

        for f in flags:
            candidates.append(
                {
                    "flag": f,
                    "status": models.FlagStatus.QUEUED.value,
                    "sploit": item.sploit,
                    "team": item.team,
                    "target_ip": item.target_ip,
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
            "sploit": payload.sploit or "manual",
            "team": payload.team,
        }
        for f in flags
    ]
    new, dup = await _ingest_flags(sess, candidates)
    await sess.commit()
    if new:
        await hub.publish("flags", {"new": new, "duplicate": dup, "manual": True})
    return schemas.FlagSubmitResponse(new=new, duplicate=dup, invalid=0)


@router.get("", response_model=list[schemas.FlagOut], dependencies=[Depends(require_token)])
async def list_flags(
    status: str | None = Query(default=None),
    sploit: str | None = None,
    team: str | None = None,
    limit: int = Query(default=200, le=2000),
    offset: int = 0,
    sess: AsyncSession = Depends(get_session),
) -> list[models.Flag]:
    q = select(models.Flag).order_by(desc(models.Flag.captured_at))
    if status:
        q = q.where(models.Flag.status == status)
    if sploit:
        q = q.where(models.Flag.sploit == sploit)
    if team:
        q = q.where(models.Flag.team == team)
    q = q.limit(limit).offset(offset)
    res = await sess.execute(q)
    return list(res.scalars().all())


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
    flag.captured_at = datetime.now(UTC)
    await sess.commit()
    return {"ok": True}
