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
* ``farm-cli node``                      — run this machine as a farm-managed
                                           node: register, then run whatever
                                           exploits the operator assigns from
                                           the UI, each in its own round loop.
* ``farm-cli watch``                     — tails the live event feed.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import random
import signal
import socket
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import click
import httpx
import websockets
from rich.console import Console
from rich.table import Table

from . import profile as profile_mod
from .api import FarmClient
from .node import NodeSupervisor
from .runner import build_command, fan_out, parse_extra_args

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


@dataclass(slots=True)
class _RoundPlan:
    """What the farm told us last time; kept when a refresh fails."""

    enabled: bool = True
    paused: bool = False
    round_length: float = 60.0
    flag_format: str = r"[A-Z0-9]{31}="
    targets: list[tuple[str, str]] = field(default_factory=list)


def _parse_targets(specs: tuple[str, ...]) -> list[tuple[str, str]]:
    targets: list[tuple[str, str]] = []
    for spec in specs:
        if "=" not in spec:
            raise click.BadParameter(f"--target must be alias=ip ({spec!r})")
        alias, ip = spec.split("=", 1)
        targets.append((alias.strip(), ip.strip()))
    return targets


async def _refresh_plan(
    client: FarmClient,
    plan: _RoundPlan,
    *,
    sploit: str,
    notes: str | None,
    fixed_targets: list[tuple[str, str]],
    strict: bool,
) -> None:
    """Pull the exploit switch, config and team list from the farm.

    Runs every round, so config edits and the UI on/off toggle apply to
    running clients. With `strict` (first round) errors are fatal;
    afterwards the last known values are kept.
    """
    try:
        expl = await client.register_exploit(
            name=sploit, host=socket.gethostname(), notes=notes
        )
        cfg = await client.get_config()
        teams = (
            fixed_targets
            or [(t["alias"], t["ip"]) for t in await client.list_teams()]
        )
    except httpx.HTTPError as exc:
        if strict:
            console.print(f"[red]cannot reach the farm: {exc}[/red]")
            sys.exit(1)
        log.warning("farm refresh failed (%s); reusing the last known config", exc)
        return
    plan.enabled = bool(expl.get("enabled", True))
    plan.paused = bool(cfg.get("paused", False))
    plan.round_length = float(cfg.get("round_length", plan.round_length))
    plan.flag_format = cfg.get("flag_format", plan.flag_format)
    plan.targets = teams


