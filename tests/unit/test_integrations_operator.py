from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from core.realtime_actuator import RealTimeActuator
from integrations import (
    AuthStrategy,
    ConnectorFactory,
    ConnectorState,
    FallbackPolicy,
    IntegrationRegistry,
    IntegrationType,
    OAuthAccount,
    OAuthBroker,
    Platform,
    connector_factory,
    integration_registry,
)
from integrations.connectors.browser import BrowserConnector
from integrations.connectors.desktop import DesktopConnector
from integrations.connectors.email import EmailConnector
from integrations.connectors.google import GoogleConnector
from integrations.connectors.scheduler import SchedulerConnector
from integrations.connectors.social import SocialConnector
from core.security.secure_vault import SecureVault


class _FakeScreenServices:
    def __init__(self, tmp_path: Path):
        self.tmp_path = tmp_path

    async def take_screenshot(self, filename=None):
        path = self.tmp_path / (filename or "screen.png")
        path.write_text("frame", encoding="utf-8")
        return {"success": True, "path": str(path)}

    async def capture_region(self, x, y, width, height, filename=None):
        _ = (x, y, width, height)
        return await self.take_screenshot(filename=filename)

    async def get_window_metadata(self):
        return {"success": True, "window_title": "Desktop", "frontmost_app": "Finder"}

    async def get_accessibility_snapshot(self):
        return {
            "success": True,
            "elements": [
                {"label": "Save", "role": "button", "x": 10, "y": 20, "width": 80, "height": 24},
            ],
        }

    async def run_ocr(self, image_path):
        _ = image_path
        return {"success": True, "text": "Save"}

    async def run_vision(self, image_path, prompt):
        _ = (image_path, prompt)
        return {
            "success": True,
            "summary": "Save button visible",
            "elements": [
                {"label": "Save", "role": "button", "x": 10, "y": 20, "width": 80, "height": 24},
            ],
        }

    async def mouse_move(self, x, y):
        return {"success": True, "x": x, "y": y}

    async def mouse_click(self, x, y, button="left", double=False):
        return {"success": True, "x": x, "y": y, "button": button, "double": double}

    async def type_text(self, text, press_enter=False):
        return {"success": True, "text": text, "press_enter": press_enter}

    async def press_key(self, key, modifiers=None):
        return {"success": True, "key": key, "modifiers": list(modifiers or [])}

    async def key_combo(self, combo):
        return {"success": True, "combo": combo}

    async def sleep(self, seconds):
        _ = seconds
        return None


@pytest.fixture
def oauth_config(monkeypatch):
    def fake_get(path, default=None):
        configs = {
            "oauth.providers.google": {
                "client_id": "client-id",
                "client_secret": "client-secret",
                "token_url": "https://oauth.example/token",
                "auth_url": "https://oauth.example/auth",
                "redirect_uri": "http://localhost:8765/callback",
                "fallback_policy": "web",
                "display_name": "Google",
            }
        }
        return configs.get(path, default)

    monkeypatch.setattr("integrations.auth.elyan_config.get", fake_get)
    return fake_get


def test_oauth_broker_persists_accounts_and_refreshes_tokens(tmp_path, monkeypatch, oauth_config):
    vault = SecureVault(vault_dir=str(tmp_path / "vault"))
    vault.unlock()
    broker = OAuthBroker(vault=vault)

    class _Resp:
        def __init__(self, payload, status_code=200):
            self._payload = payload
            self.status_code = status_code

        def json(self):
            return dict(self._payload)

    def fake_post(url, data=None, timeout=None):
        _ = (url, timeout)
        grant_type = str((data or {}).get("grant_type") or "")
        if grant_type == "authorization_code":
            return _Resp(
                {
                    "access_token": "access-1",
                    "refresh_token": "refresh-1",
                    "token_type": "Bearer",
                    "expires_in": 1,
                }
            )
        if grant_type == "refresh_token":
            return _Resp(
                {
                    "access_token": "access-2",
                    "refresh_token": "refresh-2",
                    "token_type": "Bearer",
                    "expires_in": 3600,
                }
            )
        return _Resp({}, 400)

    monkeypatch.setattr("integrations.auth.requests.post", fake_post)

    account = broker.authorize(
        "google",
        ["email.read"],
        authorization_code="auth-code",
        extra={"display_name": "Gmail"},
    )
    assert account.is_ready is True
    assert account.access_token == "access-1"
    assert broker.list_accounts("google")[0].access_token == "access-1"

    account.expires_at = time.time() - 10.0
    broker._save_account(account)

    refreshed = broker.authorize("google", ["email.read"])
    assert refreshed.is_ready is True
    assert refreshed.access_token == "access-2"
    assert broker.list_accounts("google")[0].access_token == "access-2"


