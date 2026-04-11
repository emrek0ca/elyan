from __future__ import annotations

import pytest

import tools

from core.briefing_manager import BriefingManager


class _DummyLLM:
    async def generate(self, _prompt: str, user_id: str = "") -> str:
        _ = user_id
        return "briefing-ready"


class _DummyAnomalyDetector:
    def get_anomalies(self, limit: int = 5):
        _ = limit
        return []


async def _none_source():
    return None


async def _fake_source_result(payload=None):
    return payload


@pytest.mark.asyncio
async def test_briefing_manager_routes_system_info_through_task_executor(monkeypatch):
    monkeypatch.setattr("core.briefing_manager.get_anomaly_detector", lambda: _DummyAnomalyDetector())
    seen = {}

    async def get_system_info():
        return {"success": True, "cpu_percent": 11, "memory_percent": 22}

    async def fake_execute(self, tool_func, params):
        seen["tool_name"] = getattr(tool_func, "__name__", "")
        seen["params"] = dict(params)
        return {
            "success": True,
            "status": "success",
            "cpu_percent": 12,
            "memory_percent": 34,
            "disk_usage": {"percent": 56},
            "os_version": "macOS",
        }

    original = tools._loaded_tools.get("get_system_info")
    tools._loaded_tools["get_system_info"] = get_system_info
    monkeypatch.setattr("core.briefing_manager.TaskExecutor.execute", fake_execute)

    manager = BriefingManager(llm_client=_DummyLLM())
    monkeypatch.setattr(manager, "_get_weather", _none_source)
    monkeypatch.setattr(manager, "_get_calendar", _none_source)
    monkeypatch.setattr(manager, "_get_news", _none_source)

    try:
        result = await manager.get_proactive_briefing(include_weather=False, include_calendar=False, include_news=False)
    finally:
        if original is None:
            tools._loaded_tools.pop("get_system_info", None)
        else:
            tools._loaded_tools["get_system_info"] = original

    assert seen["tool_name"] == "get_system_info"
    assert seen["params"] == {}
    assert result["success"] is True
    assert result["briefing"] == "briefing-ready"
    assert result["metrics"]["cpu"] == 12
    assert result["metrics"]["mem"] == 34


@pytest.mark.asyncio
async def test_briefing_manager_missing_tool_is_normalized_and_response_shape_preserved(monkeypatch):
    monkeypatch.setattr("core.briefing_manager.get_anomaly_detector", lambda: _DummyAnomalyDetector())

    class _MissingRegistry:
        def get(self, _tool_name):
            return None

    monkeypatch.setattr("core.briefing_manager.AVAILABLE_TOOLS", _MissingRegistry())

    manager = BriefingManager(llm_client=_DummyLLM())
    monkeypatch.setattr(manager, "_get_weather", _none_source)
    monkeypatch.setattr(manager, "_get_calendar", _none_source)
    monkeypatch.setattr(manager, "_get_news", _none_source)

    result = await manager.get_proactive_briefing(include_weather=False, include_calendar=False, include_news=False)

    assert result["success"] is True
    assert result["briefing"] == "briefing-ready"
    assert result["metrics"]["health_score"] == 100
    assert result["metrics"]["cpu"] is None
    assert result["metrics"]["mem"] is None


@pytest.mark.asyncio
async def test_briefing_manager_malformed_tool_output_is_normalized(monkeypatch):
    monkeypatch.setattr("core.briefing_manager.get_anomaly_detector", lambda: _DummyAnomalyDetector())

    async def broken_system_info():
        return None

    original = tools._loaded_tools.get("get_system_info")
    tools._loaded_tools["get_system_info"] = broken_system_info

    manager = BriefingManager(llm_client=_DummyLLM())
    monkeypatch.setattr(manager, "_get_weather", _none_source)
    monkeypatch.setattr(manager, "_get_calendar", _none_source)
    monkeypatch.setattr(manager, "_get_news", _none_source)

    try:
        result = await manager.get_proactive_briefing(include_weather=False, include_calendar=False, include_news=False)
    finally:
        if original is None:
            tools._loaded_tools.pop("get_system_info", None)
        else:
            tools._loaded_tools["get_system_info"] = original

    assert result["success"] is True
    assert result["briefing"] == "briefing-ready"
    assert result["metrics"]["health_score"] == 100
    assert result["metrics"]["cpu"] is None


@pytest.mark.asyncio
async def test_briefing_manager_returns_structured_morning_digest(monkeypatch):
    monkeypatch.setattr("core.briefing_manager.get_anomaly_detector", lambda: _DummyAnomalyDetector())

    async def fake_execute(self, tool_func, params):
        _ = (tool_func, params)
        return {
            "success": True,
            "status": "success",
            "cpu_percent": 18,
            "memory_percent": 41,
            "disk_usage": {"percent": 57},
            "os_version": "macOS 15",
        }

    monkeypatch.setattr("core.briefing_manager.TaskExecutor.execute", fake_execute)

    manager = BriefingManager(llm_client=_DummyLLM())
    monkeypatch.setattr(
        manager,
        "_get_weather",
        lambda: _fake_source_result(
            {
                "success": True,
                "city": "Istanbul",
                "temperature": 19,
                "description": "parçalı bulutlu",
            }
        ),
    )
    monkeypatch.setattr(
        manager,
        "_get_calendar",
        lambda: _fake_source_result(
            {
                "success": True,
                "events": [
                    {"title": "Standup", "start": "09:30", "end": "10:00"},
                ],
                "count": 1,
            }
        ),
    )
    monkeypatch.setattr(
        manager,
        "_get_news",
        lambda: _fake_source_result(
            {
                "success": True,
                "headlines": [
                    {"title": "Merkez Bankası faiz kararını açıkladı", "link": "https://example.com/news"},
                ],
                "count": 1,
            }
        ),
    )
    monkeypatch.setattr(
        manager,
        "_get_email_digest",
        lambda: _fake_source_result(
            {
                "success": True,
                "messages": [
                    {"title": "Bütçe onayı bekliyor", "from": "finance@example.com"},
                ],
                "count": 1,
            }
        ),
    )

    result = await manager.get_proactive_briefing()

    assert result["success"] is True
    assert result["briefing"] == "briefing-ready"
    digest = result["digest"]
    assert digest["summary"] == "briefing-ready"
    assert digest["calendar_items"][0]["title"] == "Standup"
    assert digest["email_items"][0]["title"] == "Bütçe onayı bekliyor"
    assert digest["news_items"][0]["title"] == "Merkez Bankası faiz kararını açıkladı"
    assert "19 derece" in digest["speech_script"]
    assert digest["source_trace"]["calendar"]["available"] is True
    assert digest["source_trace"]["email"]["available"] is True
