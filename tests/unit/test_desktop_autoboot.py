from pathlib import Path

from cli.commands import desktop


def test_ensure_gateway_ready_skips_start_when_healthy(monkeypatch):
    calls = {"start": 0}

    class _Gateway:
        @staticmethod
        def _fetch_gateway_status(port):
            return {"ok": True, "data": {"status": "online", "port": port}}

        @staticmethod
        def start_gateway(daemon=False, port=None):
            calls["start"] += 1

    monkeypatch.setattr(desktop, "time", type("_T", (), {"time": staticmethod(lambda: 100.0), "sleep": staticmethod(lambda _: None)}))
    monkeypatch.setattr(__import__("cli.commands", fromlist=["gateway"]), "gateway", _Gateway)

    desktop._ensure_gateway_ready(Path("/tmp/project"))

    assert calls["start"] == 0


def test_ensure_gateway_ready_starts_gateway_when_unhealthy(monkeypatch):
    state = {"count": 0, "start": 0}

    class _Gateway:
        @staticmethod
        def _fetch_gateway_status(port):
            state["count"] += 1
            return {"ok": state["count"] >= 3, "data": {"status": "online" if state["count"] >= 3 else "starting", "port": port}}

        @staticmethod
        def start_gateway(daemon=False, port=None):
            state["start"] += 1

    class _Time:
        current = 100.0

        @staticmethod
        def time():
            _Time.current += 0.2
            return _Time.current

        @staticmethod
        def sleep(_seconds):
            _Time.current += 0.5

    monkeypatch.setattr(desktop, "time", _Time)
    monkeypatch.setattr(__import__("cli.commands", fromlist=["gateway"]), "gateway", _Gateway)

    desktop._ensure_gateway_ready(Path("/tmp/project"))

    assert state["start"] == 1


def test_open_desktop_prefers_canonical_shell_without_legacy_ui(monkeypatch, tmp_path):
    root = tmp_path
    desktop_dir = root / "apps" / "desktop"
    desktop_dir.mkdir(parents=True)
    (desktop_dir / "package.json").write_text("{}", encoding="utf-8")
    (desktop_dir / "node_modules").mkdir()

    calls = {"spawn": None}

    monkeypatch.setattr(desktop, "_project_root", lambda: root)
    monkeypatch.setattr(desktop, "_ensure_gateway_ready", lambda _root: None)
    monkeypatch.setattr(desktop, "_tauri_binary_candidates", lambda _root: [])
    monkeypatch.setattr(desktop.shutil, "which", lambda name: "/opt/homebrew/bin/npm" if name == "npm" else None)
    monkeypatch.setattr(desktop, "_spawn", lambda cmd, cwd, detached, project_root: calls.__setitem__("spawn", (cmd, cwd, detached, project_root)) or 0)

    result = desktop.open_desktop(detached=False)

    assert result == 0
    assert calls["spawn"] is not None
    assert calls["spawn"][0][:3] == ["npm", "run", "tauri:dev"]


def test_open_desktop_fails_when_canonical_shell_missing(monkeypatch, tmp_path):
    root = tmp_path
    (root / "apps" / "desktop").mkdir(parents=True)

    calls = {"spawn": None}

    monkeypatch.setattr(desktop, "_project_root", lambda: root)
    monkeypatch.setattr(desktop, "_ensure_gateway_ready", lambda _root: None)
    monkeypatch.setattr(desktop, "_tauri_binary_candidates", lambda _root: [])
    monkeypatch.setattr(desktop, "_spawn", lambda cmd, cwd, detached, project_root: calls.__setitem__("spawn", (cmd, cwd, detached, project_root)) or 0)

    result = desktop.open_desktop(detached=False)

    assert result == 1
    assert calls["spawn"] is None


def test_spawn_uses_login_home_rust_toolchain_when_home_is_overridden(monkeypatch, tmp_path):
    root = tmp_path
    login_home = tmp_path / "login-home"
    login_home.mkdir()

    captured = {}

    def fake_call(cmd, cwd=None, env=None):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        captured["env"] = env
        return 0

    monkeypatch.setattr(desktop, "_login_home_dir", lambda: login_home)
    monkeypatch.setattr(desktop.subprocess, "call", fake_call)
    monkeypatch.setenv("HOME", str(tmp_path / "tmp-home"))
    monkeypatch.delenv("RUSTUP_HOME", raising=False)
    monkeypatch.delenv("CARGO_HOME", raising=False)

    result = desktop._spawn(["npm", "run", "tauri:dev"], cwd=root, detached=False, project_root=root)

    assert result == 0
    assert captured["cmd"] == ["npm", "run", "tauri:dev"]
    assert captured["cwd"] == str(root)
    assert captured["env"]["RUSTUP_HOME"] == str(login_home / ".rustup")
    assert captured["env"]["CARGO_HOME"] == str(login_home / ".cargo")
