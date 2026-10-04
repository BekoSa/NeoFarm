"""Cross-process live events: workers -> Redis pub/sub -> API -> WebSocket.

The submitter and expirer run in their own containers, so they can't reach
the API's in-process hub directly. They publish to a Redis channel; the API
subscribes on startup and re-publishes every message to its WebSocket hub.

Publishing is best-effort: a dead Redis must never stall flag submission.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import Any

import redis.asyncio as aioredis

from .config import get_settings
from .ws import Hub

log = logging.getLogger("farm.events")

CHANNEL = "farm:events"
# Running counters that aren't backed by DB rows (e.g. duplicates are dropped
# at ingest, never stored), kept in Redis so all processes share one value.
DEDUP_KEY = "farm:stats:deduplicated"

_publisher: aioredis.Redis | None = None


def _publisher_client() -> aioredis.Redis:
    global _publisher
    if _publisher is None:
        _publisher = aioredis.Redis.from_url(
            get_settings().redis_url, socket_connect_timeout=1, socket_timeout=1
        )
    return _publisher


async def publish(kind: str, payload: dict[str, Any]) -> None:
    try:
        await _publisher_client().publish(
            CHANNEL, json.dumps({"kind": kind, "payload": payload}, default=str)
        )
    except Exception as exc:
        log.debug("event publish failed: %s", exc)


async def bump_counter(key: str, n: int) -> None:
    """Best-effort INCRBY of a shared counter; a dead Redis must not stall."""
    if n <= 0:
        return
    try:
        await _publisher_client().incrby(key, n)
    except Exception as exc:
        log.debug("counter bump failed: %s", exc)


async def read_counter(key: str) -> int:
    """Best-effort read of a shared counter; 0 if unavailable."""
    try:
        value = await _publisher_client().get(key)
        return int(value) if value else 0
    except Exception as exc:
        log.debug("counter read failed: %s", exc)
        return 0


async def forward_to_hub(hub: Hub) -> None:
    """Relay worker events into `hub` until cancelled; reconnects on errors."""
    while True:
        # No socket timeout here: the subscriber legitimately idles for long.
        client = aioredis.Redis.from_url(
            get_settings().redis_url, socket_connect_timeout=3, health_check_interval=30
        )
        pubsub = client.pubsub(ignore_subscribe_messages=True)
        try:
            await pubsub.subscribe(CHANNEL)
            log.info("relaying worker events from redis channel %s", CHANNEL)
            async for msg in pubsub.listen():
                try:
                    data = json.loads(msg["data"])
                except (KeyError, TypeError, ValueError):
                    continue
                await hub.publish(str(data.get("kind", "event")), data.get("payload") or {})
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("redis event relay failed (%s); retrying in 3s", exc)
        finally:
            with contextlib.suppress(Exception):
                await pubsub.aclose()
            with contextlib.suppress(Exception):
                await client.aclose()
        await asyncio.sleep(3)
