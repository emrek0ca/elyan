from __future__ import annotations

from types import SimpleNamespace

import pytest

from cli.commands import autopilot as autopilot_cmd


class FakeAutopilot:
    def __init__(self):
        self.started = 0
        self.stopped = 0
        self.ticks: list[str] = []

    def get_status(self):
        return {
            "enabled": True,
            "running": self.started > self.stopped,
            "tick_count": len(self.ticks),
            "last_tick_reason": self.ticks[-1] if self.ticks else "",
            "last_actions": [{"kind": "maintenance", "status": "completed"}] if self.ticks else [],
            "maintenance": {"tasks_completed": 1, "total_freed_mb": 3.0},
            "predictive": {"monitoring_active": True, "active_predictions": 0},
            "automation": {"summary": {"healthy": 1, "failing": 0}},
        }

    async def start(self):
        self.started += 1
        return self.get_status()

    async def stop(self):
        self.stopped += 1
        return self.get_status()

    async def run_tick(self, **kwargs):
        self.ticks.append(kwargs.get("reason") or "manual")
        return self.get_status()


@pytest.mark.parametrize("action", ["status", "start", "stop", "tick"])
def test_autopilot_cli_actions(monkeypatch, capsys, action):
    fake = FakeAutopilot()
    monkeypatch.setattr(autopilot_cmd, "_gateway_running", lambda port: False)
    monkeypatch.setattr(autopilot_cmd, "_local_autopilot", lambda: fake)

    result = autopilot_cmd.run_autopilot(SimpleNamespace(action=action, port=18789, reason="manual_test"))
    assert result == 0

    out = capsys.readouterr().out
    assert "enabled" in out
    if action == "start":
        assert fake.started == 1
    elif action == "stop":
        assert fake.stopped == 1
    elif action == "tick":
        assert fake.ticks == ["manual_test"]
