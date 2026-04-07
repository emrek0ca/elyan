"""
Phase 6.4 — Workflow Orchestration — Test Suite (15 tests)
"""

import pytest
from unittest.mock import patch, AsyncMock

from core.workflow import (
    get_workflow_engine,
    WorkflowDefinition,
    WorkflowResult,
    format_text,
    format_json,
    format_md,
)
from core.workflow.state_machine import WorkflowState, WorkflowStateMachine


SIMPLE_SPEC = {
    "name": "Test Workflow",
    "description": "Simple test",
    "steps": [
        {"name": "step1", "action": "shell", "params": {"command": "echo hello"}},
        {"name": "step2", "action": "python", "params": {"code": "print(42)"}},
    ],
}


@pytest.fixture
def workflow_engine():
    """Get singleton WorkflowEngine."""
    return get_workflow_engine()


@pytest.fixture
def mock_shell():
    """Mock shell execution."""
    with patch("tools.code_execution_tools.execute_shell_command") as mock:
        mock.return_value = {"success": True, "output": "shell output", "return_code": 0}
        yield mock


@pytest.fixture
def mock_python():
    """Mock python execution."""
    with patch("tools.code_execution_tools.execute_python_code") as mock:
        mock.return_value = {"success": True, "output": "python output", "return_code": 0}
        yield mock


# ────────────────────────────────────────────────────────────────────────────
# WorkflowEngine Tests
# ────────────────────────────────────────────────────────────────────────────

def test_workflow_engine_singleton():
    """Test: WorkflowEngine is singleton."""
    engine1 = get_workflow_engine()
    engine2 = get_workflow_engine()
    assert engine1 is engine2


def test_create_returns_definition(workflow_engine):
    """Test: create() returns WorkflowDefinition."""
    result = workflow_engine.create(
        name="Test WF",
        steps=[{"name": "step1", "action": "shell", "params": {"command": "ls"}}],
    )

    assert result is not None
    assert result.name == "Test WF"
    assert len(result.steps) == 1


@pytest.mark.asyncio
async def test_run_simple_workflow(workflow_engine, mock_shell, mock_python):
    """Test: run_inline executes steps."""
    result = await workflow_engine.run_inline(
        steps=SIMPLE_SPEC["steps"],
        name=SIMPLE_SPEC["name"],
    )

    assert result.success
    assert result.steps_done == 2
    assert result.steps_failed == 0
    assert len(result.outputs) == 2


@pytest.mark.asyncio
async def test_all_steps_execute_in_order(workflow_engine, mock_shell, mock_python):
    """Test: steps execute sequentially."""
    step_order = []

    async def mock_shell_track(*args, **kwargs):
        step_order.append("shell")
        return {"success": True, "output": "", "return_code": 0}

    async def mock_python_track(*args, **kwargs):
        step_order.append("python")
        return {"success": True, "output": "", "return_code": 0}

    with patch("tools.code_execution_tools.execute_shell_command", side_effect=mock_shell_track):
        with patch("tools.code_execution_tools.execute_python_code", side_effect=mock_python_track):
            result = await workflow_engine.run_inline(
                steps=SIMPLE_SPEC["steps"],
                name="Test",
            )

    assert step_order == ["shell", "python"]


@pytest.mark.asyncio
async def test_step_failure_abort(workflow_engine):
    """Test: on_failure=abort stops execution."""
    with patch("tools.code_execution_tools.execute_shell_command") as mock_shell:
        mock_shell.side_effect = Exception("Command failed")

        result = await workflow_engine.run_inline(
            steps=[
                {"name": "step1", "action": "shell", "params": {"command": "false"}, "on_failure": "abort"},
                {"name": "step2", "action": "shell", "params": {"command": "echo"}, "on_failure": "abort"},
            ],
            name="Test",
        )

    # Only step1 should attempt, step2 should be skipped
    assert result.steps_failed > 0
    assert mock_shell.call_count == 1  # Only called once


@pytest.mark.asyncio
async def test_step_failure_continue(workflow_engine, mock_shell):
    """Test: on_failure=continue continues."""
    with patch("tools.code_execution_tools.execute_shell_command") as mock_shell:
        # First call fails, second succeeds
        mock_shell.side_effect = [
            Exception("Step1 failed"),
            {"success": True, "output": "Step2", "return_code": 0},
        ]

        result = await workflow_engine.run_inline(
            steps=[
                {"name": "step1", "action": "shell", "params": {"command": "false"}, "on_failure": "continue"},
                {"name": "step2", "action": "shell", "params": {"command": "true"}, "on_failure": "continue"},
            ],
            name="Test",
        )

    # Both steps should attempt
    assert mock_shell.call_count == 2


@pytest.mark.asyncio
async def test_run_inline(workflow_engine, mock_shell, mock_python):
    """Test: run_inline without persistence."""
    result = await workflow_engine.run_inline(
        steps=SIMPLE_SPEC["steps"],
        name="Inline Test",
    )

    assert result.workflow_id == "inline"
    assert result.name == "Inline Test"


