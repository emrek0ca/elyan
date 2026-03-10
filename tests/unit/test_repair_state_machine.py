from __future__ import annotations

import json

import pytest

from core.repair.error_codes import INTENT_ERROR, TOOL_ERROR
from core.repair.state_machine import RepairStateMachine


@pytest.mark.asyncio
async def test_repair_state_machine_emits_started_and_finished_events(monkeypatch, tmp_path):
    monkeypatch.setenv("ELYAN_RUNS_DIR", str(tmp_path / "runs"))
    machine = RepairStateMachine(max_attempts=2)
    attempts: list[int] = []

    async def attempt_fn(attempt_idx, _context):
        attempts.append(attempt_idx)
        return {"success": attempt_idx == 2, "error": "" if attempt_idx == 2 else "transient"}

    outcome = await machine.run(
        TOOL_ERROR,
        attempt_fn,
        context={"request_id": "run_repair_success_001", "tool": "write_file"},
    )

    assert outcome.success is True
    assert attempts == [1, 2]

    trace_path = tmp_path / "runs" / "run_repair_success_001" / "trace.jsonl"
    lines = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert [row["event"] for row in lines] == ["repair.started", "repair.finished"]
    assert lines[0]["retry_count"] == 0
    assert lines[1]["status"] == "success"
    assert lines[1]["retry_count"] == 2
    assert lines[1]["payload"]["attempts_used"] == 2
    assert lines[1]["payload"]["max_attempts"] == 2
    assert lines[1]["payload"]["retry_budget_remaining"] == 0


@pytest.mark.asyncio
async def test_repair_state_machine_emits_non_retryable_finish_metadata(monkeypatch, tmp_path):
    monkeypatch.setenv("ELYAN_RUNS_DIR", str(tmp_path / "runs"))
    machine = RepairStateMachine(max_attempts=2)

    async def attempt_fn(_attempt_idx, _context):
        raise AssertionError("attempt_fn should not be called for non-retryable errors")

    outcome = await machine.run(
        INTENT_ERROR,
        attempt_fn,
        context={"request_id": "run_repair_non_retryable_001", "tool": "write_file"},
    )

    assert outcome.success is False
    assert outcome.attempts == 0

    trace_path = tmp_path / "runs" / "run_repair_non_retryable_001" / "trace.jsonl"
    lines = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert [row["event"] for row in lines] == ["repair.started", "repair.finished"]
    assert lines[1]["status"] == "non_retryable"
    assert lines[1]["retry_count"] == 0
    assert lines[1]["payload"]["attempts_used"] == 0
    assert lines[1]["payload"]["max_attempts"] == 2
    assert lines[1]["payload"]["retry_budget_remaining"] == 2
