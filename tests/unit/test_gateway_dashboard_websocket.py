import pytest
from aiohttp import WSMsgType, web
from aiohttp.test_utils import TestClient, TestServer

from core.gateway import server as gateway_server


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
