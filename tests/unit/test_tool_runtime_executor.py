from types import SimpleNamespace

import pytest

from core.agent import Agent
from core.tool_runtime import ExecutionRequest, ToolRuntimeExecutor, VerificationEnvelope


class _NoopMemory:
    def get_recent_conversations(self, user_id, limit=5):
        _ = (user_id, limit)
        return []

    def store_conversation(self, user_id, user_input, bot_response):
        _ = (user_id, user_input, bot_response)
        return None


class _Kernel:
    def __init__(self):
        self.memory = _NoopMemory()
        self.tools = SimpleNamespace(execute=None)


class _FakeExecutor:
    def __init__(self):
        self.requests = []

    async def execute(self, agent, request):
        self.requests.append((agent, request))
        return {"success": True, "status": "success", "message": "ok"}


def _make_agent() -> Agent:
    agent = Agent.__new__(Agent)
    agent.kernel = _Kernel()
    agent.current_user_id = "user-1"
    return agent


@pytest.mark.asyncio
async def test_agent_execute_tool_delegates_to_tool_runtime_executor(monkeypatch):
    fake = _FakeExecutor()
    monkeypatch.setattr("core.agent.get_tool_runtime_executor", lambda: fake)

    agent = _make_agent()
    result = await Agent._execute_tool(
        agent,
        "research",
        {"query": "elyan"},
        user_input="elyan nedir",
        step_name="Araştır",
    )

    assert result["success"] is True
    assert fake.requests
    _agent, request = fake.requests[0]
    assert isinstance(request, ExecutionRequest)
    assert request.tool_name == "research"
    assert request.params == {"query": "elyan"}
    assert request.step_name == "Araştır"


def test_tool_runtime_executor_resolve_spec_applies_aliases_and_metadata():
    executor = ToolRuntimeExecutor()
    agent = SimpleNamespace(
        _resolve_tool_name=lambda tool_name: "web_search" if tool_name == "web_search" else tool_name,
        _should_upgrade_research_to_delivery=lambda _text, _params: False,
        _normalize_param_aliases=lambda _tool, params: dict(params),
    )

    spec = executor._resolve_spec(
        agent,
        ExecutionRequest(
            tool_name="search_web",
            params={"query": "elyan"},
            action_aliases={"search_web": "web_search"},
        ),
    )

    assert spec.requested_name == "search_web"
    assert spec.resolved_name == "web_search"
    assert spec.params == {"query": "elyan"}


def test_verification_envelope_extracts_runtime_fields():
    envelope = VerificationEnvelope.from_result(
        {
            "verified": False,
            "verification_warning": "screen mismatch",
            "_proof": {"screenshot": "/tmp/proof.png"},
            "error_code": "VERIFY_FAILED",
            "status": "failed",
        }
    )

    assert envelope.verified is False
    assert envelope.warning == "screen mismatch"
    assert envelope.evidence["screenshot"] == "/tmp/proof.png"
    assert envelope.metadata["error_code"] == "VERIFY_FAILED"


def test_tool_runtime_executor_mode_policy_blocks_messaging_in_coding_mode():
    decision = ToolRuntimeExecutor._evaluate_mode_policy(
        "send_message",
        {"metadata": {"agent_mode": "coding"}},
        user_id="user-1",
    )

    assert decision["enabled"] is True
    assert decision["mode"] == "coding"
    assert decision["tool_group"] == "messaging"
    assert decision["allowed"] is False