def test_oauth_broker_handles_persistence_failure_gracefully(tmp_path, monkeypatch, oauth_config):
    vault = SecureVault(vault_dir=str(tmp_path / "vault"))
    vault.unlock()
    broker = OAuthBroker(vault=vault)

    class _Resp:
        status_code = 200

        def json(self):
            return {
                "access_token": "access-1",
                "refresh_token": "refresh-1",
                "token_type": "Bearer",
                "expires_in": 3600,
            }

    monkeypatch.setattr("integrations.auth.requests.post", lambda *args, **kwargs: _Resp())
    monkeypatch.setattr(broker.vault, "store_secret", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("vault locked")))

    account = broker.authorize("google", ["email.read"], authorization_code="auth-code")
    assert account.is_ready is True
    assert account.access_token == "access-1"


def test_oauth_broker_syncs_connector_truth_to_runtime_db(tmp_path, monkeypatch, oauth_config):
    vault = SecureVault(vault_dir=str(tmp_path / "vault"))
    vault.unlock()

    class _ConnectorRepo:
        def __init__(self):
            self.accounts: dict[tuple[str, str, str], dict[str, object]] = {}
            self.traces: list[dict[str, object]] = []

        def upsert_account(self, payload):
            payload = dict(payload or {})
            key = (
                str(payload.get("workspace_id") or "local-workspace"),
                str(payload.get("provider") or ""),
                str(payload.get("account_alias") or "default"),
            )
            self.accounts[key] = payload

        def list_accounts(self, workspace_id="local-workspace", provider=""):
            rows = list(self.accounts.values())
            if provider:
                rows = [row for row in rows if str(row.get("provider") or "") == provider]
            if workspace_id:
                rows = [row for row in rows if str(row.get("workspace_id") or "") == workspace_id]
            return rows

        def get_account(self, provider, account_alias, workspace_id="local-workspace"):
            return self.accounts.get((workspace_id, provider, account_alias))

        def delete_account(self, provider, account_alias, workspace_id="local-workspace"):
            self.accounts.pop((workspace_id, provider, account_alias), None)

        def record_trace(self, payload):
            self.traces.append(dict(payload or {}))
            return dict(payload or {})

        def list_traces(self, **kwargs):
            _ = kwargs
            return list(self.traces)

        def summary(self, **kwargs):
            _ = kwargs
            return {"total": len(self.traces), "recent": list(self.traces)}

    class _RuntimeDb:
        def __init__(self):
            self.connectors = _ConnectorRepo()

    runtime_db = _RuntimeDb()
    monkeypatch.setattr("integrations.auth.get_runtime_database", lambda: runtime_db)
    broker = OAuthBroker(vault=vault)

    class _Resp:
        def __init__(self, payload, status_code=200):
            self._payload = payload
            self.status_code = status_code

        def json(self):
            return dict(self._payload)

    def fake_post(url, data=None, timeout=None):
        _ = (url, timeout)
        grant_type = str((data or {}).get("grant_type") or "")
        if grant_type == "authorization_code":
            return _Resp(
                {
                    "access_token": "access-1",
                    "refresh_token": "refresh-1",
                    "token_type": "Bearer",
                    "expires_in": 3600,
                }
            )
        return _Resp({}, 400)

    monkeypatch.setattr("integrations.auth.requests.post", fake_post)

    account = broker.authorize(
        "google",
        ["email.read"],
        authorization_code="auth-code",
        extra={"display_name": "Gmail", "workspace_id": "workspace-alpha"},
    )
    assert account.is_ready is True

    records = runtime_db.connectors.list_accounts(workspace_id="workspace-alpha", provider="google")
    assert len(records) == 1
    assert records[0]["account_alias"] == "default"
    assert records[0]["workspace_id"] == "workspace-alpha"
    assert records[0]["status"] == ConnectorState.READY.value
    assert runtime_db.connectors.get_account("google", "default", workspace_id="workspace-alpha") is not None
    loaded = broker.list_accounts("google")
    assert len(loaded) == 1
    assert loaded[0].provider == "google"
    assert loaded[0].display_name == "Gmail"
    assert broker.delete_account("google", "default") is True
    assert runtime_db.connectors.get_account("google", "default", workspace_id="workspace-alpha") is None
    assert broker.list_accounts("google") == []


