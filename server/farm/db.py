"""Async SQLAlchemy engine + session factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from .config import get_settings

# Constant key for pg_advisory_lock — serializes schema setup across
# server + workers on cold start so concurrent CREATE TABLE IF NOT EXISTS
# can't race on pg_type uniqueness.
_SCHEMA_LOCK_KEY = 0x6661726D5F696E69  # "farm_ini"


class Base(DeclarativeBase):
    pass


_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def _create_known_indexes(sync_conn) -> None:
    """Ensure indexes added after table creation exist on persistent volumes."""
    for table in Base.metadata.sorted_tables:
        for index in table.indexes:
            index.create(bind=sync_conn, checkfirst=True)


def engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database_url,
            pool_size=settings.postgres_pool_size,
            max_overflow=settings.postgres_max_overflow,
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
    """Create tables. Idempotent and concurrency-safe.

    `CREATE TABLE IF NOT EXISTS` is not safe under concurrency in Postgres —
    parallel callers can race on pg_type uniqueness. We serialize with a
    transaction-scoped advisory lock so only one process runs the DDL; the
    others wait, then no-op. Retries the connect itself a few times in case
    the database is still coming up.
    """
    import asyncio
    import logging

    from . import models  # noqa: F401  ensure models are imported

    log = logging.getLogger("farm.db")
    last_exc: Exception | None = None
    for attempt in range(30):
        try:
            async with engine().begin() as conn:
                await conn.execute(
                    text("SELECT pg_advisory_xact_lock(:k)"),
                    {"k": _SCHEMA_LOCK_KEY},
                )
                await conn.run_sync(Base.metadata.create_all)
                await conn.run_sync(_create_known_indexes)
            return
        except Exception as exc:
            last_exc = exc
            log.warning(
                "init_db attempt %d failed (%s); retrying in 1s", attempt + 1, exc
            )
            await asyncio.sleep(1.0)
    raise RuntimeError(f"init_db: gave up after retries: {last_exc}")
