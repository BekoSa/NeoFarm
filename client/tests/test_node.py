from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from farm_cli import node

FLAG_RE = r"[A-Z0-9]{31}="


class _DummyTask:
    def cancel(self) -> None:  # pragma: no cover - never awaited in tests
        pass


class RecordingSupervisor(node.NodeSupervisor):
    """A supervisor that records start/stop decisions instead of spawning
    real asyncio tasks, so `_reconcile` can be tested in isolation."""

    def __init__(self, **kw) -> None:
        super().__init__(**kw)
        self.started: list[tuple[str, int]] = []
        self.stopped: list[str] = []

    def _start_task(self, spec: dict, round_length: int, flag_format: str) -> None:
        sploit = spec["sploit"]
        rev = int(spec.get("rev", 1))
        self.started.append((sploit, rev))
        self._tasks[sploit] = node._Task(
            sploit=sploit, rev=rev, script_path=Path("x"), args=[], task=_DummyTask(),
        )

    async def _stop_task(self, sploit: str) -> None:
        if sploit in self._tasks:
            self.stopped.append(sploit)
            self._tasks.pop(sploit, None)
            self._stops.pop(sploit, None)


@pytest.fixture
def sup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> RecordingSupervisor:
    monkeypatch.setattr(node, "node_id", lambda *a, **k: "test-node-id")
    return RecordingSupervisor(client=object(), name="n", workdir=tmp_path)


def _task(sploit: str, rev: int = 1, enabled: bool = True) -> dict:
    return {
        "sploit": sploit, "rev": rev, "enabled": enabled,
        "script": "print(1)", "script_name": f"{sploit}.py", "args": None,
    }


def _resp(tasks: list[dict], enabled: bool = True) -> dict:
    return {"enabled": enabled, "round_length": 60, "flag_format": FLAG_RE, "tasks": tasks}


def recon(sup: RecordingSupervisor, resp: dict) -> None:
    asyncio.run(sup._reconcile(resp))


def test_starts_enabled_task(sup: RecordingSupervisor) -> None:
    recon(sup, _resp([_task("a")]))
    assert sup.started == [("a", 1)]
    assert sup.stopped == []


def test_same_rev_is_noop(sup: RecordingSupervisor) -> None:
    recon(sup, _resp([_task("a")]))
    sup.started.clear()
    recon(sup, _resp([_task("a")]))
    assert sup.started == []
    assert sup.stopped == []


def test_rev_bump_restarts(sup: RecordingSupervisor) -> None:
    recon(sup, _resp([_task("a", rev=1)]))
    sup.started.clear()
    recon(sup, _resp([_task("a", rev=2)]))
    assert sup.stopped == ["a"]
    assert sup.started == [("a", 2)]


def test_disabled_task_stops(sup: RecordingSupervisor) -> None:
    recon(sup, _resp([_task("a")]))
    recon(sup, _resp([_task("a", enabled=False)]))
    assert sup.stopped == ["a"]
    assert "a" not in sup._tasks


def test_removed_task_stops(sup: RecordingSupervisor) -> None:
    recon(sup, _resp([_task("a"), _task("b")]))
    assert sorted(sup._tasks) == ["a", "b"]
    recon(sup, _resp([_task("a")]))
    assert sup.stopped == ["b"]
    assert sorted(sup._tasks) == ["a"]


def test_node_disabled_stops_all(sup: RecordingSupervisor) -> None:
    recon(sup, _resp([_task("a"), _task("b")]))
    recon(sup, _resp([_task("a"), _task("b")], enabled=False))
    assert sorted(sup.stopped) == ["a", "b"]
    assert sup._tasks == {}


def test_node_id_persists(tmp_path: Path) -> None:
    path = tmp_path / "node-id"
    first = node.node_id(path)
    second = node.node_id(path)
    assert first == second
    assert len(first) == 32  # uuid4 hex