def test_integration_registry_resolves_oauth_first_capabilities():
    email_capability = integration_registry.resolve("Gmail'de son mesajları oku")
    calendar_capability = integration_registry.resolve("Google Calendar'a toplantı ekle")
    docs_capability = integration_registry.resolve("Google Docs'ta doküman yaz")
    sheets_capability = integration_registry.resolve("Google Sheets'te tablo güncelle")
    slides_capability = integration_registry.resolve("Google Slides sunumu hazırla")
    chat_capability = integration_registry.resolve("Google Chat'te mesaj gönder")
    social_capability = integration_registry.resolve("Instagram'a story at")

    assert str(email_capability.integration_type) == IntegrationType.EMAIL.value
    assert str(email_capability.auth_strategy) == AuthStrategy.OAUTH.value
    assert "email.read" in list(email_capability.required_scopes)
    assert str(email_capability.fallback_policy) == FallbackPolicy.WEB.value
    assert email_capability.workflow_bundle.steps

    assert str(calendar_capability.integration_type) == IntegrationType.API.value
    assert str(calendar_capability.auth_strategy) == AuthStrategy.OAUTH.value
    assert "calendar.write" in list(calendar_capability.required_scopes)
    assert str(calendar_capability.fallback_policy) == FallbackPolicy.WEB.value
    assert calendar_capability.multi_agent_recommended is True or len(calendar_capability.workflow_bundle.steps) >= 2

    assert str(docs_capability.integration_type) == IntegrationType.API.value
    assert "docs.read" in list(docs_capability.required_scopes)
    assert str(sheets_capability.integration_type) == IntegrationType.API.value
    assert "sheets.write" in list(sheets_capability.required_scopes)
    assert str(slides_capability.integration_type) == IntegrationType.API.value
    assert "slides.read" in list(slides_capability.required_scopes)
    assert str(chat_capability.integration_type) == IntegrationType.API.value
    assert "chat.write" in list(chat_capability.required_scopes)

    assert str(social_capability.integration_type) == IntegrationType.SOCIAL.value
    assert str(social_capability.fallback_policy) == FallbackPolicy.WEB.value
    assert any(scope.startswith("instagram.") for scope in list(social_capability.required_scopes))

    quick_plan = integration_registry.resolve_connection_plan(app_name="Gmail")
    assert quick_plan["provider"] == "google"
    assert "email.read" in list(quick_plan["required_scopes"])
    assert str(quick_plan["integration_type"]) == IntegrationType.EMAIL.value


@pytest.mark.asyncio
async def test_email_connector_uses_google_oauth_when_env_is_missing(monkeypatch):
    connector = EmailConnector(provider="google", connector_name="gmail")
    monkeypatch.setattr(connector, "_ready_via_env", lambda: False)
    monkeypatch.setattr(
        "integrations.connectors.email.oauth_broker.authorize",
        lambda *args, **kwargs: OAuthAccount(
            provider="google",
            account_alias="default",
            status="ready",
            access_token="token-1",
            refresh_token="refresh-1",
            granted_scopes=["email.read"],
        ),
    )

    result = await connector.connect("gmail")

    assert result.success is True
    assert result.status == "ready"
    assert connector.auth_account.provider == "google"


