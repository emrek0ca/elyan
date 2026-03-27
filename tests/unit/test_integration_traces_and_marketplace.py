from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from core.gateway import server as gateway_server
from core.integration_trace import IntegrationTraceStore
from core.skills.marketplace import SkillMarketplace
from integrations import ConnectorState, OAuthAccount


class _Req:
    def __init__(self, query=None, payload=None):
        self.rel_url = type("_Rel", (), {"query": query or {}})()
        self._payload = payload or {}

    async def json(self):
        return dict(self._payload)


class _FakeBroker:
    def __init__(self):
        self.authorize_calls = []
        self.delete_calls = []
        self.accounts = [
            OAuthAccount(
                provider="google",
                account_alias="work",
                display_name="Work",
                email="work@example.com",
                status=ConnectorState.READY,
                access_token="token-1",
                granted_scopes=["email.read", "calendar.read"],
            ),
            OAuthAccount(
                provider="x",
                account_alias="default",
                display_name="X",
                email="",
                status=ConnectorState.NEEDS_INPUT,
                auth_url="https://x.com/oauth",
                granted_scopes=[],
            ),
        ]

    def list_accounts(self, provider=None):
        if provider:
            return [account for account in self.accounts if account.provider == provider]
        return list(self.accounts)

    def authorize(self, provider, scopes, **kwargs):
        self.authorize_calls.append((provider, list(scopes or []), kwargs))
        return OAuthAccount(
            provider=provider,
            account_alias=str(kwargs.get("account_alias") or "default"),
            display_name=f"{provider.title()} Account",
            email=f"{provider}@example.com",
            status=ConnectorState.READY,
            access_token=f"{provider}-token",
            granted_scopes=list(scopes or []),
            auth_url="",
        )

    def delete_account(self, provider, alias="default"):
        self.delete_calls.append((provider, alias))
        return True


@pytest.mark.asyncio
async def test_gateway_integration_account_and_trace_endpoints(monkeypatch, tmp_path):
    store = IntegrationTraceStore(storage_root=tmp_path / "trace")
    store.record_trace(
        provider="google",
        connector_name="gmail",
        integration_type="email",
        operation="connector",
        status="success",
        success=True,
        latency_ms=11.2,
    )
    store.record_trace(
        provider="x",
        connector_name="x",
        integration_type="social",
        operation="connector",
        status="failed",
        success=False,
        fallback_used=True,
        fallback_reason="social_web_fallback",
        latency_ms=32.5,
    )
    monkeypatch.setattr("core.integration_trace.get_integration_trace_store", lambda: store)
    fake_broker = _FakeBroker()
    monkeypatch.setattr("integrations.oauth_broker", fake_broker)

    class _FakeConnector:
        async def connect(self, target, **kwargs):
            _ = (target, kwargs)
            return SimpleNamespace(
                success=True,
                status="success",
                fallback_used=False,
                fallback_reason="",
                model_dump=lambda: {
                    "success": True,
                    "status": "success",
                    "fallback_used": False,
                    "fallback_reason": "",
                    "message": "connected",
                },
            )

    monkeypatch.setattr("integrations.connector_factory.get", lambda *args, **kwargs: _FakeConnector())

    srv = gateway_server.ElyanGatewayServer.__new__(gateway_server.ElyanGatewayServer)

    accounts_resp = await gateway_server.ElyanGatewayServer.handle_integrations_accounts(
        srv,
        _Req(query={"provider": "google"}),
    )
    accounts_payload = json.loads(accounts_resp.text)
    assert accounts_payload["ok"] is True
    assert accounts_payload["total"] == 1
    assert accounts_payload["counts"]["ready"] == 1

    connect_resp = await gateway_server.ElyanGatewayServer.handle_integrations_connect(
        srv,
        _Req(
            payload={
                "app_name": "Gmail",
                "account_alias": "work",
                "mode": "oauth",
                "authorization_code": "",
                "redirect_uri": "http://localhost:8765/callback",
            }
        ),
    )
    connect_payload = json.loads(connect_resp.text)
    assert connect_payload["ok"] is True
    assert connect_payload["resolved_app_name"] == "Gmail"
    assert connect_payload["resolved_provider"] == "google"
    assert connect_payload["account"]["status"] == ConnectorState.READY.value
    assert fake_broker.authorize_calls

    revoke_resp = await gateway_server.ElyanGatewayServer.handle_integrations_account_revoke(
        srv,
        _Req(payload={"provider": "google", "account_alias": "work"}),
    )
    revoke_payload = json.loads(revoke_resp.text)
    assert revoke_payload["ok"] is True
    assert fake_broker.delete_calls == [("google", "work")]

    trace_resp = await gateway_server.ElyanGatewayServer.handle_integration_traces(
        srv,
        _Req(query={"provider": "google", "limit": "10"}),
    )
    trace_payload = json.loads(trace_resp.text)
    assert trace_payload["ok"] is True
    assert trace_payload["total"] == 3
    assert trace_payload["summary"]["total"] == 4

    summary_resp = await gateway_server.ElyanGatewayServer.handle_integration_summary(
        srv,
        _Req(query={"provider": "google"}),
    )
    summary_payload = json.loads(summary_resp.text)
    assert summary_payload["ok"] is True
    assert summary_payload["accounts"]["total"] == 1
    assert summary_payload["traces"]["total"] == 4


