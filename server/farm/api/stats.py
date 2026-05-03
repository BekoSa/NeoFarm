"""Aggregated statistics for the dashboard."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models, schemas
from ..db import get_session
from ..deps import require_token

router = APIRouter(prefix="/api/stats", tags=["stats"])

_STATUS_FIELD = {
    models.FlagStatus.ACCEPTED.value: "accepted",
    models.FlagStatus.REJECTED.value: "rejected",
    models.FlagStatus.QUEUED.value: "queued",
    models.FlagStatus.PENDING.value: "queued",
    models.FlagStatus.EXPIRED.value: "expired",
    models.FlagStatus.DUPLICATE.value: "duplicate",
    models.FlagStatus.ERROR.value: "error",
}


def _empty_counts() -> dict[str, int]:
    return {
        "accepted": 0,
        "rejected": 0,
        "queued": 0,
        "expired": 0,
        "duplicate": 0,
        "error": 0,
    }


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


def _counts_to_bucket(label: str, counts: dict[str, int]) -> schemas.StatsBucket:
    return schemas.StatsBucket(label=label, **counts)


def _add_count(counts: dict[str, int], status: str, count: int) -> None:
    field = _STATUS_FIELD.get(status)
    if field is not None:
        counts[field] += count


@router.get("", response_model=schemas.StatsOut, dependencies=[Depends(require_token)])
async def stats(sess: AsyncSession = Depends(get_session)) -> schemas.StatsOut:
    cols = _bucket_columns()
    now = datetime.now(UTC)

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

    summary_rows = (
        await sess.execute(
            select(
                models.Flag.sploit,
                models.Flag.team,
                models.Flag.status,
                func.count().label("count"),
            ).group_by(models.Flag.sploit, models.Flag.team, models.Flag.status)
        )
    ).all()

    totals_counts = _empty_counts()
    sploit_counts: dict[str, dict[str, int]] = defaultdict(_empty_counts)
    team_counts: dict[str, dict[str, int]] = defaultdict(_empty_counts)

    for row in summary_rows:
        count = int(row.count or 0)
        status = str(row.status)
        _add_count(totals_counts, status, count)
        _add_count(sploit_counts[row.sploit or "unknown"], status, count)
        _add_count(team_counts[row.team or "unknown"], status, count)

    totals = _counts_to_bucket("total", totals_counts)
    by_sploit = [
        _counts_to_bucket(label, counts) for label, counts in sploit_counts.items()
    ]
    by_sploit.sort(key=lambda b: b.accepted + b.rejected, reverse=True)

    by_team = [
        _counts_to_bucket(label, counts) for label, counts in team_counts.items()
    ]
    by_team.sort(key=lambda b: b.accepted + b.rejected, reverse=True)

    return schemas.StatsOut(
        totals=totals,
        by_sploit=by_sploit,
        by_team=by_team,
        last_minute=last_minute,
        last_hour=last_hour,
    )
