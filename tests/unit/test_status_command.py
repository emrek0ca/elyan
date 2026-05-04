from __future__ import annotations

import json
import sys
import types
from types import SimpleNamespace

from cli.commands import status as status_cmd


class FakeAutopilot:
    def get_status(self):
        return {
            "running": True,
            "last_tick_reason": "heartbeat",
        }


class FakeOperatorStatus:
    def get_status(self):
        return {
            "status": "healthy",
            "summary": {
                "mobile_dispatch": {"status": "healthy"},
                "computer_use": {"status": "healthy"},
                "internet_reach": {"status": "healthy"},
                "document_ingest": {"status": "healthy"},
                "speed_runtime": {"current_lane": "turbo_lane"},
                "model_runtime": {
                    "execution_mode": "local_first",
                    "environment": {"torch_available": True},
                },
            },
        }


def test_status_prints_autopilot(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".elyan").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".elyan" / "elyan.json").write_text("{}", encoding="utf-8")

    fake_module = types.ModuleType("core.autopilot")
    fake_module.get_autopilot = lambda: FakeAutopilot()
    monkeypatch.setitem(sys.modules, "core.autopilot", fake_module)
    fake_operator_module = types.ModuleType("core.operator_status")
    fake_operator_module.get_operator_status_sync = lambda: FakeOperatorStatus().get_status()
    monkeypatch.setitem(sys.modules, "core.operator_status", fake_operator_module)

    status_cmd.run_status(SimpleNamespace(deep=False, json=False))
    out = capsys.readouterr().out
    assert "Lansman:" in out
    assert "elyan setup --force" in out
    assert "Kurulumdan UI'ya" in out
    assert "bootstrap-owner -> login -> auth/me -> logout" in out
    assert "Autopilot:" in out
    assert "ACTIVE" in out
    assert "Operator:" in out
    assert "torch yes" in out


def test_status_json_includes_launch_readiness(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    elyan_dir = tmp_path / ".elyan"
    elyan_dir.mkdir(parents=True, exist_ok=True)
    (elyan_dir / "elyan.json").write_text(
        json.dumps(
            {
                "models": {
                    "default": {
                        "provider": "ollama",
                        "model": "llama3.2:3b",
                    }
                },
                "channels": [{"enabled": True}],
                "cron": [{"enabled": True}],
            }
        ),
        encoding="utf-8",
    )

    fake_module = types.ModuleType("core.autopilot")
    fake_module.get_autopilot = lambda: FakeAutopilot()
    monkeypatch.setitem(sys.modules, "core.autopilot", fake_module)
    fake_operator_module = types.ModuleType("core.operator_status")
    fake_operator_module.get_operator_status_sync = lambda: FakeOperatorStatus().get_status()
    monkeypatch.setitem(sys.modules, "core.operator_status", fake_operator_module)

    status_cmd.run_status(SimpleNamespace(deep=False, json=True))
    payload = json.loads(capsys.readouterr().out)

    assert payload["launch"]["ready"] is True
    assert payload["launch"]["next_action"] == "elyan launch"
    assert payload["channels"]["active"] == 1
    assert "platforms" in payload
    assert "skills" in payload
    assert isinstance(payload["skills"], dict)
    assert payload["operator"]["status"] == "healthy"
    assert payload["operator"]["summary"]["model_runtime"]["execution_mode"] == "local_first"


def test_status_uses_platform_summary_for_connected_channels(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    elyan_dir = tmp_path / ".elyan"
    elyan_dir.mkdir(parents=True, exist_ok=True)
    (elyan_dir / "elyan.json").write_text('{"channels":[{"enabled":true}]}', encoding="utf-8")

    fake_module = types.ModuleType("core.autopilot")
    fake_module.get_autopilot = lambda: FakeAutopilot()
    monkeypatch.setitem(sys.modules, "core.autopilot", fake_module)
    fake_operator_module = types.ModuleType("core.operator_status")
    fake_operator_module.get_operator_status_sync = lambda: FakeOperatorStatus().get_status()
    monkeypatch.setitem(sys.modules, "core.operator_status", fake_operator_module)

    monkeypatch.setattr(
        "cli.commands.platforms._build_payload",
        lambda: {"summary": {"configured_channels": 1, "connected_channels": 0}, "surfaces": []},
        raising=False,
    )

    status_cmd.run_status(SimpleNamespace(deep=False, json=True))
    payload = json.loads(capsys.readouterr().out)

    assert payload["channels"]["connected"] == 0
    assert payload["channels"]["configured"] == 1


def test_status_text_prints_skill_issues(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    elyan_dir = tmp_path / ".elyan"
    elyan_dir.mkdir(parents=True, exist_ok=True)
    (elyan_dir / "elyan.json").write_text("{}", encoding="utf-8")

    fake_module = types.ModuleType("core.autopilot")
    fake_module.get_autopilot = lambda: FakeAutopilot()
    monkeypatch.setitem(sys.modules, "core.autopilot", fake_module)
    fake_operator_module = types.ModuleType("core.operator_status")
    fake_operator_module.get_operator_status_sync = lambda: FakeOperatorStatus().get_status()
    monkeypatch.setitem(sys.modules, "core.operator_status", fake_operator_module)
    monkeypatch.setattr(
        "cli.commands.status._skill_summary",
        lambda: {"installed": 4, "enabled": 3, "issues": 2, "runtime_ready": 2},
        raising=False,
    )

    status_cmd.run_status(SimpleNamespace(deep=False, json=False))
    out = capsys.readouterr().out

    assert "Skills:" in out
    assert "3/4 aktif" in out
    assert "2 skill attention istiyor" in out
