"""Daemon + CLI sözleşme testleri — GUI'siz MVP yüzeyi.

Kapsam: durum özeti STATE şemasını doğru okur, PID dosyası ölü süreçte
temizlenir, CLI komut ağacı tam, servis dosyaları doğru komutu içerir,
QR terminal render'ı çalışır, desktop_limit_reached self-heal'i yalnız
bayat masaüstü cihazlarını düşürür.
"""

from __future__ import annotations

import json
import os
import threading
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
    daemon.PID_PATH.write_text(str(12345))
    monkeypatch.setattr(daemon, "_pid_alive", lambda _pid: True)
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


def test_runtime_status_summary_does_not_report_persisted_ready_when_daemon_stopped(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    import runtime.daemon as daemon

    monkeypatch.setattr(daemon, "PID_PATH", tmp_path / "daemon.pid")
    state_store.update_state(
        {
            "runtime": {
                "runtimeToken": "stale-runtime-token",
                "lifecycleState": "ready",
                "websocketConnected": True,
            }
        }
    )

    summary = daemon.runtime_status_summary()

    assert summary["pid"] == 0
    assert summary["lifecycleState"] == "offline"
    assert summary["websocketConnected"] is False
    assert summary["paired"] is True


def test_daemon_start_invalidates_transport_truth_from_previous_process(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    import runtime.daemon as daemon

    state_store.update_state(
        {
            "runtime": {
                "runtimeToken": "persisted-runtime-token",
                "deviceId": "11111111-1111-4111-8111-111111111111",
                "deviceSecret": "x" * 32,
                "ready": True,
                "lifecycleState": "ready",
                "websocketConnected": True,
            },
            "pairing": {"realtimeReady": True},
        }
    )

    daemon._mark_daemon_transport_starting()

    snapshot = state_store.snapshot()
    assert snapshot["runtime"]["runtimeToken"] == "persisted-runtime-token"
    assert snapshot["runtime"]["ready"] is False
    assert snapshot["runtime"]["websocketConnected"] is False
    assert snapshot["runtime"]["lifecycleState"] == "runtime_connecting"
    assert snapshot["pairing"]["realtimeReady"] is False


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


def test_daemon_keeper_honors_pid_scoped_stop_marker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import runtime.daemon as daemon

    stop_path = tmp_path / "daemon.stop"
    monkeypatch.setattr(daemon, "STOP_PATH", stop_path)
    instance = object.__new__(daemon.ElyanDaemon)
    instance._stop = threading.Event()
    stop_path.write_text(str(os.getpid()))

    thread = threading.Thread(target=instance.run_forever)
    thread.start()
    thread.join(timeout=2)

    assert thread.is_alive() is False
    assert instance._stop.is_set() is True


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
        ["doctor", "--fix"],
        ["service", "install"],
        ["service", "uninstall"],
        ["version"],
    ):
        args = parser.parse_args(command)
        assert callable(args.func), command
    assert parser.parse_args(["doctor", "--fix"]).fix is True
    assert parser.parse_args(["doctor"]).fix is False


def test_daemon_run_forever_forces_reconnect_on_wake_gap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Uyku/askı sonrası duvar-saati atlaması hemen yeniden bağlanmayı tetikler."""
    import runtime.daemon as daemon

    monkeypatch.setattr(daemon, "STOP_PATH", tmp_path / "daemon.stop")
    instance = object.__new__(daemon.ElyanDaemon)
    instance._stop = threading.Event()

    calls: list[str] = []

    def _reconnect() -> dict[str, Any]:
        calls.append("reconnect")
        instance._stop.set()  # tek iterasyondan sonra döngüyü durdur
        return {"ok": True}

    instance.bridge = SimpleNamespace(force_runtime_reconnect=_reconnect)
    monkeypatch.setattr(instance._stop, "wait", lambda _timeout: False)
    # İlk çağrı last_wall'ı kurar; ikinci çağrı büyük atlama (uyku) simüle eder.
    wall_values = iter([1_000.0, 2_000.0])
    monkeypatch.setattr(daemon.time, "time", lambda: next(wall_values, 2_000.0))
    monkeypatch.setattr(
        daemon.state_store, "snapshot", lambda: {"runtime": {"lifecycleState": "ready"}}
    )

    instance.run_forever()

    assert calls == ["reconnect"]


def test_daemon_run_forever_skips_reconnect_without_wake_gap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Küçük tik aralığında (uyku yok) ve bağlıyken yeniden bağlanma tetiklenmez."""
    import runtime.daemon as daemon

    monkeypatch.setattr(daemon, "STOP_PATH", tmp_path / "daemon.stop")
    instance = object.__new__(daemon.ElyanDaemon)
    instance._stop = threading.Event()

    calls: list[str] = []
    instance.bridge = SimpleNamespace(
        force_runtime_reconnect=lambda: calls.append("reconnect") or {"ok": True}
    )

    tick = {"n": 0}

    def _wait(_timeout: float) -> bool:
        tick["n"] += 1
        if tick["n"] >= 2:
            instance._stop.set()
        return False

    monkeypatch.setattr(instance._stop, "wait", _wait)
    wall_values = iter([1_000.0, 1_001.0, 1_002.0])
    monkeypatch.setattr(daemon.time, "time", lambda: next(wall_values, 1_002.0))
    monkeypatch.setattr(
        daemon.state_store, "snapshot", lambda: {"runtime": {"lifecycleState": "ready"}}
    )

    instance.run_forever()

    assert calls == []


def test_stop_daemon_clears_stale_pid_after_forced_shutdown(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import cli.main as cli

    pid_path = tmp_path / "daemon.pid"
    stop_path = tmp_path / "daemon.stop"
    pid_path.write_text("12345")
    kills: list[tuple[int, int]] = []
    monkeypatch.setattr(cli, "PID_PATH", pid_path)
    monkeypatch.setattr(cli, "STOP_PATH", stop_path)
    monkeypatch.setattr(cli, "_daemon_running", lambda: 12345)
    monkeypatch.setattr(cli.os, "kill", lambda pid, sig: kills.append((pid, sig)))
    monkeypatch.setattr(cli.time, "sleep", lambda _seconds: None)

    assert cli._stop_daemon(quiet=True) is True
    assert kills == [(12345, 15), (12345, 9)]
    assert pid_path.exists() is False
    assert stop_path.exists() is False


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
