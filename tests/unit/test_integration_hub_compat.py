from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.integration_hub import Integration, IntegrationHub, IntegrationStatus, IntegrationType


@pytest.fixture
def isolated_hub(tmp_path, monkeypatch):
    monkeypatch.setattr("core.integration_hub.HOME_DIR", tmp_path)
    hub = IntegrationHub()
    hub.integrations = {}
    hub.credentials_file = tmp_path / "integrations.json"
    return hub


@pytest.mark.asyncio
async def test_send_email_delegates_to_email_tools(isolated_hub, monkeypatch):
    hub = isolated_hub
    integration_id = hub.register_integration(
        "mail",
        IntegrationType.EMAIL,
        {"email_address": "user@example.com", "email_password": "secret", "smtp_server": "smtp.example.com", "smtp_port": 587},
        {"imap_server": "imap.example.com"},
    )

    called = {}

    async def fake_send_email(self, to, subject, body, cc=None, bcc=None, attachments=None, html=False):
        called["to"] = to
        called["subject"] = subject
        called["body"] = body
        called["cc"] = cc
        called["bcc"] = bcc
        called["html"] = html
        return {"success": True, "message": "sent"}

    monkeypatch.setattr("tools.email_tools.EmailManager.send_email", fake_send_email)

    result = await hub.send_email(integration_id, "dest@example.com", "Hello", "World")

    assert result["success"] is True
    assert called["to"] == "dest@example.com"
    assert called["subject"] == "Hello"


@pytest.mark.asyncio
async def test_create_calendar_event_delegates_to_google_connector(isolated_hub, monkeypatch):
    hub = isolated_hub
    integration_id = hub.register_integration(
        "calendar",
        IntegrationType.CALENDAR,
        {"access_token": "access-token", "refresh_token": "refresh-token", "email": "user@example.com"},
        {"scopes": ["calendar.read", "calendar.write"]},
    )

    captured = {}

    async def fake_execute(self, action):
        captured["action"] = dict(action)
        return SimpleNamespace(
            model_dump=lambda: {"success": True, "status": "success", "message": "calendar_event_created", "action": dict(action)}
        )

    monkeypatch.setattr("integrations.connectors.google.GoogleConnector.execute", fake_execute)

    result = await hub.create_calendar_event(integration_id, "Meeting", "2026-03-20T10:00:00Z", "2026-03-20T11:00:00Z")

    assert result["success"] is True
    assert captured["action"]["kind"] == "calendar_create"
    assert captured["action"]["event"]["summary"] == "Meeting"


@pytest.mark.asyncio
async def test_upload_to_cloud_delegates_to_google_drive(isolated_hub, monkeypatch, tmp_path):
    hub = isolated_hub
    file_path = tmp_path / "report.txt"
    file_path.write_text("hello", encoding="utf-8")
    integration_id = hub.register_integration(
        "drive",
        IntegrationType.CLOUD_STORAGE,
        {"access_token": "access-token", "refresh_token": "refresh-token"},
        {"provider": "google", "folder_id": "folder-123"},
    )

    captured = {}

    async def fake_execute(self, action):
        captured["action"] = dict(action)
        return SimpleNamespace(
            model_dump=lambda: {"success": True, "status": "success", "message": "drive_uploaded", "action": dict(action)}
        )

    monkeypatch.setattr("integrations.connectors.google.GoogleConnector.execute", fake_execute)

    result = await hub.upload_to_cloud(integration_id, str(file_path), remote_path="reports/report.txt")

    assert result["success"] is True
    assert captured["action"]["kind"] == "drive_upload"
    assert captured["action"]["file_path"] == str(file_path)
    assert captured["action"]["name"] == "reports/report.txt"
