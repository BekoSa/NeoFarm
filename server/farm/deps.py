"""Common FastAPI dependencies."""

from __future__ import annotations

from fastapi import Header, HTTPException, status

from .config import get_settings


async def require_token(x_farm_token: str | None = Header(default=None)) -> None:
    """Auth gate. The token is shared between server, CLI and frontend."""
    if x_farm_token != get_settings().farm_api_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-Farm-Token",
        )
