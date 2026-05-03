"""Click-based CLI.

User-facing entrypoints:

* ``farm-cli login URL --token TOKEN``  — saves credentials.
* ``farm-cli ping``                      — health check.
* ``farm-cli config``                    — shows the current farm config.
* ``farm-cli run SCRIPT [--name NAME]``  — schedules SCRIPT once per round
                                           against every team from config.
                                           Works on any machine that can
                                           reach the farm.
* ``farm-cli send 'TEXT'``               — manual flag submission.
* ``farm-cli watch``                     — tails the live event feed.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import socket
import sys
import time
from pathlib import Path

import click
import httpx
import websockets
from rich.console import Console
from rich.table import Table

from . import profile as profile_mod
from .api import FarmClient
from .runner import fan_out, parse_extra_args

console = Console()
log = logging.getLogger("farm.cli")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)


def _async(coro_func):
    """Tiny shim — let click commands be async."""

    def wrapper(*args, **kwargs):
        return asyncio.run(coro_func(*args, **kwargs))

    wrapper.__name__ = coro_func.__name__
    wrapper.__doc__ = coro_func.__doc__
    return wrapper


@click.group()
def cli() -> None:
    """Farm client — drive CTF exploits and ship their output to the farm."""


@cli.command()
@click.argument("url")
@click.option("--token", "-t", required=True, help="X-Farm-Token from server config.")
@_async
async def login(url: str, token: str) -> None:
    """Save URL + token under ~/.config/farm-cli/profile.yml."""
    p = profile_mod.Profile(url=url.rstrip("/"), token=token)
    async with FarmClient(p) as client:
        try:
            await client.health()
            await client.get_config()
        except httpx.HTTPError as exc:
            console.print(f"[red]could not reach {url}: {exc}[/red]")
            sys.exit(1)
    profile_mod.save(p)
    console.print(f"[green]ok[/green] saved profile -> {profile_mod.DEFAULT_PATH}")


@cli.command()
@_async
async def ping() -> None:
    """Health check."""
    p = profile_mod.load()
    async with FarmClient(p) as client:
        console.print(await client.health())


@cli.command()
@_async
async def config() -> None:
    """Print the active farm config (read from the server)."""
    p = profile_mod.load()
    async with FarmClient(p) as client:
        console.print_json(data=await client.get_config())


@cli.command("teams")
@_async
async def teams() -> None:
    """List configured teams."""
    p = profile_mod.load()
    async with FarmClient(p) as client:
        rows = await client.list_teams()
    t = Table(title="Teams")
    t.add_column("alias")
    t.add_column("ip")
    for r in rows:
        t.add_row(r["alias"], r["ip"])
    console.print(t)


@cli.command("send")
@click.argument("text")
@click.option("--sploit", default="manual")
@click.option("--team", default=None)
@_async
async def send(text: str, sploit: str, team: str | None) -> None:
    """Manually submit flag(s) extracted from TEXT."""
    p = profile_mod.load()
    async with FarmClient(p) as client:
        result = await client.submit_manual(text, sploit=sploit, team=team)
    console.print(result)


@cli.command("run")
@click.argument("script", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--name", "-n", default=None, help="Exploit name (defaults to filename).")
@click.option(
    "--once", is_flag=True, default=False, help="Run a single round and exit."
)
@click.option(
    "--parallelism", "-p", type=int, default=8, help="Concurrent team runs."
)
@click.option(
    "--timeout",
    type=float,
    default=None,
    help="Per-team timeout (s). Defaults to round_length - 5.",
)
@click.option(
    "--target",
    multiple=True,
    help="Override targets. Format: alias=ip. May be repeated.",
)
@click.option(
    "--args",
    "extra_args",
    default="",
    help="Extra args appended to the script after target IP.",
)
@click.option(
    "--notes", default=None, help="Free-form notes to attach in the UI."
)
@_async
async def run(
    script: Path,
    name: str | None,
    once: bool,
    parallelism: int,
    timeout: float | None,
    target: tuple[str, ...],
    extra_args: str,
    notes: str | None,
) -> None:
    """Run SCRIPT against every configured team in a loop, one batch per round.

    SCRIPT is invoked as `<interpreter> SCRIPT <team-ip> [extra-args]`. The
    target IP is also exported as $FARM_TARGET. Anything matching the farm's
    flag regex on stdout is submitted automatically.
    """
    sploit = name or script.stem
    p = profile_mod.load()

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    async with FarmClient(p, timeout=20.0) as client:
        await client.register_exploit(
            name=sploit, host=socket.gethostname(), notes=notes
        )

        cfg = await client.get_config()

        # Build the team table: explicit --target wins; otherwise pull from config.
        if target:
            targets: list[tuple[str, str]] = []
            for spec in target:
                if "=" not in spec:
                    raise click.BadParameter(f"--target must be alias=ip ({spec!r})")
                alias, ip = spec.split("=", 1)
                targets.append((alias.strip(), ip.strip()))
        else:
            teams_raw = cfg.get("teams") or []
            targets = [(t["alias"], t["ip"]) for t in teams_raw]

        if not targets:
            console.print(
                "[red]no targets[/red]: configure teams in config.yml or pass --target"
            )
            sys.exit(2)

        round_length = cfg.get("round_length", 60)
        flag_format = cfg.get("flag_format", r"[A-Z0-9]{31}=")
        eff_timeout = timeout if timeout is not None else max(5.0, round_length - 5)

        round_idx = 0
        while not stop.is_set():
            round_idx += 1
            t0 = time.monotonic()
            console.print(
                f"[cyan]round {round_idx}[/cyan] sploit={sploit} "
                f"targets={len(targets)} timeout={eff_timeout:.1f}s"
            )
            try:
                results = await fan_out(
                    script=script,
                    sploit=sploit,
                    targets=targets,
                    timeout=eff_timeout,
                    parallelism=parallelism,
                    extra_args=parse_extra_args(extra_args),
                    flag_format=flag_format,
                    farm=client,
                )
            except Exception:
                log.exception("round failed")
                results = []

            total_flags = sum(r.flags_found for r in results)
            elapsed = time.monotonic() - t0
            console.print(
                f"  done in {elapsed:.1f}s, captured {total_flags} flag(s)"
            )

            if once or stop.is_set():
                break

            sleep_for = max(0.5, round_length - elapsed)
            try:
                await asyncio.wait_for(stop.wait(), timeout=sleep_for)
            except asyncio.TimeoutError:
                pass


@cli.command("watch")
@_async
async def watch() -> None:
    """Tail the live WebSocket event feed."""
    p = profile_mod.load()
    url = f"{p.ws_url}/ws?token={p.token}"
    async with websockets.connect(url, ping_interval=20) as ws:
        console.print(f"[green]connected[/green] to {url}")
        async for msg in ws:
            try:
                data = json.loads(msg)
            except ValueError:
                console.print(msg)
                continue
            kind = data.get("kind")
            payload = data.get("payload")
            console.print(f"[dim]{kind}[/dim] {json.dumps(payload, default=str)}")
