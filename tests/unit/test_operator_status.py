import pytest


@pytest.mark.asyncio
async def test_operator_status_aggregates_mobile_computer_and_internet(monkeypatch):
    from core import operator_status

    class _Settings:
        def get(self, key, default=None):
            values = {
                "liteparse_enabled": True,
                "vision_ocr_backend": "auto",
                "vision_ocr_model": "glm-ocr",
            }
            return values.get(key, default)

    class _Integration:
        async def get_health_status(self):
            return {"status": "healthy", "ready": True, "fallback_active": False}

    class _Internet:
        def get_health_status(self):
            return {"status": "healthy", "ready": True, "fallback_active": False}

    class _Mobile:
        def get_dashboard_sessions(self):
            return {"status": "healthy", "sessions": [], "count": 0, "pending_approvals": 0, "fallback_active": False}

    monkeypatch.setattr(operator_status, "SettingsPanel", lambda: _Settings())
    monkeypatch.setattr(operator_status, "get_computer_use_integration", lambda: _Integration())
    monkeypatch.setattr(operator_status, "get_internet_reach_runtime", lambda: _Internet())
    monkeypatch.setattr(operator_status, "MobileDispatchBridge", lambda: _Mobile())

    payload = await operator_status.get_operator_status()
    assert payload["status"] == "healthy"
    assert payload["summary"]["document_ingest"]["liteparse_enabled"] is True
    assert "speed_runtime" in payload["summary"]
