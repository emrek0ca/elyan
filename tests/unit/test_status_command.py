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


def test_status_prints_autopilot(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".elyan").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".elyan" / "elyan.json").write_text("{}", encoding="utf-8")

    fake_module = types.ModuleType("core.autopilot")
    fake_module.get_autopilot = lambda: FakeAutopilot()
    monkeypatch.setitem(sys.modules, "core.autopilot", fake_module)

    status_cmd.run_status(SimpleNamespace(deep=False, json=False))
    out = capsys.readouterr().out
    assert "Lansman:" in out
    assert "elyan setup --force" in out
    assert "Autopilot:" in out
    assert "ACTIVE" in out


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

    status_cmd.run_status(SimpleNamespace(deep=False, json=True))
    payload = json.loads(capsys.readouterr().out)

    assert payload["launch"]["ready"] is True
    assert payload["launch"]["next_action"] == "elyan launch"
    assert payload["channels"]["active"] == 1
