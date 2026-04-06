import pytest
from types import SimpleNamespace

from core.sub_agent.executor import SubAgentExecutor
from core.sub_agent.session import SubAgentSession, SubAgentTask


class _DummyAgent:
    def __init__(self):
        self.calls = []

    async def _execute_tool(self, tool_name, params, **kwargs):
        _ = kwargs
        self.calls.append((tool_name, dict(params or {})))
        if tool_name == "blocked":
            return {"success": False, "error": "blocked"}
        return {"success": True, "path": params.get("path", "")}


class _DummyLLM:
    def __init__(self, response: str):
        self.response = response

    async def generate(self, prompt, **kwargs):
        return self.response


@pytest.mark.asyncio
async def test_executor_enforces_allowed_tools():
    sess = SubAgentSession(
        session_id="s1",
        parent_session_id="p",
        specialist_key="qa",
        task=SubAgentTask(name="t", action="blocked", params={}),
        allowed_tools=frozenset({"chat"}),
    )
    ex = SubAgentExecutor(_DummyAgent())
    res = await ex.run(sess)
    assert res.status == "failed"


@pytest.mark.asyncio
async def test_executor_collects_artifacts():
    sess = SubAgentSession(
        session_id="s2",
        parent_session_id="p",
        specialist_key="builder",
        task=SubAgentTask(name="t", action="write_file", params={"path": "/tmp/a.txt"}),
        allowed_tools=frozenset({"write_file"}),
    )
    ex = SubAgentExecutor(_DummyAgent())
    res = await ex.run(sess)
    assert res.status in {"success", "partial"}


@pytest.mark.asyncio
async def test_executor_chat_without_llm_still_executes():
    sess = SubAgentSession(
        session_id="s3",
        parent_session_id="p",
        specialist_key="researcher",
        task=SubAgentTask(name="t", action="chat", params={"message": "özetle"}),
        allowed_tools=frozenset({"chat"}),
    )
    ex = SubAgentExecutor(_DummyAgent())
    res = await ex.run(sess)
    assert res.status in {"success", "partial"}


@pytest.mark.asyncio
async def test_executor_uses_llm_json_tool_directive():
    agent = _DummyAgent()
    agent.llm = _DummyLLM('{"action":"write_file","params":{"path":"/tmp/llm.txt"},"done":false}')
    sess = SubAgentSession(
        session_id="s4",
        parent_session_id="p",
        specialist_key="builder",
        task=SubAgentTask(name="t", action="chat", params={"message": "dosya yaz"}),
        allowed_tools=frozenset({"write_file"}),
    )
    ex = SubAgentExecutor(agent)
    res = await ex.run(sess)
    assert res.status in {"success", "partial"}
    assert "/tmp/llm.txt" in (res.artifacts or [])


@pytest.mark.asyncio
async def test_executor_done_string_false_does_not_short_circuit():
    agent = _DummyAgent()
    agent.llm = _DummyLLM('{"action":"write_file","params":{"path":"/tmp/false-done.txt"},"done":"false"}')
    sess = SubAgentSession(
        session_id="s5",
        parent_session_id="p",
        specialist_key="builder",
        task=SubAgentTask(name="t", action="chat", params={"message": "dosya yaz"}),
        allowed_tools=frozenset({"write_file"}),
    )
    ex = SubAgentExecutor(agent)
    res = await ex.run(sess)
    assert res.status in {"success", "partial"}
    assert any(c[0] == "write_file" for c in agent.calls)


@pytest.mark.asyncio
async def test_executor_accepts_top_level_llm_tool_params():
    agent = _DummyAgent()
    agent.llm = _DummyLLM('{"tool":"write_file","path":"/tmp/top-level.txt","done":false}')
    sess = SubAgentSession(
        session_id="s6",
        parent_session_id="p",
        specialist_key="builder",
        task=SubAgentTask(name="t", action="chat", params={"message": "dosya yaz"}),
        allowed_tools=frozenset({"write_file"}),
    )
    ex = SubAgentExecutor(agent)
    res = await ex.run(sess)
    assert res.status in {"success", "partial"}
    assert "/tmp/top-level.txt" in (res.artifacts or [])


@pytest.mark.asyncio
async def test_executor_planner_fallback_generates_tool_when_llm_missing(monkeypatch):
    agent = _DummyAgent()

    async def _fake_create_plan(self, **kwargs):
        _ = (self, kwargs)
        return SimpleNamespace(
            subtasks=[
                SimpleNamespace(action="list_files", params={"path": "~/Desktop"}),
            ]
        )

    monkeypatch.setattr("core.intelligent_planner.IntelligentPlanner.create_plan", _fake_create_plan)

    sess = SubAgentSession(
        session_id="s7",
        parent_session_id="p",
        specialist_key="ops",
        task=SubAgentTask(name="t", action="chat", description="masaüstündeki dosyaları listele"),
        allowed_tools=frozenset({"list_files"}),
    )
    ex = SubAgentExecutor(agent)
    res = await ex.run(sess)
    assert res.status in {"success", "partial"}
    assert any(call[0] == "list_files" for call in agent.calls)