def test_integration_trace_store_prefers_runtime_db_when_jsonl_missing(monkeypatch, tmp_path):
    class _ConnectorRepo:
        def __init__(self):
            self.traces = [
                {
                    "trace_id": "itr_1",
                    "provider": "google",
                    "connector_name": "gmail",
                    "integration_type": "email",
                    "operation": "connector",
                    "status": "success",
                    "success": True,
                    "latency_ms": 12.5,
                    "fallback_used": False,
                },
                {
                    "trace_id": "itr_2",
                    "provider": "google",
                    "connector_name": "calendar",
                    "integration_type": "calendar",
                    "operation": "connector",
                    "status": "success",
                    "success": True,
                    "latency_ms": 20.0,
                    "fallback_used": True,
                },
            ]

        def list_traces(self, **kwargs):
            limit = int(kwargs.get("limit") or 100)
            provider = str(kwargs.get("provider") or "").strip().lower()
            rows = [dict(item) for item in self.traces]
            if provider:
                rows = [row for row in rows if str(row.get("provider") or "").strip().lower() == provider]
            return rows[:limit]

        def summary(self, **kwargs):
            _ = kwargs
            return {"total": len(self.traces), "recent": list(self.traces), "fallback_count": 1}

    class _RuntimeDb:
        def __init__(self):
            self.connectors = _ConnectorRepo()

    runtime_db = _RuntimeDb()
    monkeypatch.setattr("core.integration_trace.get_runtime_database", lambda: runtime_db)
    store = IntegrationTraceStore(storage_root=tmp_path / "trace", use_runtime_db=True)

    rows = store.list_traces(limit=10, provider="google")
    assert len(rows) == 2
    assert rows[0]["trace_id"] == "itr_1"

    summary = store.summary(limit=10)
    assert summary["total"] == 2
    assert summary["fallback_count"] == 1
    assert summary["recent"][0]["trace_id"] == "itr_1"


@pytest.mark.asyncio
async def test_marketplace_rejects_untrusted_urls_and_hashless_remote_packages(monkeypatch, tmp_path):
    monkeypatch.setattr("core.skills.marketplace.Path.home", lambda: tmp_path)
    traces: list[dict[str, object]] = []

    class _TraceStore:
        def record_trace(self, **kwargs):
            traces.append(dict(kwargs))
            return dict(kwargs)

    monkeypatch.setattr("core.integration_trace.get_integration_trace_store", lambda: _TraceStore())
    marketplace = SkillMarketplace()

    blocked, message, warnings = await marketplace.install_from_url("http://evil.example.com/skill.json")
    assert blocked is False
    assert "Untrusted marketplace URL" in message
    assert warnings

    blocked2, message2, warnings2 = await marketplace.install_from_dict(
        {
            "name": "hashless_skill",
            "version": "1.0.0",
            "description": "Remote package without checksum",
            "source": "marketplace",
            "trust_level": "curated",
            "files": {"skill.py": "print('ok')"},
        }
    )
    assert blocked2 is False
    assert "Hash verification failed" in message2 or "Trust policy blocked" in message2
    assert warnings2
    assert traces
