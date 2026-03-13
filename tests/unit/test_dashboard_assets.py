"""Unit tests for dashboard asset serving."""

from aiohttp import web
import pytest
from pathlib import Path

from core.gateway import server as gateway_server


class _Req:
    def __init__(self, filename):
        self.match_info = {"filename": filename}


class _OpsReq:
    def __init__(self, query=None, cookies=None, remote="127.0.0.1"):
        self.query = query or {}
        self.cookies = cookies or {}
        self.headers = {}
        self.remote = remote
        self.transport = None


@pytest.mark.asyncio
async def test_handle_web_asset_serves_dashboard_js():
    srv = gateway_server.ElyanGatewayServer.__new__(gateway_server.ElyanGatewayServer)
    resp = await gateway_server.ElyanGatewayServer.handle_web_asset(srv, _Req("dashboard.js"))
    assert isinstance(resp, web.FileResponse)


@pytest.mark.asyncio
async def test_handle_web_asset_serves_ops_console_js():
    srv = gateway_server.ElyanGatewayServer.__new__(gateway_server.ElyanGatewayServer)
    resp = await gateway_server.ElyanGatewayServer.handle_web_asset(srv, _Req("ops_console.js"))
    assert isinstance(resp, web.FileResponse)


@pytest.mark.asyncio
async def test_handle_web_asset_rejects_traversal():
    srv = gateway_server.ElyanGatewayServer.__new__(gateway_server.ElyanGatewayServer)
    resp = await gateway_server.ElyanGatewayServer.handle_web_asset(srv, _Req("../secret.txt"))
    assert resp.status == 400


@pytest.mark.asyncio
async def test_handle_ops_console_page_requires_valid_token(monkeypatch):
    monkeypatch.setattr(gateway_server, "_ensure_admin_access_token", lambda: "ops-token")
    srv = gateway_server.ElyanGatewayServer.__new__(gateway_server.ElyanGatewayServer)
    resp = await gateway_server.ElyanGatewayServer.handle_ops_console_page(srv, _OpsReq(query={}))
    assert resp.status == 403


@pytest.mark.asyncio
async def test_handle_ops_console_page_sets_admin_cookie(monkeypatch):
    monkeypatch.setattr(gateway_server, "_ensure_admin_access_token", lambda: "ops-token")
    srv = gateway_server.ElyanGatewayServer.__new__(gateway_server.ElyanGatewayServer)
    resp = await gateway_server.ElyanGatewayServer.handle_ops_console_page(srv, _OpsReq(query={"token": "ops-token"}))
    assert isinstance(resp, web.FileResponse)
    assert resp.cookies["elyan_admin_session"].value == "ops-token"


def test_dashboard_js_uses_longer_message_timeout_and_friendly_abort_text():
    js = Path("/Users/emrekoca/Desktop/bot/ui/web/dashboard.js").read_text(encoding="utf-8")
    assert "timeoutMs: 130000" in js
    assert "Istek zaman asimina ugradi" in js
    assert "friendlyFailure" in js
    assert "status-detail" in js
    assert "/api/product/home" in js
    assert "/api/models" in js
    assert "/api/agent/profile" in js
    assert "model-add-btn" in js
    assert "collab-save-btn" in js
    assert "profile-save-btn" in js
    assert "/api/product/workflows/run" in js
    assert "onboarding-list" in js
    assert "release-list" in js


def test_ops_console_js_points_to_admin_endpoints():
    js = Path("/Users/emrekoca/Desktop/bot/ui/web/ops_console.js").read_text(encoding="utf-8")
    assert "/api/admin/overview" in js
    assert "/api/admin/users" in js
    assert "/api/admin/plans" in js
