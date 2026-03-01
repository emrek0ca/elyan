import json

import pytest

from core.gateway import server as gateway_server


class _Req:
    def __init__(self, data):
        self._data = data

    async def json(self):
        return self._data


class _Agent:
    def __init__(self, response: str = "ok"):
        self.response = response
        self.calls = []

    async def process(self, text, notify=None, attachments=None, channel="cli", metadata=None):
        self.calls.append({
            "text": text,
            "channel": channel,
            "metadata": metadata,
        })
        return self.response


@pytest.mark.asyncio
async def test_handle_external_message_wait_returns_agent_response(monkeypatch):
    monkeypatch.setattr(gateway_server, "push_activity", lambda *_a, **_k: None)

    srv = gateway_server.ElyanGatewayServer.__new__(gateway_server.ElyanGatewayServer)
    srv.agent = _Agent(response="tamam")

    req = _Req({"text": "merhaba", "channel": "dashboard", "wait": True, "timeout_s": 30})
    resp = await gateway_server.ElyanGatewayServer.handle_external_message(srv, req)

    assert resp.status == 200
    payload = json.loads(resp.text)
    assert payload["status"] == "ok"
    assert payload["response"] == "tamam"
    assert srv.agent.calls and srv.agent.calls[0]["channel"] == "dashboard"


@pytest.mark.asyncio
async def test_handle_external_message_async_returns_processing(monkeypatch):
    monkeypatch.setattr(gateway_server, "push_activity", lambda *_a, **_k: None)

    created = []

    def _fake_create_task(coro):
        created.append(coro)

        class _DummyTask:
            pass

        return _DummyTask()

    monkeypatch.setattr(gateway_server.asyncio, "create_task", _fake_create_task)

    srv = gateway_server.ElyanGatewayServer.__new__(gateway_server.ElyanGatewayServer)
    srv.agent = _Agent(response="tamam")

    req = _Req({"text": "test", "channel": "api", "wait": False})
    resp = await gateway_server.ElyanGatewayServer.handle_external_message(srv, req)

    assert resp.status == 200
    payload = json.loads(resp.text)
    assert payload["status"] == "processing"
    assert created

    # Ensure no dangling coroutine warning in test process.
    for coro in created:
        coro.close()
