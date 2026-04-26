"""Async SQLAlchemy engine + session factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from .config import get_settings


class Base(DeclarativeBase):
    pass


_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            get_settings().database_url,
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,
            future=True,
        )
    return _engine


def sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(
            engine(), expire_on_commit=False, class_=AsyncSession
        )
    return _sessionmaker


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Use in scripts/workers; commits on successful exit."""
    sess = sessionmaker()()
    try:
        yield sess
        await sess.commit()
    except Exception:
        await sess.rollback()
        raise
    finally:
        await sess.close()


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency."""
    async with sessionmaker()() as sess:
        yield sess


async def init_db() -> None:
    """Create tables. Idempotent — uses CREATE TABLE IF NOT EXISTS.

    Safe to call from multiple processes; we rely on Postgres' DDL
    serialization. Retries a few times in case the database is still
    coming up.
    """
    import asyncio
    import logging

    from . import models  # noqa: F401  ensure models are imported

    log = logging.getLogger("farm.db")
    last_exc: Exception | None = None
    for attempt in range(30):
        try:
            async with engine().begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            return
        except Exception as exc:
            last_exc = exc
            log.warning(
                "init_db attempt %d failed (%s); retrying in 1s", attempt + 1, exc
            )
            await asyncio.sleep(1.0)
    raise RuntimeError(f"init_db: gave up after retries: {last_exc}")
