import pytest
from types import SimpleNamespace

from core.sub_agent.shared_state import TeamTask
from core.sub_agent.team import AgentTeam, TeamConfig


class _DummyAgent:
    async def _execute_tool(self, tool_name, params, **kwargs):
        _ = (kwargs, tool_name)
        return {"success": True, "message": params.get("message", "ok")}


@pytest.mark.asyncio
async def test_agent_team_scheduler_respects_dependencies(monkeypatch):
    team = AgentTeam(_DummyAgent(), TeamConfig(use_llm_planner=False, max_parallel=2, max_retries_per_task=0))

    t1 = TeamTask(title="Aşama 1", specialist="researcher", action="chat", params={"message": "a"})
    t2 = TeamTask(title="Aşama 2", specialist="builder", action="chat", params={"message": "b"}, depends_on=[t1.task_id])
    t3 = TeamTask(title="Aşama 3", specialist="qa", action="chat", params={"message": "c"}, depends_on=[t2.task_id])

    async def _fake_build(self, brief):
        _ = brief
        return [t1, t2, t3], {"stage_count": 3}

    monkeypatch.setattr(AgentTeam, "_build_team_tasks", _fake_build, raising=False)

    result = await team.execute_project("bağımlı görevleri sırayla çalıştır")
    assert result.status == "success"

    finished = [o["task_id"] for o in result.outputs if o.get("status") != "retrying"]
    assert finished.index(t1.task_id) < finished.index(t2.task_id) < finished.index(t3.task_id)


@pytest.mark.asyncio
async def test_agent_team_build_tasks_from_numbered_brief_when_planner_empty(monkeypatch):
    team = AgentTeam(_DummyAgent(), TeamConfig(use_llm_planner=False, max_parallel=2, max_tasks=6))

    async def _fake_create_plan(self, **kwargs):
        _ = (self, kwargs)
        return SimpleNamespace(subtasks=[])

    monkeypatch.setattr("core.intelligent_planner.IntelligentPlanner.create_plan", _fake_create_plan)

    tasks, _graph = await team._build_team_tasks(
        "1) Desktop'ta klasör oluştur 2) not.md dosyasını yaz 3) sonucu doğrula"
    )
    assert len(tasks) >= 3
    assert tasks[1].depends_on == [tasks[0].task_id]
    assert tasks[2].depends_on == [tasks[1].task_id]
    assert tasks[0].action in {"create_folder", "write_file", "list_files", "chat"}