def test_list_returns_created(workflow_engine):
    """Test: list() shows created workflows."""
    workflow_engine.create(
        name="WF1",
        steps=[{"name": "s1", "action": "shell", "params": {"command": "ls"}}],
    )

    workflows = workflow_engine.list()
    names = [wf["name"] for wf in workflows]

    assert "WF1" in names


def test_get_nonexistent_returns_none(workflow_engine):
    """Test: get() returns None for missing workflow."""
    result = workflow_engine.get("nonexistent-123")
    assert result is None


def test_delete_workflow(workflow_engine):
    """Test: delete() removes workflow."""
    wf = workflow_engine.create(
        name="Temp",
        steps=[{"name": "s1", "action": "shell", "params": {"command": "ls"}}],
    )

    success = workflow_engine.delete(wf.workflow_id)
    assert success

    retrieved = workflow_engine.get(wf.workflow_id)
    assert retrieved is None


# ────────────────────────────────────────────────────────────────────────────
# WorkflowStateMachine Tests
# ────────────────────────────────────────────────────────────────────────────

def test_state_machine_start_run():
    """Test: start_run() creates WorkflowRun."""
    sm = WorkflowStateMachine()
    run = sm.start_run("workflow-123")

    assert run is not None
    assert run.workflow_id == "workflow-123"
    assert run.state == WorkflowState.IDLE
    assert run.state.value == "received"


def test_transition_to_done():
    """Test: transition_to() DONE state."""
    sm = WorkflowStateMachine()
    run = sm.start_run("workflow-123")

    run.transition_to(WorkflowState.RUNNING)
    assert run.state == WorkflowState.RUNNING

    run.transition_to(WorkflowState.DONE)
    assert run.state == WorkflowState.DONE
    assert len(run.history) == 2


def test_transition_to_failed():
    """Test: transition_to() FAILED state."""
    sm = WorkflowStateMachine()
    run = sm.start_run("workflow-123")

    run.transition_to(WorkflowState.RUNNING)
    run.transition_to(WorkflowState.FAILED, {"error": "Step 2 failed"})

    assert run.state == WorkflowState.FAILED
    assert run.history[-1]["metadata"]["error"] == "Step 2 failed"


def test_canonical_state_chain():
    """Test: canonical lifecycle transitions stay legal."""
    sm = WorkflowStateMachine()
    run = sm.start_run("workflow-123")

    run.transition_to(WorkflowState.CLASSIFIED)
    run.transition_to(WorkflowState.SCOPED)
    run.transition_to(WorkflowState.PLANNED)
    run.transition_to(WorkflowState.GATHERING_CONTEXT)
    run.transition_to(WorkflowState.EXECUTING)
    run.transition_to(WorkflowState.REVIEWING)
    run.transition_to(WorkflowState.EXPORTING)
    run.transition_to(WorkflowState.COMPLETED)

    assert run.state == WorkflowState.COMPLETED


def test_illegal_transition_rejected():
    """Test: illegal transitions raise ValueError."""
    sm = WorkflowStateMachine()
    run = sm.start_run("workflow-123")
    run.transition_to(WorkflowState.EXECUTING)
    run.transition_to(WorkflowState.COMPLETED)

    with pytest.raises(ValueError):
        run.transition_to(WorkflowState.EXECUTING)


# ────────────────────────────────────────────────────────────────────────────
# Formatter Tests
# ────────────────────────────────────────────────────────────────────────────

def test_format_text():
    """Test: text formatter."""
    result = WorkflowResult(
        success=True,
        workflow_id="wf-1",
        name="Test",
        steps_total=2,
        steps_done=2,
        steps_failed=0,
        outputs=[
            {"name": "step1", "success": True, "output": "Output1", "duration": 0.5},
            {"name": "step2", "success": True, "output": "Output2", "duration": 0.3},
        ],
        elapsed=0.8,
    )

    output = format_text(result)
    assert "Test" in output
    assert "✓" in output
    assert "2/2" in output


def test_format_json():
    """Test: JSON formatter produces valid JSON."""
    import json as json_lib
    result = WorkflowResult(
        success=True,
        workflow_id="wf-1",
        name="JSON Test",
        steps_total=1,
        steps_done=1,
        steps_failed=0,
    )

    output = format_json(result)
    data = json_lib.loads(output)

    assert data["success"]
    assert data["name"] == "JSON Test"


def test_format_md():
    """Test: Markdown formatter has header."""
    result = WorkflowResult(
        success=True,
        workflow_id="wf-1",
        name="MD Test",
        steps_total=2,
        steps_done=2,
        steps_failed=0,
        outputs=[
            {"name": "build", "success": True, "output": "Built", "duration": 1.0},
            {"name": "test", "success": True, "output": "Tests passed", "duration": 2.0},
        ],
    )

    output = format_md(result)
    assert "#" in output
    assert "build" in output
    assert "test" in output


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
