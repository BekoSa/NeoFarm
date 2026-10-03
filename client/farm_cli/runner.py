"""Run an exploit script against a list of teams.

The runner is language-agnostic. It picks an interpreter from the file
extension (`.py` -> python3, `.sh` -> bash, ...) or, if the file is
executable, runs it directly.

Each team gets its own subprocess. stdout is scanned line by line for the
flag regex; newly seen flags are shipped to the farm about once a second,
so they reach the jury while the exploit is still running. A short run
report (exit code, output tails) follows when the process ends.

The whole round shares one deadline: a target whose turn comes late only
gets the time that is left, so a hanging exploit can't stretch a round
past `round_length`.
"""

from __future__ import annotations

import asyncio
import codecs
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
from collections.abc import Sequence
from pathlib import Path

from .api import FarmClient

log = logging.getLogger("farm.runner")

_TAIL_LIMIT = 4000
_FLUSH_INTERVAL = 1.0
_SUBMIT_BATCH = 500
_STREAM_CHUNK_SIZE = 4096
# A "line" longer than this is scanned without waiting for its newline;
# the last _STREAM_OVERLAP chars are re-scanned with the next chunk.
_LINE_LIMIT = 64 * 1024
_STREAM_OVERLAP = 512
# Don't bother starting a target with less time than this left in the round.
_MIN_RUN_TIME = 1.0
# How long to wait for output pipes to drain after the process exits.
_DRAIN_TIMEOUT = 2.0
# Delivery rounds (3 HTTP attempts each, 1s apart) before giving up on flags.
_FINAL_FLUSH_ROUNDS = 3


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
    exit_code: int | None
    duration_ms: int
    stdout: str
    stderr: str
    flags_found: int
    skipped: bool = False


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


async def _submit_flags_with_retries(
    farm: FarmClient,
    items: list[dict],
    log_label: str,
) -> bool:
    for attempt in range(3):
        try:
            await farm.submit_flags(items)
            return True
        except Exception:
            if attempt == 2:
                log.exception("%s failed", log_label)
            else:
                await asyncio.sleep(0.2 * (attempt + 1))
    return False


class FlagSink:
    """Deduplicates flags found in one run and ships new ones to the farm.

    Flags that couldn't be delivered stay queued for the next flush.
    """

    def __init__(
        self,
        farm: FarmClient,
        *,
        sploit: str,
        team: str | None,
        target_ip: str | None,
    ) -> None:
        self._farm = farm
        self._meta = {"sploit": sploit, "team": team, "target_ip": target_ip}
        self._seen: dict[str, None] = {}
        self._unsent: list[str] = []
        self._lock = asyncio.Lock()

    @property
    def found(self) -> int:
        return len(self._seen)

    @property
    def unsent(self) -> list[str]:
        return list(self._unsent)

    def add(self, flag: str) -> None:
        if flag not in self._seen:
            self._seen[flag] = None
            self._unsent.append(flag)

    async def flush(self) -> bool:
        """Try to deliver everything pending; True when nothing is left."""
        async with self._lock:
            while self._unsent:
                batch = self._unsent[:_SUBMIT_BATCH]
                items = [{"flag": f, **self._meta} for f in batch]
                if not await _submit_flags_with_retries(self._farm, items, "flag submit"):
                    return False
                del self._unsent[: len(batch)]
            return True

    async def run_flusher(self) -> None:
        while True:
            await asyncio.sleep(_FLUSH_INTERVAL)
            await self.flush()


def _scan(text: str, flag_re: re.Pattern[str], sink: FlagSink) -> None:
    for match in flag_re.finditer(text):
        sink.add(match.group(0))


async def _stream(
    proc: asyncio.subprocess.Process,
    flag_re: re.Pattern[str],
    sink: FlagSink,
    stdout_tail: _BoundedTail,
    stderr_tail: _BoundedTail,
) -> None:
    """Drain process output, feeding complete lines to the flag regex."""

    async def pump_stdout() -> None:
        assert proc.stdout
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        carry = ""
        while True:
            data = await proc.stdout.read(_STREAM_CHUNK_SIZE)
            if not data:
                break
            text = decoder.decode(data)
            stdout_tail.append(text)
            buf = carry + text
            cut = buf.rfind("\n")
            if cut >= 0:
                _scan(buf[:cut], flag_re, sink)
                carry = buf[cut + 1 :]
            elif len(buf) > _LINE_LIMIT:
                _scan(buf, flag_re, sink)
                carry = buf[-_STREAM_OVERLAP:]
            else:
                carry = buf
        tail = decoder.decode(b"", final=True)
        stdout_tail.append(tail)
        _scan(carry + tail, flag_re, sink)

    async def pump_stderr() -> None:
        assert proc.stderr
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        while True:
            data = await proc.stderr.read(_STREAM_CHUNK_SIZE)
            if not data:
                break
            stderr_tail.append(decoder.decode(data))

    await asyncio.gather(pump_stdout(), pump_stderr())


