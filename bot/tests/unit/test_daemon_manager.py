"""Unit tests for daemon manager command resolution."""

import sys
from pathlib import Path

from cli.daemon import DaemonManager


def test_program_arguments_prefers_project_venv_binary(tmp_path: Path):
    dm = DaemonManager()
    dm.project_root = tmp_path

    elyan_bin = tmp_path / ".venv" / "bin" / "elyan"
    elyan_bin.parent.mkdir(parents=True, exist_ok=True)
    elyan_bin.write_text("#!/bin/sh\n", encoding="utf-8")

    args = dm._program_arguments()
    assert args[0] == str(elyan_bin)
    assert args[1:] == ["gateway", "start"]


def test_program_arguments_falls_back_to_module(monkeypatch):
    dm = DaemonManager()
    dm.project_root = Path("/nonexistent/project")
    monkeypatch.setattr("cli.daemon.shutil.which", lambda _: None)

    args = dm._program_arguments()
    assert args[:3] == [sys.executable, "-m", "cli.main"]
    assert args[3:] == ["gateway", "start"]
