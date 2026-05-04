"""Read / write the YAML config without restarting the server."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..config import FarmConfig, get_config, replace_config
from ..deps import require_token
from ..protocols import available_protocols

router = APIRouter(prefix="/api/config", tags=["config"])


@router.get("", dependencies=[Depends(require_token)])
async def read_config() -> dict:
    return get_config().model_dump(mode="json", by_alias=True)


@router.put("", dependencies=[Depends(require_token)])
async def write_config(payload: dict) -> dict:
    try:
        cfg = FarmConfig.model_validate(payload)
    except Exception as exc:
        raise HTTPException(400, f"invalid config: {exc}") from exc
    if cfg.protocol not in available_protocols():
        raise HTTPException(
            400,
            f"unknown protocol '{cfg.protocol}'; "
            f"available: {sorted(available_protocols())}",
        )
    new = replace_config(cfg, persist=True)
    return new.model_dump(mode="json", by_alias=True)


@router.get("/protocols", dependencies=[Depends(require_token)])
async def list_protocols() -> list[str]:
    return sorted(available_protocols())
