from __future__ import annotations

import asyncio
import sys
import textwrap
import time
from pathlib import Path

import pytest

from farm_cli import runner

FLAG_RE = r"[A-Z0-9]{31}="


def flag(i: int) -> str:
    return f"{i:031d}="


class FakeFarm:
    def __init__(self, fail_submits: int = 0) -> None:
        self.flags: list[str] = []
        self.submit_calls = 0
        self.runs: list[dict] = []
        self._fail = fail_submits

    async def submit_flags(self, items: list[dict]) -> dict:
        self.submit_calls += 1
        if self._fail:
            self._fail -= 1
            raise RuntimeError("farm down")
        assert all("output" not in i for i in items), "raw stdout must not be shipped"
        self.flags.extend(i["flag"] for i in items)
        return {}

    async def report_run(self, **kw) -> None:
        self.runs.append(kw)


def script(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "sploit.py"
    path.write_text(textwrap.dedent(body))
    return path


def run(path: Path, farm: FakeFarm, timeout: float = 10.0) -> runner.RunResult:
    return asyncio.run(
        runner.run_once(
            script=path, sploit="t", target_ip="10.0.0.1", team="team-01",
            timeout=timeout, extra_args=[], flag_format=FLAG_RE,
            farm=farm, host_label="test",
        )
    )


def test_each_flag_is_submitted_once(tmp_path: Path) -> None:
    path = script(
        tmp_path,
        f"""
        print("{flag(1)}")
        print("noise {flag(2)} {flag(1)}")
        print("{flag(2)}")
        """,
    )
    farm = FakeFarm()
    res = run(path, farm)
    assert sorted(farm.flags) == [flag(1), flag(2)]
    assert res.flags_found == 2
    assert farm.runs[0]["flags_found"] == 2


def test_flag_split_across_writes(tmp_path: Path) -> None:
    f = flag(7)
    path = script(
        tmp_path,
        f"""
        import sys, time
        sys.stdout.write("{f[:10]}"); sys.stdout.flush(); time.sleep(0.3)
        sys.stdout.write("{f[10:]}\\n"); sys.stdout.flush()
        sys.stdout.write("{flag(8)}")  # no trailing newline
        """,
    )
    farm = FakeFarm()
    run(path, farm)
    assert sorted(farm.flags) == [f, flag(8)]


def test_flags_stream_before_exit_and_timeout_kills(tmp_path: Path) -> None:
    path = script(
        tmp_path,
        f"""
        import subprocess, sys, time
        # A helper that would keep the pipes open forever.
        subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        print("{flag(3)}", flush=True)
        time.sleep(60)
        """,
    )
    farm = FakeFarm()
    t0 = time.monotonic()
    res = run(path, farm, timeout=2.5)
    assert time.monotonic() - t0 < 8
    assert res.exit_code == -9
    assert farm.flags == [flag(3)]
    assert "killed after" in farm.runs[0]["stderr_tail"]


def test_undelivered_flags_are_retried(tmp_path: Path) -> None:
    path = script(tmp_path, f'print("{flag(4)}")\n')
    farm = FakeFarm(fail_submits=4)  # the first flush exhausts its 3 attempts
    run(path, farm)
    assert farm.flags == [flag(4)]


def test_lost_flags_are_logged(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    path = script(tmp_path, f'print("{flag(5)}")\n')
    farm = FakeFarm(fail_submits=1000)
    run(path, farm)
    assert farm.flags == []
    assert flag(5) in caplog.text  # printed so it can be pasted by hand


@pytest.mark.parametrize("parallelism", [0, 1])
def test_round_deadline_skips_late_targets(tmp_path: Path, parallelism: int) -> None:
    path = script(tmp_path, "import time; time.sleep(30)\n")
    farm = FakeFarm()
    targets = [(f"team-{i}", f"10.0.0.{i}") for i in range(3)]

    t0 = time.monotonic()
    results = asyncio.run(
        runner.fan_out(
            script=path, sploit="t", targets=targets, timeout=30,
            deadline=time.monotonic() + 2.0, parallelism=parallelism,
            extra_args=[], flag_format=FLAG_RE, farm=farm,
        )
    )
    assert time.monotonic() - t0 < 8
    if parallelism == 0:
        assert [r.skipped for r in results] == [False, False, False]
    else:
        # The first target eats the whole budget; the rest are skipped.
        assert [r.skipped for r in results] == [False, True, True]


def test_unknown_extension_requires_exec_bit(tmp_path: Path) -> None:
    path = tmp_path / "sploit.bin"
    path.write_text("")
    with pytest.raises(SystemExit):
        runner.build_command(path, "1.2.3.4", [])
    assert runner.build_command(tmp_path / "x.py", "1.2.3.4", ["-v"])[-2:] == ["1.2.3.4", "-v"]
    assert sys.executable  # tests run the scripts with python3 from PATH
