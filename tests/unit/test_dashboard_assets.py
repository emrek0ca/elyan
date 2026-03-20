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


def test_dashboard_js_includes_mission_control_runtime_hooks():
    js = Path("/Users/emrekoca/Desktop/bot/ui/web/dashboard.js").read_text(encoding="utf-8")
    assert "timeoutMs: 130000" in js
    assert "Istek zaman asimina ugradi" in js
    assert "friendlyFailure" in js
    assert "missionFilter" in js
    assert "renderMissionControlStrip" in js
    assert "renderMissionQuality" in js
    assert "/api/missions" in js
    assert "/api/missions/" in js
    assert "/api/missions/overview" in js
    assert "/api/missions/approvals/resolve" in js
    assert "/api/missions/skills/save" in js
    assert "/api/missions/memory" in js
    assert "Mission baslatildi" in js
    assert "mission_event" in js
    assert "URLSearchParams" in js
    assert "mission_id" in js
    assert "selected_mission_id" in js
    assert 'tools: "p-tools"' in js
    assert "g-refresh-tools" in js
    assert "loadSkillCatalog" in js
    assert "refreshSkillRegistry" in js
    assert "loadMarketplace" in js
    assert "installMarketplaceSkill" in js
    assert "/api/skills/refresh" in js
    assert "skills-refresh" in js
    assert "/api/marketplace/browse" in js
    assert "/api/marketplace/categories" in js
    assert "/api/marketplace/install" in js
    assert "marketplace-refresh" in js
    assert 'rawStrategy === "hızlı"' in js
    assert 'normalizedStrategy = "fast"' in js


def test_ops_console_js_points_to_admin_endpoints():
    js = Path("/Users/emrekoca/Desktop/bot/ui/web/ops_console.js").read_text(encoding="utf-8")
    assert "/api/admin/overview" in js
    assert "/api/admin/users" in js
    assert "/api/admin/plans" in js
