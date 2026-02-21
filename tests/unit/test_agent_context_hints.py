from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.agent import Agent


@pytest.mark.asyncio
async def test_execute_tool_pushes_error_hint_to_dashboard(monkeypatch):
    agent = Agent()
    agent.kernel = MagicMock()
    agent.kernel.tools.execute = AsyncMock(side_effect=ValueError("not found"))
    agent.learning = MagicMock()
    agent.learning.generate_smart_hint.return_value = "Erişim hatası için izinleri kontrol et."

    async def _failing_tool(**_kwargs):
        return {"success": False, "error": "permission denied while writing file"}

    monkeypatch.setattr("core.agent.AVAILABLE_TOOLS", {"custom_hint_tool": _failing_tool})

    with patch("core.agent.tool_policy") as mock_policy, patch("core.agent._push_hint") as mock_push_hint:
        mock_policy.check_access.return_value = {"allowed": True, "requires_approval": False}
        result = await agent._execute_tool("custom_hint_tool", {"path": "x.txt"})

    assert result["success"] is False
    called_error = str(agent.learning.generate_smart_hint.call_args.kwargs.get("last_error", "")).lower()
    assert "permission denied" in called_error
    mock_push_hint.assert_called_once()
    assert mock_push_hint.call_args.kwargs.get("icon") == "triangle-alert"
    assert mock_push_hint.call_args.kwargs.get("color") == "orange"


@pytest.mark.asyncio
async def test_execute_tool_pushes_discovery_hint_on_success(monkeypatch):
    agent = Agent()
    agent.kernel = MagicMock()
    agent.kernel.tools.execute = AsyncMock(side_effect=ValueError("not found"))
    agent.learning = MagicMock()
    agent.learning.generate_smart_hint.return_value = "Araştırma için research komutunu deneyebilirsin."

    async def _ok_tool(**_kwargs):
        return {"success": True, "content": "ok"}

    monkeypatch.setattr("core.agent.AVAILABLE_TOOLS", {"custom_hint_tool": _ok_tool})

    with patch("core.agent.tool_policy") as mock_policy, patch("core.agent._push_hint") as mock_push_hint:
        mock_policy.check_access.return_value = {"allowed": True, "requires_approval": False}
        result = await agent._execute_tool("custom_hint_tool", {})

    assert result["success"] is True
    agent.learning.generate_smart_hint.assert_called_with(last_error=None)
    mock_push_hint.assert_called_once_with(
        "Araştırma için research komutunu deneyebilirsin.",
        icon="lightbulb",
        color="blue",
    )
