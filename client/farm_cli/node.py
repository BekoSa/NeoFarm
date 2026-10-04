"""Node agent — a farm-managed, persistent exploit runner.

``farm-cli node`` turns the machine it runs on into a *node*: it registers
with the farm, heartbeats every few seconds, and runs whatever exploit tasks
the operator assigned to it from the UI. Each task is driven in a round loop
identical to ``farm-cli run`` (via :func:`farm_cli.runner.fan_out`), so flags
and run reports travel the normal pipeline — the node layer only supervises
which exploits run and reports liveness.

Nothing here reaches beyond the team's own infrastructure: the agent runs the
team's exploit scripts against the configured CTF targets and reports back to
the team's farm. Scripts are fetched from the farm the operator controls.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
import socket
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from . import __version__, profile as profile_mod
from .api import FarmClient
from .runner import fan_out, parse_extra_args

log = logging.getLogger("farm.node")

AGENT_VERSION = __version__
_HEARTBEAT_INTERVAL = 5.0


def node_id(path: Path | None = None) -> str:
    """A stable per-machine id, generated once and cached on disk."""
    path = path or (profile_mod.DEFAULT_PATH.parent / "node-id")
    with contextlib.suppress(OSError):
        if path.exists():
            existing = path.read_text().strip()
            if existing:
                return existing
    nid = uuid.uuid4().hex
    with contextlib.suppress(OSError):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(nid)
        path.chmod(0o600)
    return nid


@dataclass(slots=True)
class _Task:
    """One running exploit loop the supervisor babysits."""

    sploit: str
    rev: int
    script_path: Path
    args: list[str]
    task: asyncio.Task
    since: float = field(default_factory=time.monotonic)


async def _run_task_loop(
    client: FarmClient,
    *,
    sploit: str,
    script: Path,
    args: list[str],
    host_label: str,
    round_length: int,
    flag_format: str,
    stop: asyncio.Event,
) -> None:
    """Drive one exploit against every team, round after round, until stopped.

    Mirrors ``farm-cli run``: each round refreshes the UI on/off switch, the
    farm config (pause, round length, flag regex) and the team list, then fans
    the script out across all targets within a per-round time budget.
    """
    targets: list[tuple[str, str]] = []
    rl = float(round_length)
    ff = flag_format

    while not stop.is_set():
        t0 = time.monotonic()
        enabled = True
        paused = False
        try:
            expl = await client.register_exploit(
                name=sploit, host=host_label, notes=f"node:{host_label}"
            )
            cfg = await client.get_config()
            targets = [(t["alias"], t["ip"]) for t in await client.list_teams()]
            enabled = bool(expl.get("enabled", True))
            paused = bool(cfg.get("paused", False))
            rl = float(cfg.get("round_length", rl))
            ff = cfg.get("flag_format", ff)
        except httpx.HTTPError as exc:
            log.warning("[%s] farm refresh failed (%s); reusing last config", sploit, exc)

        budget = max(5.0, rl - 5)
        if paused:
            log.info("[%s] farm paused — skipping round", sploit)
        elif not enabled:
            log.info("[%s] disabled in UI — skipping round", sploit)
        elif not targets:
            log.warning("[%s] no targets configured — skipping round", sploit)
        else:
            shuffled = random.sample(targets, len(targets))
            try:
                results = await fan_out(
                    script=script,
                    sploit=sploit,
                    targets=shuffled,
                    timeout=budget,
                    deadline=t0 + budget,
                    parallelism=0,
                    extra_args=args,
                    flag_format=ff,
                    farm=client,
                )
                flags = sum(r.flags_found for r in results)
                log.info("[%s] round done in %.1fs, %d flag(s)", sploit, time.monotonic() - t0, flags)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("[%s] round failed", sploit)

        sleep_for = max(0.5, rl - (time.monotonic() - t0))
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=sleep_for)


class NodeSupervisor:
    """Heartbeats the farm and keeps the running tasks in sync with it."""

    def __init__(
        self,
        client: FarmClient,
        *,
        name: str,
        workdir: Path,
        interval: float = _HEARTBEAT_INTERVAL,
    ) -> None:
        self._client = client
        self._name = name
        self._workdir = workdir
        self._interval = interval
        self._id = node_id()
        self._host = socket.gethostname()
        self._tasks: dict[str, _Task] = {}
        self._stops: dict[str, asyncio.Event] = {}

    async def run(self) -> None:
        self._workdir.mkdir(parents=True, exist_ok=True)
        log.info("node %s (%s) up — workdir %s", self._name, self._id[:8], self._workdir)
        try:
            while True:
                try:
                    resp = await self._heartbeat()
                    await self._reconcile(resp)
                except asyncio.CancelledError:
                    raise
                except httpx.HTTPError as exc:
                    log.warning("heartbeat failed (%s); retrying", exc)
                except Exception:
                    log.exception("supervisor tick failed")
                await asyncio.sleep(self._interval)
        finally:
            await self._stop_all()

    async def _heartbeat(self) -> dict:
        running = [
            {"sploit": s, "since_s": round(time.monotonic() - t.since)}
            for s, t in self._tasks.items()
        ]
        return await self._client.node_heartbeat(
            {
                "node_id": self._id,
                "name": self._name,
                "hostname": self._host,
                "agent_version": AGENT_VERSION,
                "status": "running" if self._tasks else "idle",
                "running": running,
            }
        )

    async def _reconcile(self, resp: dict) -> None:
        node_enabled = bool(resp.get("enabled", True))
        round_length = int(resp.get("round_length", 60))
        flag_format = resp.get("flag_format", r"[A-Z0-9]{31}=")
        tasks = resp.get("tasks", []) if node_enabled else []
        wanted = {t["sploit"]: t for t in tasks if t.get("enabled", True)}

        # Stop anything no longer wanted (removed, disabled, or node off).
        for sploit in [s for s in self._tasks if s not in wanted]:
            await self._stop_task(sploit)

        for sploit, spec in wanted.items():
            rev = int(spec.get("rev", 1))
            current = self._tasks.get(sploit)
            if current is not None and current.rev == rev:
                continue  # already running the right version
            if current is not None:
                await self._stop_task(sploit)  # content changed — restart
            self._start_task(spec, round_length, flag_format)

    def _start_task(self, spec: dict, round_length: int, flag_format: str) -> None:
        sploit = spec["sploit"]
        script_name = spec.get("script_name") or f"{sploit}.py"
        script_path = self._workdir / Path(script_name).name  # no path traversal
        script_path.write_text(spec.get("script", ""))
        with contextlib.suppress(OSError):
            script_path.chmod(0o700)
        args = parse_extra_args(spec.get("args") or "")

        stop = asyncio.Event()
        coro = _run_task_loop(
            self._client,
            sploit=sploit,
            script=script_path,
            args=args,
            host_label=self._host,
            round_length=round_length,
            flag_format=flag_format,
            stop=stop,
        )
        task = asyncio.create_task(coro, name=f"node-task:{sploit}")
        self._stops[sploit] = stop
        self._tasks[sploit] = _Task(
            sploit=sploit, rev=int(spec.get("rev", 1)),
            script_path=script_path, args=args, task=task,
        )
        log.info("started task %s (rev %s)", sploit, spec.get("rev"))

    async def _stop_task(self, sploit: str) -> None:
        self._stops.pop(sploit, None)
        state = self._tasks.pop(sploit, None)
        if state is None:
            return
        state.task.cancel()
        with contextlib.suppress(Exception, asyncio.CancelledError):
            await state.task
        log.info("stopped task %s", sploit)

    async def _stop_all(self) -> None:
        for sploit in list(self._tasks):
            await self._stop_task(sploit)
