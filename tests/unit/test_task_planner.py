from __future__ import annotations

import asyncio

import pytest

import tools
from tools.planning_tools.task_planner import ExecutionMode, Plan, Task, TaskPlanner, TaskStatus


@pytest.fixture
def planner():
    planner = TaskPlanner()
    planner._plans.clear()
    planner.set_tool_executor(None)
    yield planner
    planner._plans.clear()
    planner.set_tool_executor(None)


@pytest.mark.asyncio
async def test_task_planner_fallback_executes_via_task_executor(monkeypatch, planner):
    async def planner_tool(path=""):
        return {"success": True, "message": f"raw:{path}"}

    tools._loaded_tools["planner_fallback_tool"] = planner_tool
    seen: dict[str, object] = {}

    async def fake_execute(self, tool_func, params):
        seen["tool_name"] = getattr(tool_func, "__name__", "")
        seen["params"] = dict(params)
        return {
            "success": True,
            "status": "success",
            "message": "normalized-ok",
            "_tool_result": {"status": "success"},
        }

    monkeypatch.setattr("core.task_executor.TaskExecutor.execute", fake_execute)

    task = Task(id="task_1", name="Planner fallback", action="planner_fallback_tool", params={"path": "/tmp/x"})
    plan = Plan(id="plan_1", name="Plan", description="desc", tasks=[task], execution_mode=ExecutionMode.SEQUENTIAL)

    try:
        await planner._execute_task(task, plan)
    finally:
        tools._loaded_tools.pop("planner_fallback_tool", None)

    assert seen["tool_name"] == "planner_tool"
    assert seen["params"] == {"path": "/tmp/x"}
    assert task.status == TaskStatus.COMPLETED
    assert plan.results["task_1"]["status"] == "success"
    assert plan.results["task_1"]["_tool_result"]["status"] == "success"


@pytest.mark.asyncio
async def test_task_planner_fallback_timeout_is_normalized(monkeypatch, planner):
    monkeypatch.setattr("core.task_executor.TASK_TIMEOUT", 0.01)

    async def slow_tool():
        await asyncio.sleep(0.05)
        return {"success": True}

    tools._loaded_tools["planner_slow_tool"] = slow_tool
    task = Task(id="task_2", name="Slow task", action="planner_slow_tool", params={})
    plan = Plan(id="plan_2", name="Plan", description="desc", tasks=[task], execution_mode=ExecutionMode.SEQUENTIAL)

    try:
        await planner._execute_task(task, plan)
    finally:
        tools._loaded_tools.pop("planner_slow_tool", None)

    assert task.status == TaskStatus.FAILED
    assert plan.results["task_2"]["status"] == "failed"
    assert plan.results["task_2"]["error_code"] == "TIMEOUT"
    assert plan.results["task_2"]["errors"] == ["TIMEOUT"]


@pytest.mark.asyncio
async def test_task_planner_unknown_tool_returns_normalized_failure(planner):
    task = Task(id="task_3", name="Unknown task", action="missing_planner_tool_xyz", params={})
    plan = Plan(id="plan_3", name="Plan", description="desc", tasks=[task], execution_mode=ExecutionMode.SEQUENTIAL)

    await planner._execute_task(task, plan)

    assert task.status == TaskStatus.FAILED
    assert task.error == "Bilinmeyen action: missing_planner_tool_xyz"
    assert plan.results["task_3"]["success"] is False
    assert plan.results["task_3"]["status"] == "failed"
    assert plan.results["task_3"]["error_code"] == "UNKNOWN_TOOL"
    assert plan.results["task_3"]["errors"] == ["UNKNOWN_TOOL"]