@pytest.mark.asyncio
async def test_social_connector_prefers_api_execution_when_available(monkeypatch):
    connector = SocialConnector(provider="x", connector_name="x")
    monkeypatch.setattr("integrations.connectors.social.oauth_broker.provider_config", lambda provider: {"api_base_url": "https://api.example.com"})
    monkeypatch.setattr(
        "integrations.connectors.social.oauth_broker.authorize",
        lambda *args, **kwargs: OAuthAccount(
            provider="x",
            account_alias="default",
            status=ConnectorState.READY,
            access_token="token-x",
            granted_scopes=["x.read", "x.write"],
        ),
    )
    connector.auth_account = OAuthAccount(
        provider="x",
        account_alias="default",
        status=ConnectorState.READY,
        access_token="token-x",
        granted_scopes=["x.read", "x.write"],
    )

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"ok": True, "message": "sent"}

    monkeypatch.setattr("integrations.connectors.social.requests.request", lambda *args, **kwargs: _Resp())

    result = await connector.execute({"endpoint": "posts", "method": "POST", "json": {"text": "hello"}})

    assert result.success is True
    assert result.fallback_used is False
    assert result.result["ok"] is True


def test_connector_factory_maps_integration_types_to_correct_connectors():
    capability = integration_registry.resolve("Gmail'de son mesajları oku")
    google_connector = connector_factory.get(
        IntegrationType.API,
        platform=Platform.LINUX,
        auth_state={"capability": capability.model_dump(), "auth_account": {"provider": "google"}},
    )
    browser_connector = connector_factory.get(IntegrationType.BROWSER, platform=Platform.LINUX)
    desktop_connector = connector_factory.get(IntegrationType.DESKTOP, platform=Platform.LINUX)
    email_connector = connector_factory.get(IntegrationType.EMAIL, platform=Platform.LINUX)
    social_connector = connector_factory.get(IntegrationType.SOCIAL, platform=Platform.LINUX)
    scheduler_connector = connector_factory.get(IntegrationType.SCHEDULER, platform=Platform.LINUX)

    assert isinstance(google_connector, GoogleConnector)
    assert isinstance(browser_connector, BrowserConnector)
    assert isinstance(desktop_connector, DesktopConnector)
    assert isinstance(email_connector, EmailConnector)
    assert isinstance(social_connector, SocialConnector)
    assert isinstance(scheduler_connector, SchedulerConnector)


def test_realtime_actuator_parallel_submission_batches_independent_actions(monkeypatch, tmp_path):
    monkeypatch.setattr("core.realtime_actuator.runtime._module_available", lambda name: False)
    services = _FakeScreenServices(tmp_path)
    actuator = RealTimeActuator(services=services, process_mode=False, fps=30, max_frames=3, max_actions=3)

    active = 0
    max_active = 0
    call_order: list[str] = []

    async def fake_submit_async(action):
        nonlocal active, max_active
        kind = str(action.get("kind") or action.get("action") or "")
        call_order.append(kind)
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.01)
        active -= 1
        return {"success": True, "status": "success", "kind": kind}

    monkeypatch.setattr(actuator, "submit_async", fake_submit_async)

    results = asyncio.run(
        actuator.submit_parallel(
            [
                {"kind": "click", "id": 1},
                {"kind": "click", "id": 2},
                {"kind": "send", "id": 3},
                {"kind": "click", "id": 4},
            ],
            max_parallel=3,
        )
    )

    assert len(results) == 4
    assert [item["kind"] for item in results] == ["click", "click", "send", "click"]
    assert max_active >= 2
    assert call_order[2] == "send"


def test_core_integrations_compat_exports_canonical_surface():
    import core.integrations as compat

    assert hasattr(compat, "integration_registry")
    assert hasattr(compat, "connector_factory")
    assert hasattr(compat, "oauth_broker")
