"""Unit tests for CLI gateway status/health helpers."""

import json
from pathlib import Path

from cli.commands import gateway


def test_gateway_status_json_contains_runtime_data(monkeypatch, tmp_path: Path, capsys):
    monkeypatch.setattr(gateway, "_running_gateway_pid", lambda port: 12345)
    monkeypatch.setattr(gateway, "_write_pidfile", lambda pid: None)
    monkeypatch.setattr(
        gateway,
        "_safe_process_info",
        lambda pid: {"pid": pid, "running": True, "memory_mb": 10.5, "uptime_s": 12},
    )
    monkeypatch.setattr(
        gateway,
        "_fetch_gateway_status",
        lambda port: {
            "ok": True,
            "data": {
                "status": "online",
                "adapters": {"telegram": "connected"},
                "adapter_health": {"telegram": {"retries": 0, "failures": 0}},
            },
        },
    )
    monkeypatch.setattr(
        gateway,
        "_fetch_gateway_channels",
        lambda port: {
            "ok": True,
            "data": {"channels": [{"type": "telegram", "status": "connected"}]},
        },
    )

    gateway.gateway_status(as_json=True, port=18789)
    out = capsys.readouterr().out.strip()
    payload = json.loads(out)
    assert payload["running"] is True
    assert payload["runtime_available"] is True
    assert payload["runtime"]["adapters"]["telegram"] == "connected"
    assert payload["channels_available"] is True
    assert payload["channels"][0]["type"] == "telegram"


def test_gateway_health_unreachable_json(monkeypatch, capsys):
    monkeypatch.setattr(
        gateway,
        "_fetch_gateway_status",
        lambda port: {"ok": False, "error": "connection refused"},
    )
    monkeypatch.setattr(gateway, "_running_gateway_pid", lambda port: None)

    gateway.gateway_health(as_json=True, port=18789)
    out = capsys.readouterr().out.strip()
    payload = json.loads(out)
    assert payload["healthy"] is False
    assert payload["status"] == "unreachable"
    assert "connection refused" in payload["error"]


def test_gateway_health_reports_starting_when_process_exists(monkeypatch, capsys):
    monkeypatch.setattr(
        gateway,
        "_fetch_gateway_status",
        lambda port: {"ok": False, "error": "connection refused"},
    )
    monkeypatch.setattr(gateway, "_running_gateway_pid", lambda port: 45678)

    gateway.gateway_health(as_json=True, port=18789)
    out = capsys.readouterr().out.strip()
    payload = json.loads(out)
    assert payload["healthy"] is False
    assert payload["status"] == "starting"
    assert payload["pid"] == 45678


def test_gateway_logs_filters_by_level_and_term(monkeypatch, tmp_path: Path, capsys):
    log_file = tmp_path / "gateway.log"
    log_file.write_text(
        "\n".join(
            [
                "2026-02-19 10:00:00 | gateway | INFO | started",
                "2026-02-19 10:00:01 | gateway | ERROR | connection refused",
                "2026-02-19 10:00:02 | gateway | INFO | ready",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(gateway, "LOG_FILE", log_file)

    gateway.gateway_logs(tail=10, level="error", filter_term="connection")
    out = capsys.readouterr().out
    assert "ERROR" in out
    assert "connection refused" in out
    assert "started" not in out


def test_find_listener_pids_uses_lsof_fallback(monkeypatch):
    monkeypatch.setattr(gateway.psutil, "net_connections", lambda kind="tcp": (_ for _ in ()).throw(RuntimeError("no access")))

    class _Result:
        returncode = 0
        stdout = "111\n222\n"
        stderr = ""

    monkeypatch.setattr(gateway.subprocess, "run", lambda *a, **k: _Result())
    pids = gateway._find_listener_pids(18789)
    assert pids == [111, 222]


def test_restart_gateway_calls_stop_then_start(monkeypatch):
    calls = []
    monkeypatch.setattr(gateway, "stop_gateway", lambda port=None: calls.append(("stop", port)))
    monkeypatch.setattr(gateway, "_is_port_listening", lambda port: False)
    monkeypatch.setattr(gateway, "_is_launchd_service_loaded", lambda: False)
    monkeypatch.setattr(gateway, "start_gateway", lambda daemon=False, port=None: calls.append(("start", port, daemon)))

    gateway.restart_gateway(daemon=True, port=18789)
    assert calls[0] == ("stop", 18789)
    assert calls[1] == ("start", 18789, True)


def test_restart_gateway_uses_launchd_when_loaded(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(gateway, "_is_launchd_service_loaded", lambda: True)
    monkeypatch.setattr(gateway, "_kickstart_launchd_service", lambda: (True, None))
    monkeypatch.setattr(gateway, "_wait_until_gateway_ready", lambda port, timeout_s=20.0: True)
    monkeypatch.setattr(gateway, "_running_gateway_pid", lambda port: 98765)
    monkeypatch.setattr(gateway, "_write_pidfile", lambda pid: calls.append(("write_pid", pid)))
    monkeypatch.setattr(gateway, "stop_gateway", lambda port=None: calls.append(("stop", port)))
    monkeypatch.setattr(gateway, "start_gateway", lambda daemon=False, port=None: calls.append(("start", port, daemon)))

    gateway.restart_gateway(daemon=True, port=18789)
    out = capsys.readouterr().out

    assert ("write_pid", 98765) in calls
    assert ("stop", 18789) not in calls
    assert ("start", 18789, True) not in calls
    assert "launchd servisi üzerinden yeniden başlatılıyor" in out


def test_gateway_reload_posts_sync(monkeypatch, capsys):
    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"ok": true, "message": "Senkronizasyon tamamlandi (2 adapter)."}'

    monkeypatch.setattr(gateway.urllib.request, "urlopen", lambda req, timeout=5: _Resp())
    gateway.gateway_reload(port=18789, as_json=False)
    out = capsys.readouterr().out
    assert "Senkronizasyon tamamlandi" in out
