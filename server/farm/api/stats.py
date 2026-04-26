"""Aggregated statistics for the dashboard."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models, schemas
from ..db import get_session
from ..deps import require_token

router = APIRouter(prefix="/api/stats", tags=["stats"])


def _bucket_columns():
    """Sum-case columns per status, returning a tuple suitable for select()."""
    s = models.Flag.status
    return (
        func.sum(case((s == models.FlagStatus.ACCEPTED, 1), else_=0)).label("accepted"),
        func.sum(case((s == models.FlagStatus.REJECTED, 1), else_=0)).label("rejected"),
        func.sum(
            case(
                (s.in_([models.FlagStatus.QUEUED, models.FlagStatus.PENDING]), 1),
                else_=0,
            )
        ).label("queued"),
        func.sum(case((s == models.FlagStatus.EXPIRED, 1), else_=0)).label("expired"),
        func.sum(case((s == models.FlagStatus.DUPLICATE, 1), else_=0)).label("duplicate"),
        func.sum(case((s == models.FlagStatus.ERROR, 1), else_=0)).label("error"),
    )


def _to_bucket(label: str, row) -> schemas.StatsBucket:
    return schemas.StatsBucket(
        label=label,
        accepted=int(row.accepted or 0),
        rejected=int(row.rejected or 0),
        queued=int(row.queued or 0),
        expired=int(row.expired or 0),
        duplicate=int(row.duplicate or 0),
        error=int(row.error or 0),
    )


@router.get("", response_model=schemas.StatsOut, dependencies=[Depends(require_token)])
async def stats(sess: AsyncSession = Depends(get_session)) -> schemas.StatsOut:
    cols = _bucket_columns()
    now = datetime.now(UTC)

    totals_row = (await sess.execute(select(*cols))).one()
    totals = _to_bucket("total", totals_row)

    minute_row = (
        await sess.execute(
            select(*cols).where(models.Flag.captured_at >= now - timedelta(minutes=1))
        )
    ).one()
    last_minute = _to_bucket("1m", minute_row)

    hour_row = (
        await sess.execute(
            select(*cols).where(models.Flag.captured_at >= now - timedelta(hours=1))
        )
    ).one()
    last_hour = _to_bucket("1h", hour_row)

    by_sploit_rows = (
        await sess.execute(
            select(models.Flag.sploit, *cols).group_by(models.Flag.sploit)
        )
    ).all()
    by_sploit = [
        _to_bucket(r.sploit or "unknown", r) for r in by_sploit_rows
    ]
    by_sploit.sort(key=lambda b: b.accepted + b.rejected, reverse=True)

    by_team_rows = (
        await sess.execute(
            select(models.Flag.team, *cols).group_by(models.Flag.team)
        )
    ).all()
    by_team = [_to_bucket(r.team or "unknown", r) for r in by_team_rows]
    by_team.sort(key=lambda b: b.accepted + b.rejected, reverse=True)

    return schemas.StatsOut(
        totals=totals,
        by_sploit=by_sploit,
        by_team=by_team,
        last_minute=last_minute,
        last_hour=last_hour,
    )
