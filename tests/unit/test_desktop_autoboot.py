from pathlib import Path

from cli.commands import desktop


def test_ensure_gateway_ready_skips_start_when_healthy(monkeypatch):
    calls = {"start": 0}

    class _Gateway:
        @staticmethod
        def _fetch_gateway_launch_health(port):
            return {"ok": True, "data": {"ok": True, "port": port, "readiness": {"launch_ready": True, "launch_blockers": []}}}

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
        def _fetch_gateway_launch_health(port):
            state["count"] += 1
            return {"ok": state["count"] >= 3, "data": {"ok": state["count"] >= 3, "port": port, "readiness": {"launch_ready": state["count"] >= 3, "launch_blockers": []}}}

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
