"""Teams endpoint — sourced from config.yml."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..config import get_config
from ..deps import require_token
from ..schemas import TeamOut

router = APIRouter(prefix="/api/teams", tags=["teams"])


@router.get("", response_model=list[TeamOut], dependencies=[Depends(require_token)])
async def list_teams() -> list[TeamOut]:
    return [TeamOut(alias=t.alias, ip=t.ip) for t in get_config().expanded_teams()]
