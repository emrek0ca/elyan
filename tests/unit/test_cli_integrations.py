from __future__ import annotations

from types import SimpleNamespace

from cli.commands import integrations as cli_integrations
from integrations import ConnectorState, OAuthAccount


class _FakeBroker:
    def __init__(self):
        self.authorize_calls = []
        self.delete_calls = []
        self._accounts = [
            OAuthAccount(
                provider="google",
                account_alias="work",
                display_name="Work",
                email="work@example.com",
                status=ConnectorState.READY,
                access_token="token-1",
                granted_scopes=["email.read", "calendar.read"],
            )
        ]

    def list_accounts(self, provider=None):
        if provider:
            return [item for item in self._accounts if item.provider == provider]
        return list(self._accounts)

    def authorize(self, provider, scopes, **kwargs):
        self.authorize_calls.append((provider, list(scopes or []), kwargs))
        return OAuthAccount(
            provider=provider,
            account_alias=str(kwargs.get("account_alias") or "default"),
            display_name=str(kwargs.get("display_name") or "Authorized"),
            email=str(kwargs.get("email") or ""),
            status=ConnectorState.READY,
            access_token="token-2",
            granted_scopes=list(scopes or []),
            auth_url="",
        )

    def delete_account(self, provider, alias="default"):
        self.delete_calls.append((provider, alias))
        return True


class _FakeTraceStore:
    def list_traces(self, **kwargs):
        _ = kwargs
        return [
            {
                "provider": "google",
                "connector_name": "gmail",
                "integration_type": "email",
                "operation": "connector",
                "status": "success",
                "success": True,
                "latency_ms": 12.0,
                "fallback_used": False,
                "session_id": "sess-1",
                "evidence": [{"kind": "api"}],
                "artifacts": [],
            },
            {
                "provider": "x",
                "connector_name": "x",
                "integration_type": "social",
                "operation": "connector",
                "status": "failed",
                "success": False,
                "latency_ms": 48.0,
                "fallback_used": True,
                "fallback_reason": "social_web_fallback",
                "session_id": "sess-2",
                "evidence": [],
                "artifacts": [],
            },
        ]

    def summary(self, *, limit: int = 200):
        _ = limit
        return {
            "total": 2,
            "fallback_count": 1,
            "by_provider": {"google": 1, "x": 1},
            "by_operation": {"connector": 2},
            "by_status": {"success": 1, "failed": 1},
            "avg_latency_ms": 30.0,
        }


def test_cli_integrations_accounts_connect_revoke_and_traces(monkeypatch, capsys):
    fake_broker = _FakeBroker()
    fake_store = _FakeTraceStore()
    monkeypatch.setattr(cli_integrations, "oauth_broker", fake_broker)
    monkeypatch.setattr(cli_integrations, "get_integration_trace_store", lambda: fake_store)

    code = cli_integrations.handle_integrations(SimpleNamespace(action="accounts", provider="google", json=False))
    assert code == 0
    accounts_out = capsys.readouterr().out
    assert "Hesaplar: 1" in accounts_out
    assert "google:work" in accounts_out
    assert "scopes: email.read, calendar.read" in accounts_out

    code = cli_integrations.handle_integrations(
        SimpleNamespace(
            action="connect",
            provider="",
            account_alias="work",
            app_name="Gmail",
            scopes="",
            mode="oauth",
            authorization_code="abc",
            redirect_uri="http://localhost:8765/callback",
            display_name="Work",
            email="work@example.com",
            json=False,
        )
    )
    assert code == 0
    connect_out = capsys.readouterr().out
    assert "Gmail -> google:work bağlandı" in connect_out
    assert fake_broker.authorize_calls
    assert fake_broker.authorize_calls[-1][0] == "google"

    code = cli_integrations.handle_integrations(
        SimpleNamespace(action="revoke", provider="google", account_alias="work", json=False)
    )
    assert code == 0
    revoke_out = capsys.readouterr().out
    assert "google:work kaldırıldı" in revoke_out
    assert fake_broker.delete_calls == [("google", "work")]

    code = cli_integrations.handle_integrations(
        SimpleNamespace(
            action="traces",
            provider="google",
            limit=10,
            user_id="",
            operation="",
            connector_name="",
            integration_type="",
            json=False,
        )
    )
    assert code == 0
    traces_out = capsys.readouterr().out
    assert "Trace sayısı: 2" in traces_out
    assert "google:gmail connector [success]" in traces_out
    assert "x:x connector [failed]" in traces_out

    code = cli_integrations.handle_integrations(SimpleNamespace(action="summary", provider="google", json=False))
    assert code == 0
    summary_out = capsys.readouterr().out
    assert "Trace toplam: 2" in summary_out
    assert "Fallback: 1" in summary_out
