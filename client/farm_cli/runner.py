"""Run an exploit script against a list of teams.

The runner is language-agnostic. It picks an interpreter from the file
extension (`.py` -> python3, `.sh` -> bash, ...) or, if the file is
executable, runs it directly.

Each team gets its own subprocess in parallel, with a per-process
timeout slightly less than `round_length`. stdout is streamed in chunks
to the farm so flags appear in the dashboard in near-real-time, and
again on completion as a "run report".
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import logging
import os
import re
import shlex
import socket
import time
from collections.abc import Iterable
from pathlib import Path

from .api import FarmClient

log = logging.getLogger("farm.runner")

_FLAG_TAIL_LIMIT = 4000
_FLUSH_INTERVAL = 1.0


# Interpreter mapping for non-executable scripts.
_INTERPRETERS: dict[str, list[str]] = {
    ".py": ["python3", "-u"],
    ".py3": ["python3", "-u"],
    ".sh": ["bash"],
    ".bash": ["bash"],
    ".rb": ["ruby"],
    ".js": ["node"],
    ".ts": ["npx", "tsx"],
    ".pl": ["perl"],
    ".php": ["php"],
}


@dataclasses.dataclass(slots=True)
class RunResult:
    team: str | None
    target_ip: str | None
    exit_code: int
    duration_ms: int
    stdout: str
    stderr: str
    flags_found: int


def build_command(script: Path, target: str, extra_args: list[str]) -> list[str]:
    """Pick an interpreter for the script and inject `target` as argv[1]."""
    suffix = script.suffix.lower()
    args = list(extra_args)
    if suffix in _INTERPRETERS:
        return [*_INTERPRETERS[suffix], str(script), target, *args]
    # No suffix or unknown — assume it's executable.
    if not os.access(script, os.X_OK):
        raise SystemExit(
            f"don't know how to run {script.name}: unknown extension and not executable. "
            f"chmod +x it, or rename to one of {sorted(_INTERPRETERS)}"
        )
    return [str(script), target, *args]


async def _stream(
    proc: asyncio.subprocess.Process,
    on_chunk,
    flag_re: re.Pattern[str] | None = None,
) -> tuple[str, str]:
    """Drain stdout/stderr concurrently. Calls on_chunk(chunk) for stdout."""
    stdout_chunks: list[str] = []
    stderr_chunks: list[str] = []

    async def pump_stdout() -> None:
        assert proc.stdout
        buffer: list[str] = []
        last = time.monotonic()
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            text = line.decode("utf-8", "replace")
            stdout_chunks.append(text)
            buffer.append(text)
            if time.monotonic() - last >= _FLUSH_INTERVAL or sum(map(len, buffer)) > 4096:
                chunk = "".join(buffer)
                buffer.clear()
                last = time.monotonic()
                await on_chunk(chunk)
        if buffer:
            await on_chunk("".join(buffer))

    async def pump_stderr() -> None:
        assert proc.stderr
        while True:
            line = await proc.stderr.readline()
            if not line:
                break
            stderr_chunks.append(line.decode("utf-8", "replace"))

    await asyncio.gather(pump_stdout(), pump_stderr())
    return "".join(stdout_chunks), "".join(stderr_chunks)


async def run_once(
    *,
    script: Path,
    sploit: str,
    target_ip: str,
    team: str | None,
    timeout: float,
    extra_args: list[str],
    farm: FarmClient,
    host_label: str,
) -> RunResult:
    cmd = build_command(script, target_ip, extra_args)
    start = time.monotonic()

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ, "FARM_TARGET": target_ip},
    )

    async def on_chunk(chunk: str) -> None:
        try:
            await farm.submit_flags(
                [
                    {
                        "output": chunk,
                        "sploit": sploit,
                        "team": team,
                        "target_ip": target_ip,
                    }
                ]
            )
        except Exception:  # network blip, don't kill the run
            log.exception("flag submit failed")

    try:
        stdout, stderr = await asyncio.wait_for(_stream(proc, on_chunk), timeout=timeout)
        exit_code = await proc.wait()
    except asyncio.TimeoutError:
        proc.kill()
        with contextlib.suppress(Exception):
            await proc.wait()
        stdout, stderr = ("", f"[farm] killed after {timeout:.1f}s\n")
        exit_code = -9

    duration_ms = int((time.monotonic() - start) * 1000)

    flag_re = re.compile(r"[A-Z0-9]{31}=")
    flags_found = len(set(flag_re.findall(stdout)))

    await farm.report_run(
        sploit=sploit,
        team=team,
        target_ip=target_ip,
        host=host_label,
        flags_found=flags_found,
        duration_ms=duration_ms,
        exit_code=exit_code,
        stdout_tail=stdout[-_FLAG_TAIL_LIMIT:] or None,
        stderr_tail=stderr[-_FLAG_TAIL_LIMIT:] or None,
    )

    return RunResult(
        team=team,
        target_ip=target_ip,
        exit_code=exit_code,
        duration_ms=duration_ms,
        stdout=stdout,
        stderr=stderr,
        flags_found=flags_found,
    )


async def fan_out(
    *,
    script: Path,
    sploit: str,
    targets: Iterable[tuple[str, str]],   # (alias, ip)
    timeout: float,
    parallelism: int,
    extra_args: list[str],
    farm: FarmClient,
) -> list[RunResult]:
    sem = asyncio.Semaphore(parallelism)
    host_label = socket.gethostname()

    async def task(team: str, ip: str) -> RunResult:
        async with sem:
            return await run_once(
                script=script,
                sploit=sploit,
                target_ip=ip,
                team=team,
                timeout=timeout,
                extra_args=extra_args,
                farm=farm,
                host_label=host_label,
            )

    coros = [task(alias, ip) for alias, ip in targets]
    return await asyncio.gather(*coros)


def parse_extra_args(raw: str) -> list[str]:
    return shlex.split(raw) if raw else []
