import pytest

from core.sub_agent.manager import SubAgentManager
from core.sub_agent.session import SubAgentTask


class _DummyAgent:
    async def _execute_tool(self, tool_name, params, **kwargs):
        _ = kwargs
        return {"success": True, "tool": tool_name, "params": params}


@pytest.mark.asyncio
async def test_spawn_parallel_collects_results():
    mgr = SubAgentManager(_DummyAgent(), parent_session_id="p1")
    jobs = [
        ("researcher", SubAgentTask(name="r1", action="chat", params={"message": "a"})),
        ("builder", SubAgentTask(name="b1", action="chat", params={"message": "b"})),
    ]

    results = await mgr.spawn_parallel(jobs, timeout=10)
    assert len(results) == 2
    assert all(r.status in {"success", "partial"} for r in results)


@pytest.mark.asyncio
async def test_spawn_and_wait_returns_result():
    mgr = SubAgentManager(_DummyAgent(), parent_session_id="p2")
    result = await mgr.spawn_and_wait("ops", SubAgentTask(name="ops", action="chat", params={"message": "ok"}), timeout=10)
    assert result.status in {"success", "partial"}


@pytest.mark.asyncio
async def test_spawn_and_wait_fails_when_validation_gate_fails():
    mgr = SubAgentManager(_DummyAgent(), parent_session_id="p3", max_validation_retries=1)
    task = SubAgentTask(
        name="gate",
        action="chat",
        params={"message": "çıktı üret"},
        gates=["file_exists"],
    )
    result = await mgr.spawn_and_wait("builder", task, timeout=10)
    assert result.status == "failed"
    assert isinstance(result.result, dict)
    assert result.result.get("error") == "validation_failed"
