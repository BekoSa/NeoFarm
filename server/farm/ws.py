"""In-process pub/sub for the WebSocket feed.

We don't need Redis pubsub here — there's exactly one API process per
deployment. Workers that want to push live events POST /api/internal/event
which calls publish() on the API hub.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import WebSocket


class Hub:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[str]] = set()
        self._lock = asyncio.Lock()

    async def subscribe(self) -> asyncio.Queue[str]:
        q: asyncio.Queue[str] = asyncio.Queue(maxsize=512)
        async with self._lock:
            self._subscribers.add(q)
        return q

    async def unsubscribe(self, q: asyncio.Queue[str]) -> None:
        async with self._lock:
            self._subscribers.discard(q)

    async def publish(self, kind: str, payload: dict[str, Any]) -> None:
        msg = json.dumps({"kind": kind, "payload": payload}, default=str)
        async with self._lock:
            queues = list(self._subscribers)
        for q in queues:
            # If a client is too slow, drop oldest events for it.
            if q.full():
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            q.put_nowait(msg)


hub = Hub()


async def relay(ws: WebSocket) -> None:
    q = await hub.subscribe()
    try:
        while True:
            msg = await q.get()
            await ws.send_text(msg)
    finally:
        await hub.unsubscribe(q)
