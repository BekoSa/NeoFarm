"""WebSocket endpoint for live UI updates.

Clients authenticate by sending the token as the first text message right
after connecting, so it never shows up in URLs or access logs. The legacy
`/ws?token=...` form is still accepted for older farm-cli builds.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from ..deps import token_ok
from ..ws import relay

router = APIRouter()

_AUTH_TIMEOUT = 5.0


@router.websocket("/ws")
async def feed(ws: WebSocket, token: str | None = Query(default=None)) -> None:
    await ws.accept()
    try:
        if token is None:
            try:
                token = await asyncio.wait_for(ws.receive_text(), timeout=_AUTH_TIMEOUT)
            except asyncio.TimeoutError:
                token = None
        if not token_ok(token):
            await ws.close(code=4401)
            return
        await relay(ws)
    except WebSocketDisconnect:
        pass
