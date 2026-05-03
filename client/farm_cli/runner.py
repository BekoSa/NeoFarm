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
import signal
import socket
import time
from collections import deque
from collections.abc import Iterable
from pathlib import Path

from .api import FarmClient

log = logging.getLogger("farm.runner")

_FLAG_TAIL_LIMIT = 4000
_FLUSH_INTERVAL = 1.0
_FINAL_FLAG_BATCH = 500
_STREAM_CHUNK_SIZE = 4096
_STREAM_CARRY_LIMIT = 512


class _BoundedTail:
    """Append-only buffer that retains only the last ``limit`` chars."""

    __slots__ = ("_chunks", "_size", "_limit")

    def __init__(self, limit: int) -> None:
        self._chunks: deque[str] = deque()
        self._size = 0
        self._limit = limit

    def append(self, text: str) -> None:
        if not text:
            return
        # If a single write blows the budget, keep only the suffix.
        if len(text) >= self._limit:
            self._chunks.clear()
            self._chunks.append(text[-self._limit :])
            self._size = self._limit
            return
        self._chunks.append(text)
        self._size += len(text)
        while self._size > self._limit and self._chunks:
            head = self._chunks[0]
            drop = self._size - self._limit
            if drop >= len(head):
                self._chunks.popleft()
                self._size -= len(head)
            else:
                self._chunks[0] = head[drop:]
                self._size -= drop

    def value(self) -> str:
        return "".join(self._chunks)


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
    flag_re: re.Pattern[str],
) -> tuple[str, str, list[str]]:
    """Drain process output without retaining unbounded stdout/stderr."""
    stdout_tail = _BoundedTail(_FLAG_TAIL_LIMIT)
    stderr_tail = _BoundedTail(_FLAG_TAIL_LIMIT)
    flags_seen: dict[str, None] = {}

    async def pump_stdout() -> None:
        assert proc.stdout
        buffer: list[str] = []
        buffered_len = 0
        carry = ""
        last = time.monotonic()
        while True:
            data = await proc.stdout.read(_STREAM_CHUNK_SIZE)
            if not data:
                break
            text = data.decode("utf-8", "replace")
            stdout_tail.append(text)

            search_text = carry + text
            for match in flag_re.finditer(search_text):
                flags_seen.setdefault(match.group(0), None)
            carry = search_text[-_STREAM_CARRY_LIMIT:]

            buffer.append(text)
            buffered_len += len(text)
            if time.monotonic() - last >= _FLUSH_INTERVAL or buffered_len >= 4096:
                chunk = "".join(buffer)
                buffer.clear()
                buffered_len = 0
                last = time.monotonic()
                await on_chunk(chunk)
        if buffer:
            await on_chunk("".join(buffer))

    async def pump_stderr() -> None:
        assert proc.stderr
        while True:
            data = await proc.stderr.read(_STREAM_CHUNK_SIZE)
            if not data:
                break
            stderr_tail.append(data.decode("utf-8", "replace"))

    await asyncio.gather(pump_stdout(), pump_stderr())
    return stdout_tail.value(), stderr_tail.value(), list(flags_seen)


def _batched(items: list[str], size: int) -> Iterable[list[str]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _kill_process_tree(proc: asyncio.subprocess.Process) -> None:
    """SIGKILL the child's process group; falls back to single-pid kill."""
    pid = proc.pid
    if pid is None:
        return
    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL)
        return
    except ProcessLookupError:
        return
    except (PermissionError, OSError):
        with contextlib.suppress(ProcessLookupError):
            proc.kill()


async def _submit_flags_with_retries(
    farm: FarmClient,
    items: list[dict],
    log_label: str,
) -> None:
    for attempt in range(3):
        try:
            await farm.submit_flags(items)
            return
        except Exception:
            if attempt == 2:
                log.exception("%s failed", log_label)
            else:
                await asyncio.sleep(0.2 * (attempt + 1))


async def run_once(
    *,
    script: Path,
    sploit: str,
    target_ip: str,
    team: str | None,
    timeout: float,
    extra_args: list[str],
    flag_format: str,
    farm: FarmClient,
    host_label: str,
) -> RunResult:
    cmd = build_command(script, target_ip, extra_args)
    start = time.monotonic()

    # start_new_session=True puts the child in its own process group so we can
    # SIGKILL the whole tree on timeout (exploits often spawn helpers).
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ, "FARM_TARGET": target_ip},
        start_new_session=True,
    )
    flag_re = re.compile(flag_format)

    async def on_chunk(chunk: str) -> None:
        await _submit_flags_with_retries(
            farm,
            [
                {
                    "output": chunk,
                    "sploit": sploit,
                    "team": team,
                    "target_ip": target_ip,
                }
            ],
            "flag submit",
        )

    stream_task = asyncio.create_task(_stream(proc, on_chunk, flag_re))
    timed_out = False
    try:
        exit_code = await asyncio.wait_for(proc.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        timed_out = True
        _kill_process_tree(proc)
        with contextlib.suppress(Exception):
            await proc.wait()
        exit_code = -9

    try:
        stdout, stderr, final_flags = await asyncio.wait_for(stream_task, timeout=2.0)
    except Exception:
        stream_task.cancel()
        with contextlib.suppress(Exception, asyncio.CancelledError):
            await stream_task
        stdout, stderr, final_flags = (
            "",
            "[farm] failed to collect process output\n",
            [],
        )

    if timed_out:
        stderr = ((stderr or "") + f"[farm] killed after {timeout:.1f}s\n")[
            -_FLAG_TAIL_LIMIT:
        ]

    duration_ms = int((time.monotonic() - start) * 1000)

    flags_found = len(final_flags)

    for batch in _batched(final_flags, _FINAL_FLAG_BATCH):
        await _submit_flags_with_retries(
            farm,
            [
                {
                    "flag": flag,
                    "sploit": sploit,
                    "team": team,
                    "target_ip": target_ip,
                }
                for flag in batch
            ],
            "final flag submit",
        )

    for attempt in range(3):
        try:
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
            break
        except Exception:
            if attempt == 2:
                log.exception("run report failed")
            else:
                await asyncio.sleep(0.2 * (attempt + 1))

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
    flag_format: str,
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
                flag_format=flag_format,
                farm=farm,
                host_label=host_label,
            )

    coros = [task(alias, ip) for alias, ip in targets]
    return await asyncio.gather(*coros)


def parse_extra_args(raw: str) -> list[str]:
    return shlex.split(raw) if raw else []
