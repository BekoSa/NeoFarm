"""WebSocket endpoint for live UI updates."""

from __future__ import annotations

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from ..config import get_settings
from ..ws import relay

router = APIRouter()


@router.websocket("/ws")
async def feed(ws: WebSocket, token: str = Query(default="")) -> None:
    if token != get_settings().farm_api_token:
        await ws.close(code=4401)
        return
    await ws.accept()
    try:
        await relay(ws)
    except WebSocketDisconnect:
        pass
