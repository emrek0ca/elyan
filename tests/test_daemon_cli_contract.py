"""Daemon + CLI sözleşme testleri — GUI'siz MVP yüzeyi.

Kapsam: durum özeti STATE şemasını doğru okur, PID dosyası ölü süreçte
temizlenir, CLI komut ağacı tam, servis dosyaları doğru komutu içerir,
QR terminal render'ı çalışır, desktop_limit_reached self-heal'i yalnız
bayat masaüstü cihazlarını düşürür.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from runtime import state_store


def _isolate_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(state_store, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(state_store, "STATE_PATH", tmp_path / "elyan_state.json")
    monkeypatch.setattr(state_store, "LEGACY_STATE_PATH", tmp_path / "legacy.json")
    try:
        state_store.invalidate_cache()
    except AttributeError:
        pass


def test_runtime_status_summary_reads_real_schema(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    import runtime.daemon as daemon

    monkeypatch.setattr(daemon, "PID_PATH", tmp_path / "daemon.pid")
    state_store.update_state(
        {
            "account": {"accessToken": "tok", "email": "test@elyan.dev"},
            "runtime": {
                "runtimeToken": "rt",
                "lifecycleState": "ready",
                "websocketConnected": True,
                "lastErrorCode": "",
            },
            "taskInbox": {
                "items": [
                    {"id": "t1", "title": "Sunum", "status": "running"},
                    {"id": "t2", "title": "Eski", "status": "completed"},
                ]
            },
        }
    )

    summary = daemon.runtime_status_summary()

    assert summary["signedIn"] is True
    assert summary["email"] == "test@elyan.dev"
    assert summary["paired"] is True
    assert summary["lifecycleState"] == "ready"
    assert summary["websocketConnected"] is True
    assert len(summary["activeTasks"]) == 1
    assert summary["activeTasks"][0]["id"] == "t1"


def test_read_daemon_pid_ignores_dead_process(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import runtime.daemon as daemon

    pid_path = tmp_path / "daemon.pid"
    monkeypatch.setattr(daemon, "PID_PATH", pid_path)

    assert daemon.read_daemon_pid() == 0  # dosya yok
    pid_path.write_text("999999")  # ölü pid
    monkeypatch.setattr(daemon, "_pid_alive", lambda pid: False)
    assert daemon.read_daemon_pid() == 0
    monkeypatch.setattr(daemon, "_pid_alive", lambda pid: True)
    assert daemon.read_daemon_pid() == 999999


def test_cli_parser_covers_mvp_commands() -> None:
    from cli.main import build_parser

    parser = build_parser()
    for command in (
        ["pair"],
        ["login"],
        ["logout"],
        ["start"],
        ["stop"],
        ["restart"],
        ["run"],
        ["status"],
        ["tasks"],
        ["doctor"],
        ["service", "install"],
        ["service", "uninstall"],
        ["version"],
    ):
        args = parser.parse_args(command)
        assert callable(args.func), command


def test_service_definitions_run_daemon_module() -> None:
    from cli.main import _launchd_plist, _systemd_unit

    plist = _launchd_plist()
    assert "runtime.daemon" in plist
    assert "RunAtLoad" in plist
    unit = _systemd_unit()
    assert "runtime.daemon" in unit
    assert "Restart=on-failure" in unit


def test_render_qr_produces_block_matrix() -> None:
    from cli.main import _render_qr

    rendered = _render_qr("elyan://pair?sessionId=abc&pairingCode=123456")
    assert len(rendered.splitlines()) > 10
    assert any(ch in rendered for ch in "█▀▄")


class _FakeResult:
    def __init__(self, ok: bool, data: dict[str, Any] | None = None, error: str = "") -> None:
        self.ok = ok
        self.data = data or {}
        self.error = error

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "data": self.data, "error": self.error}


def test_stale_desktop_self_heal_only_removes_stale_desktops(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    import runtime.bridge as bridge_mod

    runtime_bridge = bridge_mod.RuntimeBridge()
    deactivated: list[str] = []

    fake_backend = SimpleNamespace(
        mobile_bootstrap=lambda: _FakeResult(
            True,
            {
                "devices": [
                    {"id": "ios-1", "type": "mobile", "platform": "ios", "lastSeenAt": "2026-07-09T10:00:00Z"},
                    {"id": "mac-eski", "type": "desktop", "platform": "macos", "lastSeenAt": "2026-07-01T10:00:00Z"},
                    {"id": "mac-canli", "type": "desktop", "platform": "macos", "lastSeenAt": "2099-01-01T00:00:00Z"},
                ]
            },
        ),
        device_deactivate=lambda device_id: (deactivated.append(device_id), _FakeResult(True))[1],
    )
    monkeypatch.setattr(runtime_bridge, "backend", fake_backend)
    monkeypatch.setattr(runtime_bridge, "_log_backend_result", lambda *a, **k: None)

    removed = runtime_bridge._deactivate_stale_desktop_devices()

    assert removed is True
    assert deactivated == ["mac-eski"]  # mobil ve canlı masaüstü dokunulmadı


def test_self_pair_retries_after_desktop_limit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    import runtime.bridge as bridge_mod

    runtime_bridge = bridge_mod.RuntimeBridge()
    calls = {"create": 0}

    def fake_create(_payload: dict[str, Any]) -> _FakeResult:
        calls["create"] += 1
        if calls["create"] == 1:
            return _FakeResult(False, error="desktop_limit_reached")
        return _FakeResult(True, {"sessionId": "s1", "pairingCode": "123456"})

    fake_backend = SimpleNamespace(
        runtime_register_identity_error=lambda: {"code": "RUNTIME_AUTH_MISSING"},
        pairing_create_session=fake_create,
        pairing_claim_session=lambda sid, payload: _FakeResult(True, {"status": "claimed"}),
        pairing_get_session=lambda sid: _FakeResult(True, {"status": "claimed"}),
        mobile_bootstrap=lambda: _FakeResult(
            True,
            {"devices": [{"id": "mac-eski", "type": "desktop", "lastSeenAt": "2026-07-01T10:00:00Z"}]},
        ),
        device_deactivate=lambda device_id: _FakeResult(True),
    )
    monkeypatch.setattr(runtime_bridge, "backend", fake_backend)
    monkeypatch.setattr(runtime_bridge, "_log_backend_result", lambda *a, **k: None)
    monkeypatch.setattr(runtime_bridge, "_runtime_register_identity_error", lambda: {"code": "RUNTIME_AUTH_MISSING"})
    monkeypatch.setattr(runtime_bridge, "ensure_runtime_registered", lambda: {"ok": True})
    monkeypatch.setattr(runtime_bridge, "pairing_get_session", lambda sid: {"ok": True, "registration": {"ok": True}})

    outcome = runtime_bridge.pairing_self_pair({})

    assert calls["create"] == 2  # limit → self-heal → yeniden dene
    assert outcome.get("ok") is True
    assert outcome.get("stage") == "registered"
