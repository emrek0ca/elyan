from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from core.gateway import server as gateway_server


@pytest.mark.asyncio
async def test_handle_skill_refresh_rebuilds_registry(monkeypatch):
    calls = {"refresh": 0}

    def fake_refresh():
        calls["refresh"] += 1

    monkeypatch.setattr(gateway_server.skill_registry, "refresh", fake_refresh)
    monkeypatch.setattr(gateway_server, "push_activity", lambda *_a, **_k: None)

    srv = gateway_server.ElyanGatewayServer.__new__(gateway_server.ElyanGatewayServer)
    resp = await gateway_server.ElyanGatewayServer.handle_skill_refresh(srv, SimpleNamespace())
    payload = json.loads(resp.text)

    assert payload["ok"] is True
    assert payload["skills"] >= 0
    assert payload["workflows"] >= 0
    assert calls["refresh"] == 1
