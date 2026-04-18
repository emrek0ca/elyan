import asyncio

import pytest
from aiohttp import WSMsgType, web
from aiohttp.test_utils import TestClient, TestServer

from core.gateway import server as gateway_server
from core.gateway.adapters.webchat import WebChatAdapter
from core.gateway.response import UnifiedResponse


@pytest.mark.asyncio
async def test_dashboard_ws_accepts_auth_message_before_stream(monkeypatch):
    monkeypatch.setattr(gateway_server, "_is_loopback_request", lambda request: True)
    monkeypatch.setattr(gateway_server, "_dashboard_ws_clients", set())
    monkeypatch.setattr(gateway_server, "_activity_log", [])
    monkeypatch.setattr(gateway_server, "_tool_event_log", [])
    monkeypatch.setattr(gateway_server, "_cowork_event_log", [])

    seen_tokens: list[str] = []

    def _resolve_token(token: str):
        seen_tokens.append(token)
        return True, "", {"session_id": "admin"}

    monkeypatch.setattr(gateway_server, "_resolve_dashboard_ws_token", _resolve_token)

    srv = gateway_server.ElyanGatewayServer.__new__(gateway_server.ElyanGatewayServer)
    srv._require_user_session = lambda request, allow_cookie=True: (False, "user session required", {})
    srv._require_admin_access = lambda request, allow_cookie=True: (False, "admin token required")

    app = web.Application()

    async def _handler(request):
        return await gateway_server.ElyanGatewayServer.handle_dashboard_ws(srv, request)

    app.router.add_get("/ws/dashboard", _handler)

    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        ws = await client.ws_connect("/ws/dashboard")
        await ws.send_json({"type": "auth", "token": "ws-admin-token"})

        message = await ws.receive_json()
        assert message["type"] == "connected"
        assert seen_tokens == ["ws-admin-token"]

        await ws.close()
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_dashboard_ws_rejects_invalid_auth_message(monkeypatch):
    monkeypatch.setattr(gateway_server, "_is_loopback_request", lambda request: True)
    monkeypatch.setattr(gateway_server, "_dashboard_ws_clients", set())
    monkeypatch.setattr(gateway_server, "_activity_log", [])
    monkeypatch.setattr(gateway_server, "_tool_event_log", [])
    monkeypatch.setattr(gateway_server, "_cowork_event_log", [])
    monkeypatch.setattr(gateway_server, "_resolve_dashboard_ws_token", lambda token: (False, "invalid or expired session", {}))

    srv = gateway_server.ElyanGatewayServer.__new__(gateway_server.ElyanGatewayServer)
    srv._require_user_session = lambda request, allow_cookie=True: (False, "user session required", {})
    srv._require_admin_access = lambda request, allow_cookie=True: (False, "admin token required")

    app = web.Application()

    async def _handler(request):
        return await gateway_server.ElyanGatewayServer.handle_dashboard_ws(srv, request)

    app.router.add_get("/ws/dashboard", _handler)

    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        ws = await client.ws_connect("/ws/dashboard")
        await ws.send_json({"type": "auth", "token": "bad-token"})

        error_message = await ws.receive_json()
        assert error_message["type"] == "error"
        assert error_message["data"]["error"] == "invalid or expired session"

        close_message = await ws.receive()
        assert close_message.type in {WSMsgType.CLOSE, WSMsgType.CLOSING, WSMsgType.CLOSED}
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_node_ws_rejects_non_loopback(monkeypatch):
    monkeypatch.setattr(gateway_server, "_is_loopback_request", lambda request: False)

    srv = gateway_server.ElyanGatewayServer.__new__(gateway_server.ElyanGatewayServer)

    app = web.Application()

    async def _handler(request):
        return await gateway_server.ElyanGatewayServer.handle_node_ws(srv, request)

    app.router.add_get("/ws/node", _handler)

    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        resp = await client.get("/ws/node")
        payload = await resp.json()
        assert resp.status == 403
        assert payload["error"] == "node websocket is restricted to localhost"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_node_ws_registers_loopback_node(monkeypatch):
    monkeypatch.setattr(gateway_server, "_is_loopback_request", lambda request: True)
    monkeypatch.setattr(gateway_server, "push_activity", lambda *_args, **_kwargs: None)

    recorded: list[object] = []

    import core.runtime.node_manager as node_manager_module

    monkeypatch.setattr(
        node_manager_module.node_manager,
        "register_node",
        lambda info: recorded.append(info),
    )

    srv = gateway_server.ElyanGatewayServer.__new__(gateway_server.ElyanGatewayServer)
    srv.connected_nodes = {}
    srv.execution_hub = type("_Hub", (), {"resolve_action": lambda self, action_id, result: None})()

    app = web.Application()

    async def _handler(request):
        return await gateway_server.ElyanGatewayServer.handle_node_ws(srv, request)

    app.router.add_get("/ws/node", _handler)

    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        ws = await client.ws_connect("/ws/node")
        await ws.send_json(
            {
                "event_type": "NodeRegistered",
                "data": {
                    "node_id": "node-1",
                    "node_type": "desktop",
                    "capabilities": ["filesystem", "terminal"],
                    "hostname": "mac-mini",
                    "platform": "darwin",
                },
            }
        )
        await asyncio.sleep(0.05)

        assert "node-1" in srv.connected_nodes
        assert recorded and getattr(recorded[0], "node_id", "") == "node-1"

        await ws.close()
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_webchat_ws_binds_session_identity_and_targets_responses(monkeypatch):
    monkeypatch.setattr(gateway_server, "_is_loopback_request", lambda request: True)

    def _require_user_session(self, request, allow_cookie=True):
        query = request.rel_url.query
        session_id = str(query.get("session_id", "") or "").strip()
        user_id = str(query.get("user_id", "") or "").strip()
        if not session_id or not user_id:
            return False, "user session required", {}
        return True, "", {
            "session_id": session_id,
            "user_id": user_id,
            "display_name": f"User {user_id[-1]}",
            "workspace_id": "workspace-a",
        }

    monkeypatch.setattr(gateway_server.ElyanGatewayServer, "_require_user_session", _require_user_session)

    adapter = WebChatAdapter({})
    seen_messages: list[object] = []

    async def _capture_message(message):
        seen_messages.append(message)

    adapter.on_message(_capture_message)

    srv = gateway_server.ElyanGatewayServer.__new__(gateway_server.ElyanGatewayServer)
    srv.webchat_adapter = adapter

    app = web.Application()

    async def _handler(request):
        return await gateway_server.ElyanGatewayServer.handle_webchat_ws(srv, request)

    app.router.add_get("/ws/chat", _handler)

    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        ws1 = await client.ws_connect("/ws/chat?session_id=session-1&user_id=user-1")
        ws2 = await client.ws_connect("/ws/chat?session_id=session-2&user_id=user-2")

        await ws1.send_json({"text": "hello from one"})
        await ws2.send_json({"text": "hello from two"})
        await asyncio.sleep(0.05)

        assert len(seen_messages) == 2
        assert getattr(seen_messages[0], "channel_id", "") == "session-1"
        assert getattr(seen_messages[0], "user_id", "") == "user-1"
        assert getattr(seen_messages[1], "channel_id", "") == "session-2"
        assert getattr(seen_messages[1], "user_id", "") == "user-2"

        await adapter.send_message("session-1", UnifiedResponse(text="reply one", format="plain"))
        msg1 = await ws1.receive_json()
        assert msg1["text"] == "reply one"

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(ws2.receive(), timeout=0.2)

        await ws1.close()
        await ws2.close()
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_webchat_ws_rejects_without_user_session(monkeypatch):
    monkeypatch.setattr(gateway_server, "_is_loopback_request", lambda request: True)
    monkeypatch.setattr(
        gateway_server.ElyanGatewayServer,
        "_require_user_session",
        lambda self, request, allow_cookie=True: (False, "user session required", {}),
    )

    adapter = WebChatAdapter({})
    srv = gateway_server.ElyanGatewayServer.__new__(gateway_server.ElyanGatewayServer)
    srv.webchat_adapter = adapter

    app = web.Application()

    async def _handler(request):
        return await gateway_server.ElyanGatewayServer.handle_webchat_ws(srv, request)

    app.router.add_get("/ws/chat", _handler)

    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        resp = await client.get("/ws/chat")
        payload = await resp.json()
        assert resp.status == 403
        assert payload["error"] == "user session required"
    finally:
        await client.close()
