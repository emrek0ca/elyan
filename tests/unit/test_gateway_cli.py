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
