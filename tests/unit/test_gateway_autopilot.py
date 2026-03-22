from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from core.gateway import server as gateway_server


class _FakeAutopilot:
    def __init__(self):
        self.started = 0
        self.stopped = 0
        self.ticks: list[str] = []

    def get_status(self):
        return {"running": self.started > self.stopped, "tick_count": len(self.ticks), "last_tick_reason": self.ticks[-1] if self.ticks else ""}

    async def start(self, agent=None, notify_callback=None):
        _ = (agent, notify_callback)
        self.started += 1
        return self.get_status()

    async def stop(self):
        self.stopped += 1
        return self.get_status()

    async def run_tick(self, *, agent=None, reason="scheduled"):
        _ = agent
        self.ticks.append(reason)
        return self.get_status()


class _Req:
    def __init__(self, payload=None):
        self._payload = payload or {}

    async def json(self):
        return dict(self._payload)


@pytest.mark.asyncio
async def test_autopilot_handlers_round_trip(monkeypatch):
    fake = _FakeAutopilot()
    monkeypatch.setattr(gateway_server, "get_autopilot", lambda: fake)

    srv = gateway_server.ElyanGatewayServer.__new__(gateway_server.ElyanGatewayServer)
    srv.agent = SimpleNamespace()
    srv.broadcast_to_dashboard = lambda *args, **kwargs: None

    resp = await gateway_server.ElyanGatewayServer.handle_autopilot_status(srv, SimpleNamespace())
    payload = json.loads(resp.text)
    assert payload["running"] is False

    resp = await gateway_server.ElyanGatewayServer.handle_autopilot_start(srv, SimpleNamespace())
    payload = json.loads(resp.text)
    assert payload["ok"] is True
    assert payload["autopilot"]["running"] is True

    resp = await gateway_server.ElyanGatewayServer.handle_autopilot_tick(srv, _Req({}))
    payload = json.loads(resp.text)
    assert payload["ok"] is True
    assert payload["autopilot"]["tick_count"] >= 1

    resp = await gateway_server.ElyanGatewayServer.handle_autopilot_stop(srv, SimpleNamespace())
    payload = json.loads(resp.text)
    assert payload["ok"] is True
    assert payload["autopilot"]["running"] is False
