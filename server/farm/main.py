"""FastAPI entrypoint."""

from __future__ import annotations

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
from .protocols import available_protocols

log = logging.getLogger("farm.api")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("loading protocols")
    available_protocols()
    log.info("loading config from %s", get_settings().farm_config)
    get_config()
    log.info("running schema migrations")
    await init_db()
    yield


app = FastAPI(title="Farm", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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
