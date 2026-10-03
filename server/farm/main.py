"""FastAPI entrypoint."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import config as config_api
from .api import exploits as exploits_api
from .api import flags as flags_api
from .api import install as install_api
from .api import stats as stats_api
from .api import teams as teams_api
from .api import ws as ws_api
from .config import get_config, get_settings
from .db import init_db
from .events import forward_to_hub
from .protocols import available_protocols
from .ws import hub

log = logging.getLogger("farm.api")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

_INSECURE_TOKENS = {"", "change-me-please"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    if get_settings().farm_api_token in _INSECURE_TOKENS:
        # The farm sits on the game network: anyone guessing the default
        # token could read, delete or poison our flags.
        raise RuntimeError("FARM_API_TOKEN is empty or the default; set a real one in .env")
    log.info("loading protocols")
    available_protocols()
    log.info("loading config from %s", get_settings().farm_config)
    get_config()
    log.info("running schema migrations")
    await init_db()
    relay_task = asyncio.create_task(forward_to_hub(hub))
    try:
        yield
    finally:
        relay_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await relay_task


app = FastAPI(title="Farm", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    # Auth is a header, not a cookie — no credentialed CORS needed.
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Total-Count"],
)

app.include_router(flags_api.router)
app.include_router(exploits_api.router)
app.include_router(teams_api.router)
app.include_router(stats_api.router)
app.include_router(config_api.router)
app.include_router(install_api.router)
app.include_router(ws_api.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
async def root() -> dict[str, str]:
    return {"service": "farm", "version": app.version}
