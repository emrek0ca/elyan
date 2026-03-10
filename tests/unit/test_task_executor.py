from __future__ import annotations

import asyncio
from datetime import datetime

import pytest

from core.task_executor import TaskExecutor


@pytest.mark.asyncio
async def test_task_executor_normalizes_success_result():
    executor = TaskExecutor()

    async def wrapped_success():
        return {
            "success": True,
            "status": "success",
            "message": "ok",
            "artifact_manifest": [{"path": "/tmp/out.txt", "type": "text"}],
            "_tool_result": {"status": "success"},
        }

    result = await executor.execute(wrapped_success, {})

    assert result["success"] is True
    assert result["status"] == "success"
    assert result["message"] == "ok"
    assert result["metrics"]["executor_duration_ms"] >= 0
    assert result["_tool_result"]["status"] == "success"


@pytest.mark.asyncio
async def test_task_executor_normalizes_partial_result_as_success():
    executor = TaskExecutor()

    async def partial_tool():
        return {"status": "partial", "message": "kismi tamamlandi"}

    result = await executor.execute(partial_tool, {})

    assert result["success"] is True
    assert result["status"] == "partial"
    assert result["message"] == "kismi tamamlandi"
    assert executor.task_history[-1]["success"] is True


@pytest.mark.asyncio
async def test_task_executor_normalizes_failed_result():
    executor = TaskExecutor()

    async def failed_tool():
        return {"success": False, "error": "boom"}

    result = await executor.execute(failed_tool, {})

    assert result["success"] is False
    assert result["status"] == "failed"
    assert result["error"] == "boom"
    assert result["errors"] == ["boom"]


@pytest.mark.asyncio
async def test_task_executor_normalizes_blocked_result():
    executor = TaskExecutor()

    async def blocked_tool():
        return {"status": "blocked", "message": "approval gerekli"}

    result = await executor.execute(blocked_tool, {})

    assert result["success"] is False
    assert result["status"] == "blocked"
    assert result["message"] == "approval gerekli"


@pytest.mark.asyncio
async def test_task_executor_normalizes_needs_input_result():
    executor = TaskExecutor()

    async def needs_input_tool():
        return {"status": "needs_input", "message": "dosya adi gerekli"}

    result = await executor.execute(needs_input_tool, {})

    assert result["success"] is False
    assert result["status"] == "needs_input"
    assert result["message"] == "dosya adi gerekli"


@pytest.mark.asyncio
async def test_task_executor_normalizes_malformed_legacy_output():
    executor = TaskExecutor()

    async def malformed_tool():
        return None

    result = await executor.execute(malformed_tool, {})

    assert result["success"] is False
    assert result["status"] == "failed"
    assert result["error_code"] == "TOOL_CONTRACT_VIOLATION"
    assert result["errors"] == ["TOOL_CONTRACT_VIOLATION"]


@pytest.mark.asyncio
async def test_task_executor_standardizes_timeout(monkeypatch):
    monkeypatch.setattr("core.task_executor.TASK_TIMEOUT", 0.01)
    executor = TaskExecutor()

    async def slow_tool():
        await asyncio.sleep(0.05)
        return {"success": True}

    result = await executor.execute(slow_tool, {})

    assert result["success"] is False
    assert result["status"] == "failed"
    assert result["error_code"] == "TIMEOUT"
    assert result["errors"] == ["TIMEOUT"]


@pytest.mark.asyncio
async def test_task_executor_standardizes_circuit_breaker_block():
    executor = TaskExecutor()

    async def blocked_by_breaker():
        return {"success": True}

    breaker = executor._get_tool_breaker("blocked_by_breaker")
    breaker.is_open = True
    breaker.opened_at = datetime.now()

    result = await executor.execute(blocked_by_breaker, {})

    assert result["success"] is False
    assert result["status"] == "blocked"
    assert result["error_code"] == "CIRCUIT_BREAKER_OPEN"
    assert result["data"]["blocker"] == "tool_circuit_breaker"


@pytest.mark.asyncio
async def test_task_executor_standardizes_execution_exception():
    executor = TaskExecutor()

    async def exploding_tool():
        raise RuntimeError("kaput")

    result = await executor.execute(exploding_tool, {})

    assert result["success"] is False
    assert result["status"] == "failed"
    assert result["error_code"] == "EXECUTION_EXCEPTION"
    assert result["data"]["exception_type"] == "RuntimeError"


@pytest.mark.asyncio
async def test_task_executor_handles_sync_tool_outputs():
    executor = TaskExecutor()

    def sync_tool():
        return {"success": True, "message": "sync-ok"}

    result = await executor.execute(sync_tool, {})

    assert result["success"] is True
    assert result["status"] == "success"
    assert result["message"] == "sync-ok"
