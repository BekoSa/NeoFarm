"""Read / write the YAML config without restarting the server."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..config import FarmConfig, get_config, replace_config
from ..deps import require_token
from ..protocols import available_protocols
from ..validators import available_validators
from ..ws import hub

router = APIRouter(prefix="/api/config", tags=["config"])


class PauseRequest(BaseModel):
    paused: bool


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
    if cfg.flag_validator not in available_validators():
        raise HTTPException(
            400,
            f"unknown flag_validator '{cfg.flag_validator}'; "
            f"available: {sorted(available_validators())}",
        )
    new = replace_config(cfg, persist=True)
    return new.model_dump(mode="json", by_alias=True)


@router.get("/protocols", dependencies=[Depends(require_token)])
async def list_protocols() -> list[str]:
    return sorted(available_protocols())


@router.get("/validators", dependencies=[Depends(require_token)])
async def list_validators() -> list[str]:
    return sorted(available_validators())


@router.post("/pause", dependencies=[Depends(require_token)])
async def set_pause(req: PauseRequest) -> dict:
    """Pause/resume the farm for a break (persisted to config.yml)."""
    cfg = get_config()
    saved = replace_config(cfg.model_copy(update={"paused": req.paused}), persist=True)
    await hub.publish("pause", {"paused": saved.paused})
    return {"paused": saved.paused}
