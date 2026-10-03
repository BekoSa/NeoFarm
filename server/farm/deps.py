"""Common FastAPI dependencies."""

from __future__ import annotations

import hmac

from fastapi import Header, HTTPException, status

from .config import get_settings


def token_ok(token: str | None) -> bool:
    expected = get_settings().farm_api_token
    return bool(token) and hmac.compare_digest(token.encode(), expected.encode())


async def require_token(x_farm_token: str | None = Header(default=None)) -> None:
    """Auth gate. The token is shared between server, CLI and frontend."""
    if not token_ok(x_farm_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-Farm-Token",
        )
