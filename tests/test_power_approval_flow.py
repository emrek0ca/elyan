import asyncio

from core.task_engine import TaskEngine, TaskDefinition
from security.approval import RiskLevel, get_approval_manager


def test_build_task_definitions_marks_power_actions_as_requires_approval():
    engine = TaskEngine()
    tasks = engine._build_task_definitions(
        [
            {"id": "task_1", "action": "shutdown_system", "params": {}, "description": "power off"},
            {"id": "task_2", "action": "list_files", "params": {}, "description": "list"},
        ],
        max_steps=5,
    )

    assert len(tasks) == 2
    assert tasks[0].requires_approval is True
    assert tasks[1].requires_approval is False


def test_execute_tasks_blocks_power_action_when_approval_denied():
    engine = TaskEngine()

    class DenyApproval:
        async def request_approval(self, **kwargs):
            return {"approved": False, "reason": "Kullanıcı reddetti"}

    class FailingExecutor:
        async def execute(self, *_args, **_kwargs):
            raise AssertionError("Power command should not execute without approval")

    engine.approval = DenyApproval()
    engine.executor = FailingExecutor()

    tasks = [
        TaskDefinition(
            id="task_1",
            action="shutdown_system",
            params={},
            description="Sistemi kapat",
            requires_approval=True,
        )
    ]

    result = asyncio.run(engine._execute_tasks(tasks, notify_callback=None, user_id="42"))
    assert result["success"] is False
    assert result["failed"] == 1
    assert result["succeeded"] == 0
    row = result["data"]["results"][0]
    assert row["success"] is False
    assert "reddetti" in row["error"].lower()


def test_execute_tasks_runs_power_action_when_approved():
    engine = TaskEngine()

    class ApproveApproval:
        async def request_approval(self, **kwargs):
            return {"approved": True}

    class SuccessExecutor:
        async def execute(self, tool_func, params):
            return await tool_func(**params)

    engine.approval = ApproveApproval()
    engine.executor = SuccessExecutor()

    tasks = [
        TaskDefinition(
            id="task_1",
            action="shutdown_system",
            params={},
            description="Sistemi kapat",
            requires_approval=True,
        )
    ]

    # Avoid actually shutting down the system: patch task_engine registry directly.
    import tools
    import core.task_engine as task_engine_module
    original = task_engine_module.AVAILABLE_TOOLS["shutdown_system"]

    async def fake_shutdown_system():
        return {"success": True, "message": "stub lock"}

    tools._loaded_tools["shutdown_system"] = fake_shutdown_system
    try:
        result = asyncio.run(engine._execute_tasks(tasks, notify_callback=None, user_id="42"))
    finally:
        tools._loaded_tools["shutdown_system"] = original

    assert result["success"] is True
    assert result["failed"] == 0
    assert result["succeeded"] == 1


def test_power_actions_are_classified_as_high_or_critical_risk():
    approval_manager = get_approval_manager()

    assert approval_manager.classify_operation_risk("shutdown_system", {}) == RiskLevel.CRITICAL
    assert approval_manager.classify_operation_risk("restart_system", {}) == RiskLevel.CRITICAL
    assert approval_manager.classify_operation_risk("sleep_system", {}) == RiskLevel.HIGH
    assert approval_manager.classify_operation_risk("lock_screen", {}) == RiskLevel.HIGH
