from __future__ import annotations

import os
import textwrap
from pathlib import Path

import pytest

from farm import config


@pytest.fixture
def cfg_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "config.yml"
    monkeypatch.setenv("FARM_CONFIG", str(path))
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(config, "_config", None)
    monkeypatch.setattr(config, "_config_stamp", None)
    monkeypatch.setattr(config, "_last_check", 0.0)
    monkeypatch.setattr(config, "_CHECK_INTERVAL", 0.0)
    return path


def write(path: Path, body: str) -> None:
    path.write_text(textwrap.dedent(body))
    # Make sure the stamp changes even on coarse-mtime filesystems.
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))


def test_missing_file_uses_defaults(cfg_file: Path) -> None:
    assert config.get_config().protocol == "dummy"


def test_picks_up_manual_edits(cfg_file: Path) -> None:
    write(cfg_file, "protocol: dummy\nround_length: 60\n")
    assert config.get_config().round_length == 60
    write(cfg_file, "protocol: dummy\nround_length: 30\n")
    assert config.get_config().round_length == 30


def test_invalid_edit_keeps_last_good(cfg_file: Path) -> None:
    write(cfg_file, "protocol: ctf01d\nflag_lifetime: 240\n")
    assert config.get_config().protocol == "ctf01d"

    write(cfg_file, "protocol: ctf01d\nflag_lifetime: [oops\n")  # broken YAML
    assert config.get_config().flag_lifetime == 240

    write(cfg_file, "protocol: ctf01d\nflag_lifetime: 1\n")  # fails validation
    assert config.get_config().flag_lifetime == 240

    write(cfg_file, "")  # caught mid-rewrite: must not fall back to dummy
    assert config.get_config().protocol == "ctf01d"

    write(cfg_file, "protocol: ctf01d\nflag_lifetime: 300\n")
    assert config.get_config().flag_lifetime == 300


def test_deleted_file_keeps_last_good(cfg_file: Path) -> None:
    write(cfg_file, "protocol: ctf01d\n")
    assert config.get_config().protocol == "ctf01d"
    cfg_file.unlink()
    assert config.get_config().protocol == "ctf01d"


def test_invalid_file_at_startup_raises(cfg_file: Path) -> None:
    write(cfg_file, "flag_lifetime: [oops\n")
    with pytest.raises(Exception):
        config.get_config()


def test_save_keeps_comments(cfg_file: Path) -> None:
    write(
        cfg_file,
        """\
        # Farm config header
        flag_format: "[A-Z0-9]{31}="   # jury regex
        flag_lifetime: 240
        protocol: dummy
        protocols:
          dummy:
            accept_rate: 1.0   # accept everything
        teams:
          - from: 1
            to: 3
            alias: "team-{i}"
            ip: "10.10.{i}.3"
        """,
    )
    cfg = config.get_config().model_copy(update={"flag_lifetime": 300})
    config.replace_config(cfg)

    text = cfg_file.read_text()
    assert "# Farm config header" in text
    assert "# jury regex" in text
    assert "# accept everything" in text
    assert "flag_lifetime: 300" in text
    # The saved file round-trips to the same config.
    assert config.reload_config() == cfg


def test_target_teams_excludes_own_team() -> None:
    cfg = config.FarmConfig.model_validate(
        {
            "teams": [{"from": 1, "to": 4, "alias": "team-{i:02d}", "ip": "10.10.{i}.3"}],
            "exclude_teams": ["team-02", "10.10.4.3"],
        }
    )
    assert [t.alias for t in cfg.expanded_teams()] == ["team-01", "team-02", "team-03", "team-04"]
    assert [t.alias for t in cfg.target_teams()] == ["team-01", "team-03"]
