import asyncio
import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.agent import Agent


class _NoopMemory:
    def get_recent_conversations(self, user_id, limit=5):
        _ = (user_id, limit)
        return []

    def store_conversation(self, user_id, user_input, bot_response):
        _ = (user_id, user_input, bot_response)
        return None


class _KernelTools:
    def __init__(self, execute):
        self.execute = execute


class _Kernel:
    def __init__(self, execute):
        self.memory = _NoopMemory()
        self.tools = _KernelTools(execute)


class _DummyLearning:
    def check_approval_confidence(self, _action, _params):
        return {"auto_approve": True}

    def generate_smart_hint(self, last_error=None):
        _ = last_error
        return None


def _make_agent(execute):
    agent = Agent()
    agent.kernel = _Kernel(execute)
    agent.learning = _DummyLearning()
    return agent


class _AllowPolicy:
    def check_access(self, _tool_name):
        return {"allowed": True, "requires_approval": False, "reason": "ok"}

    def infer_group(self, _tool_name):
        return None


ALLOW_GUARD = {"allowed": True, "requires_approval": False, "reason": "ok", "risk": "low"}


@pytest.fixture
def allow_execution():
    with patch("core.agent.runtime_security_guard.evaluate", return_value=dict(ALLOW_GUARD)), patch(
        "core.agent.tool_policy",
        new=_AllowPolicy(),
    ):
        yield


@pytest.mark.asyncio
async def test_agent_execute_tool_normalizes_kernel_success(allow_execution):
    agent = _make_agent(AsyncMock(return_value={"success": True, "message": "ok"}))

    result = await agent._execute_tool("custom_tool", {"x": 1})

    assert result["success"] is True
    assert result["status"] == "success"
    assert result["message"] == "ok"
    assert result["metrics"]["agent_source"] == "agent_kernel_execute"
    assert result["_tool_result"]["status"] == "success"


@pytest.mark.asyncio
async def test_agent_execute_tool_normalizes_fallback_malformed_output(monkeypatch, allow_execution):
    agent = _make_agent(AsyncMock(side_effect=ValueError("not found")))

    async def _malformed_tool(**_kwargs):
        return None

    monkeypatch.setattr("core.agent.AVAILABLE_TOOLS", {"custom_tool": _malformed_tool})

    result = await agent._execute_tool("custom_tool", {})

    assert result["success"] is False
    assert result["status"] == "failed"
    assert result["error_code"] == "TOOL_CONTRACT_VIOLATION"
    assert result["metrics"]["agent_source"] == "agent_fallback_callable"
    assert result["_tool_result"]["status"] == "failed"


@pytest.mark.asyncio
async def test_agent_execute_tool_normalizes_unknown_tool(monkeypatch, allow_execution):
    agent = _make_agent(AsyncMock(side_effect=ValueError("not found")))
    monkeypatch.setattr("core.agent.AVAILABLE_TOOLS", {})

    result = await agent._execute_tool("missing_tool", {})

    assert result["success"] is False
    assert result["status"] == "failed"
    assert result["error_code"] == "UNKNOWN_TOOL"
    assert result["metrics"]["agent_source"] == "agent_fallback_lookup"


@pytest.mark.asyncio
async def test_agent_execute_tool_standardizes_timeout(monkeypatch, allow_execution):
    agent = _make_agent(AsyncMock(return_value={"success": True}))

    async def _timeout(awaitable, **_kwargs):
        if inspect.iscoroutine(awaitable):
            awaitable.close()
        raise asyncio.TimeoutError()

    monkeypatch.setattr("core.agent.with_timeout", _timeout)

    result = await agent._execute_tool("custom_tool", {})

    assert result["success"] is False
    assert result["status"] == "failed"
    assert result["error_code"] == "TIMEOUT"
    assert result["metrics"]["agent_source"] == "agent_execute_tool"


@pytest.mark.asyncio
async def test_agent_execute_tool_standardizes_kernel_exception(allow_execution):
    agent = _make_agent(AsyncMock(side_effect=RuntimeError("kaput")))

    result = await agent._execute_tool("custom_tool", {})

    assert result["success"] is False
    assert result["status"] == "failed"
    assert result["error_code"] == "EXECUTION_EXCEPTION"
    assert result["data"]["exception_type"] == "RuntimeError"
    assert result["metrics"]["agent_source"] == "agent_execute_tool"


@pytest.mark.parametrize(
    ("payload", "expected_status", "expected_success"),
    [
        ({"status": "partial", "message": "kismi"}, "partial", True),
        ({"status": "blocked", "message": "approval gerekli"}, "blocked", False),
        ({"status": "needs_input", "message": "dosya adi gerekli"}, "needs_input", False),
        ({"success": False, "status": "failed", "error": "boom"}, "failed", False),
    ],
)
@pytest.mark.asyncio
async def test_agent_execute_tool_propagates_fallback_statuses(monkeypatch, allow_execution, payload, expected_status, expected_success):
    agent = _make_agent(AsyncMock(side_effect=ValueError("not found")))

    async def _status_tool(**_kwargs):
        return dict(payload)

    monkeypatch.setattr("core.agent.AVAILABLE_TOOLS", {"custom_tool": _status_tool})

    result = await agent._execute_tool("custom_tool", {})

    assert result["status"] == expected_status
    assert result["success"] is expected_success
    assert result["metrics"]["agent_source"] == "agent_fallback_callable"
    assert result["_tool_result"]["status"] == expected_status
