"""Installer endpoints — give clients a one-line way to grab farm-cli.

The CLI is pre-built into a self-contained zipapp during the Docker image
build (see ``server/Dockerfile``: ``cli-builder`` stage) and dropped at
``/app/static/farm-cli.pyz``. These routes are intentionally unauthenticated
so a fresh teammate can ``curl`` the artifact before they have a token.
The pyz contains no secrets — credentials are still supplied via
``farm-cli login``.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse

router = APIRouter(tags=["install"])

_PYZ_PATH = Path("/app/static/farm-cli.pyz")


@router.get("/install", response_class=PlainTextResponse)
async def install_instructions(request: Request) -> str:
    """Plain-text copy-paste instructions, with the caller's host filled in."""
    base = str(request.base_url).rstrip("/")
    return (
        "# farm-cli — one-shot installer\n"
        "#\n"
        "# Requires: python3 (>=3.11) on the client machine. No pip, no venv.\n"
        "#\n"
        "# 1) download:\n"
        f"curl -fsSL {base}/install/farm-cli -o farm-cli\n"
        "chmod +x ./farm-cli\n"
        "\n"
        "# 2) login (replace TOKEN with the value from your farm admin):\n"
        f"./farm-cli login {base} --token TOKEN\n"
        "\n"
        "# 3) run an exploit against every configured team, once per round:\n"
        "./farm-cli run /path/to/sploit.py\n"
        "\n"
        "# Other commands: ping, teams, send, watch, config.\n"
        "# See ./farm-cli --help for the full list.\n"
    )


@router.get("/install/farm-cli")
async def download_cli() -> FileResponse:
    """Serve the bundled zipapp."""
    if not _PYZ_PATH.is_file():
        raise HTTPException(
            503,
            "farm-cli bundle is not available on this server "
            "(image was not built with the cli-builder stage).",
        )
    return FileResponse(
        _PYZ_PATH,
        media_type="application/octet-stream",
        filename="farm-cli",
        headers={"Cache-Control": "no-cache"},
    )
