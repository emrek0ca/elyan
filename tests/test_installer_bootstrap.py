from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

from desktop_installer import bootstrap


def _payload(tmp_path: Path, *, version: str = "9.8.7") -> Path:
    payload = tmp_path / "payload"
    app = payload / "app"
    (app / "cli").mkdir(parents=True)
    (app / "cli" / "main.py").write_text("", encoding="utf-8")
    (app / "package.json").write_text(json.dumps({"version": version}), encoding="utf-8")
    python = payload / "python" / "cpython-test" / "bin" / "python3"
    python.parent.mkdir(parents=True)
    python.write_text("#!/bin/sh\n", encoding="utf-8")
    python.chmod(0o755)
    return payload


def test_user_runtime_root_is_platform_safe(tmp_path: Path) -> None:
    assert bootstrap.user_runtime_root(platform_name="darwin", home=tmp_path) == (
        tmp_path / "Library" / "Application Support" / "Elyan" / "runtime"
    )
    assert bootstrap.user_runtime_root(
        platform_name="win32",
        home=tmp_path,
        environ={"LOCALAPPDATA": str(tmp_path / "Local")},
    ) == tmp_path / "Local" / "Elyan" / "runtime"
    assert bootstrap.user_runtime_root(
        platform_name="linux",
        home=tmp_path,
        environ={"XDG_DATA_HOME": str(tmp_path / "xdg")},
    ) == tmp_path / "xdg" / "elyan" / "runtime"


def test_install_payload_is_atomic_and_idempotent(tmp_path: Path) -> None:
    payload = _payload(tmp_path)
    destination_root = tmp_path / "installed"

    installed, copied = bootstrap.install_payload(payload, destination_root)
    assert copied is True
    assert installed == destination_root / "9.8.7"
    assert bootstrap.find_portable_python(installed).is_file()
    marker = json.loads((installed / ".elyan-payload.json").read_text(encoding="utf-8"))
    assert marker == {"contract": "elyan.portable-runtime.v1", "version": "9.8.7"}

    installed_again, copied_again = bootstrap.install_payload(payload, destination_root)
    assert installed_again == installed
    assert copied_again is False
    assert not list(destination_root.glob(".9.8.7-*"))


def test_write_cli_launcher_uses_installed_runtime(tmp_path: Path) -> None:
    installed = tmp_path / "runtime" / "1.0.0"
    python = installed / "python" / "cpython-test" / "bin" / "python3"
    python.parent.mkdir(parents=True)
    python.write_text("", encoding="utf-8")
    launcher = bootstrap.write_cli_launcher(installed, python, platform_name="linux", home=tmp_path)

    content = launcher.read_text(encoding="utf-8")
    assert str(installed / "app") in content
    assert str(python) in content
    assert os.access(launcher, os.X_OK)


def test_write_cli_launcher_replaces_symlink_without_modifying_target(tmp_path: Path) -> None:
    installed = tmp_path / "runtime" / "1.0.0"
    python = installed / "python" / "cpython-test" / "bin" / "python3"
    python.parent.mkdir(parents=True)
    python.write_text("", encoding="utf-8")
    existing_target = tmp_path / "source-launcher"
    existing_target.write_text("original\n", encoding="utf-8")
    launcher = tmp_path / ".local" / "bin" / "elyan"
    launcher.parent.mkdir(parents=True)
    launcher.symlink_to(existing_target)

    written = bootstrap.write_cli_launcher(installed, python, platform_name="linux", home=tmp_path)

    assert written == launcher
    assert not launcher.is_symlink()
    assert existing_target.read_text(encoding="utf-8") == "original\n"


def test_launch_cli_registers_daemon_after_success(monkeypatch, tmp_path: Path) -> None:
    installed = tmp_path / "runtime" / "1.0.0"
    app = installed / "app"
    app.mkdir(parents=True)
    python = installed / "python" / "cpython-test" / "bin" / "python3"
    python.parent.mkdir(parents=True)
    python.write_text("", encoding="utf-8")
    calls: list[tuple[list[str], dict[str, str]]] = []

    def fake_run(command, **kwargs):
        calls.append((list(command), dict(kwargs["env"])))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(bootstrap, "find_portable_python", lambda _root: python)
    monkeypatch.setattr(bootstrap.subprocess, "run", fake_run)

    assert bootstrap.launch_cli(installed, []) == 0
    assert calls[0][0] == [str(python), "-m", "cli"]
    assert calls[1][0] == [str(python), "-m", "cli", "service", "install"]
    assert calls[0][1]["ELYAN_INSTALL_ROOT"] == str(installed)
    assert calls[0][1]["ELYAN_INSTALLER_MANAGES_SERVICE"] == "1"