@cli.command("run")
@click.argument("script", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--name", "-n", default=None, help="Exploit name (defaults to filename).")
@click.option(
    "--once", is_flag=True, default=False, help="Run a single round and exit."
)
@click.option(
    "--parallelism",
    "-p",
    type=int,
    default=0,
    help="Concurrent team runs (default 0 = all targets at once).",
)
@click.option(
    "--timeout",
    type=float,
    default=None,
    help="Time budget per round, which also caps each team run (s). "
    "Defaults to round_length - 5.",
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

    Ctrl-C finishes the current round and exits; press it again to kill
    the running exploits immediately.
    """
    sploit = name or script.stem
    args = parse_extra_args(extra_args)
    build_command(script, "0.0.0.0", args)  # fail fast on an unrunnable script
    fixed_targets = _parse_targets(target)
    p = profile_mod.load()

    stop = asyncio.Event()
    round_task: asyncio.Task | None = None

    def on_signal() -> None:
        if stop.is_set():
            console.print("[red]aborting: killing running exploits[/red]")
            if round_task is not None:
                round_task.cancel()
            return
        stop.set()
        console.print(
            "[yellow]stopping after this round — Ctrl-C again to abort now[/yellow]"
        )

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, on_signal)

    plan = _RoundPlan()
    async with FarmClient(p, timeout=20.0) as client:
        round_idx = 0
        while not stop.is_set():
            round_idx += 1
            t0 = time.monotonic()
            await _refresh_plan(
                client, plan, sploit=sploit, notes=notes,
                fixed_targets=fixed_targets, strict=round_idx == 1,
            )
            budget = timeout if timeout is not None else max(5.0, plan.round_length - 5)

            if plan.paused:
                console.print(
                    f"[yellow]round {round_idx}[/yellow] farm is paused "
                    "(break) — skipping"
                )
            elif not plan.targets:
                console.print(
                    "[red]no targets[/red]: configure teams in config.yml or pass --target"
                )
                if round_idx == 1:
                    sys.exit(2)
            elif not plan.enabled:
                console.print(
                    f"[yellow]round {round_idx}[/yellow] sploit={sploit} is "
                    "disabled in the UI — skipping"
                )
            else:
                # Shuffle so the same teams aren't always the ones that
                # start last and get cut by the round deadline.
                targets = random.sample(plan.targets, len(plan.targets))
                console.print(
                    f"[cyan]round {round_idx}[/cyan] sploit={sploit} "
                    f"targets={len(targets)} budget={budget:.1f}s"
                )
                round_task = asyncio.create_task(
                    fan_out(
                        script=script,
                        sploit=sploit,
                        targets=targets,
                        timeout=budget,
                        deadline=t0 + budget,
                        parallelism=parallelism,
                        extra_args=args,
                        flag_format=plan.flag_format,
                        farm=client,
                    )
                )
                try:
                    results = await round_task
                except asyncio.CancelledError:
                    console.print("[red]round aborted[/red]")
                    break
                except Exception:
                    log.exception("round failed")
                    results = []
                finally:
                    round_task = None

                total_flags = sum(r.flags_found for r in results)
                skipped = sum(r.skipped for r in results)
                elapsed = time.monotonic() - t0
                console.print(
                    f"  done in {elapsed:.1f}s, captured {total_flags} flag(s)"
                    + (f", [yellow]{skipped} target(s) skipped[/yellow]" if skipped else "")
                )

            if once or stop.is_set():
                break

            sleep_for = max(0.5, plan.round_length - (time.monotonic() - t0))
            try:
                await asyncio.wait_for(stop.wait(), timeout=sleep_for)
            except asyncio.TimeoutError:
                pass


@cli.command("node")
@click.option(
    "--name", "-n", default=None,
    help="Friendly node name shown in the UI (defaults to the hostname).",
)
@click.option(
    "--workdir", type=click.Path(path_type=Path), default=None,
    help="Where to write the exploit scripts the farm pushes "
    "(default: ~/.cache/farm-cli/node).",
)
@click.option(
    "--interval", type=float, default=5.0, help="Heartbeat interval (s)."
)
@_async
async def node(name: str | None, workdir: Path | None, interval: float) -> None:
    """Run this machine as a farm-managed node.

    Registers with the farm and keeps running whatever exploit tasks the
    operator assigns to this node from the UI, one round loop each — the same
    way `farm-cli run` works, but driven centrally. Leave it running; Ctrl-C
    stops every task and exits.
    """
    p = profile_mod.load()
    name = name or socket.gethostname()
    workdir = workdir or (Path.home() / ".cache" / "farm-cli" / "node")

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    async with FarmClient(p, timeout=20.0) as client:
        try:
            await client.health()
        except httpx.HTTPError as exc:
            console.print(f"[red]cannot reach the farm: {exc}[/red]")
            sys.exit(1)
        supervisor = NodeSupervisor(client, name=name, workdir=workdir, interval=interval)
        runner = asyncio.create_task(supervisor.run())
        console.print(f"[green]node up[/green] as [cyan]{name}[/cyan] — Ctrl-C to stop")
        await stop.wait()
        console.print("[yellow]stopping node — tearing down tasks[/yellow]")
        runner.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await runner


@cli.command("watch")
@_async
async def watch() -> None:
    """Tail the live WebSocket event feed."""
    p = profile_mod.load()
    url = f"{p.ws_url}/ws"
    async with websockets.connect(url, ping_interval=20) as ws:
        await ws.send(p.token)  # auth: first message, keeps the token out of URLs
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