def _kill_process_tree(proc: asyncio.subprocess.Process) -> None:
    """SIGKILL the child's process group (helpers included).

    The child was started with ``start_new_session=True``, so its pgid is
    its pid — this works even after the main process exited and left
    helpers behind holding the output pipes.
    """
    pid = proc.pid
    if pid is None:
        return
    try:
        os.killpg(pid, signal.SIGKILL)
        return
    except ProcessLookupError:
        pass
    except (PermissionError, OSError):
        pass
    with contextlib.suppress(ProcessLookupError):
        proc.kill()


async def _stop_task(task: asyncio.Task) -> None:
    task.cancel()
    with contextlib.suppress(Exception, asyncio.CancelledError):
        await task


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
    sink = FlagSink(farm, sploit=sploit, team=team, target_ip=target_ip)
    stdout_tail = _BoundedTail(_TAIL_LIMIT)
    stderr_tail = _BoundedTail(_TAIL_LIMIT)
    stream_task = asyncio.create_task(
        _stream(proc, re.compile(flag_format), sink, stdout_tail, stderr_tail)
    )
    flusher = asyncio.create_task(sink.run_flusher())

    timed_out = False
    try:
        try:
            exit_code: int | None = await asyncio.wait_for(proc.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            timed_out = True
            _kill_process_tree(proc)
            with contextlib.suppress(Exception):
                await proc.wait()
            exit_code = -9

        try:
            await asyncio.wait_for(asyncio.shield(stream_task), timeout=_DRAIN_TIMEOUT)
        except asyncio.TimeoutError:
            # Leftover helpers still hold the pipes open.
            _kill_process_tree(proc)
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(asyncio.shield(stream_task), timeout=_DRAIN_TIMEOUT)
        if not stream_task.done():
            await _stop_task(stream_task)
            stderr_tail.append("[farm] failed to collect process output\n")
    except asyncio.CancelledError:
        # Aborted (second Ctrl-C): kill the exploit, still try to deliver
        # what it already printed.
        _kill_process_tree(proc)
        await _stop_task(stream_task)
        await _stop_task(flusher)
        with contextlib.suppress(Exception, asyncio.TimeoutError):
            await asyncio.wait_for(sink.flush(), timeout=3.0)
        raise

    await _stop_task(flusher)
    for attempt in range(_FINAL_FLUSH_ROUNDS):
        if await sink.flush():
            break
        if attempt < _FINAL_FLUSH_ROUNDS - 1:
            await asyncio.sleep(1.0)
    else:
        # Better noisy than lost: the operator can paste these into the UI.
        log.error(
            "could not deliver %d flag(s) from %s/%s: %s",
            len(sink.unsent), sploit, team, " ".join(sink.unsent),
        )

    stdout = stdout_tail.value()
    stderr = stderr_tail.value()
    if timed_out:
        stderr = (stderr + f"[farm] killed after {timeout:.1f}s\n")[-_TAIL_LIMIT:]

    duration_ms = int((time.monotonic() - start) * 1000)

    for attempt in range(3):
        try:
            await farm.report_run(
                sploit=sploit,
                team=team,
                target_ip=target_ip,
                host=host_label,
                flags_found=sink.found,
                duration_ms=duration_ms,
                exit_code=exit_code,
                stdout_tail=stdout or None,
                stderr_tail=stderr or None,
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
        flags_found=sink.found,
    )


async def fan_out(
    *,
    script: Path,
    sploit: str,
    targets: Sequence[tuple[str, str]],   # (alias, ip)
    timeout: float,
    deadline: float,
    parallelism: int,
    extra_args: list[str],
    flag_format: str,
    farm: FarmClient,
) -> list[RunResult]:
    """Run against every target; `deadline` is a time.monotonic() value.

    `parallelism <= 0` runs all targets at once.
    """
    sem = asyncio.Semaphore(parallelism if parallelism > 0 else max(1, len(targets)))
    host_label = socket.gethostname()

    async def task(team: str, ip: str) -> RunResult:
        async with sem:
            remaining = deadline - time.monotonic()
            if remaining < _MIN_RUN_TIME:
                log.warning("skipping %s (%s): round deadline reached", team, ip)
                return RunResult(
                    team=team, target_ip=ip, exit_code=None, duration_ms=0,
                    stdout="", stderr="", flags_found=0, skipped=True,
                )
            return await run_once(
                script=script,
                sploit=sploit,
                target_ip=ip,
                team=team,
                timeout=min(timeout, remaining),
                extra_args=extra_args,
                flag_format=flag_format,
                farm=farm,
                host_label=host_label,
            )

    return await asyncio.gather(*(task(alias, ip) for alias, ip in targets))


def parse_extra_args(raw: str) -> list[str]:
    return shlex.split(raw) if raw else []
