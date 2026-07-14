from __future__ import annotations

import threading
from pathlib import Path

import pytest

from runtime import state_store
from runtime.execution_scheduler import parallel_read_batch, schedule_steps, schedule_tasks
from runtime.executor_core import ExecutorCore


def _isolate_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(state_store, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(state_store, "STATE_PATH", tmp_path / "elyan_state.json")
    monkeypatch.setattr(state_store, "LEGACY_STATE_PATH", tmp_path / "legacy.json")


def _metadata(capability: str) -> dict[str, object]:
    return {"sideEffect": capability.startswith("write")}


def _ready(capability: str) -> dict[str, object]:
    return {"ready": capability != "blocked_read"}


def test_scheduler_order_is_dependency_safe_and_deterministic() -> None:
    steps = [
        {"id": "blocked", "capability": "blocked_read", "priority": "urgent"},
        {"id": "old", "capability": "read_old", "priority": "normal", "queuedAt": "2026-01-01T00:00:00Z"},
        {"id": "due_later", "capability": "read_due", "priority": "high", "deadlineAt": "2026-08-01T00:00:00Z"},
        {"id": "due_first", "capability": "read_due", "priority": "high", "deadlineAt": "2026-07-20T00:00:00Z"},
        {"id": "base", "capability": "read_base", "priority": "low"},
        {"id": "dependent", "capability": "read_dependent", "priority": "urgent", "dependsOn": ["base"]},
    ]

    ordered = schedule_steps(steps, metadata_provider=_metadata, readiness_provider=_ready)

    assert [step["id"] for step in ordered] == [
        "due_first",
        "due_later",
        "old",
        "base",
        "dependent",
        "blocked",
    ]


def test_parallel_batch_contains_only_ready_independent_reads() -> None:
    ordered = schedule_steps(
        [
            {"id": "r1", "capability": "read_a", "resourceScope": ["same"]},
            {"id": "r2", "capability": "read_b", "resourceScope": ["same"]},
            {"id": "w1", "capability": "write_file", "accessMode": "read", "resourceScope": ["same"]},
            {"id": "r3", "capability": "read_c"},
        ],
        metadata_provider=_metadata,
        readiness_provider=_ready,
    )

    batch = parallel_read_batch(ordered, 0, completed_step_ids=set())

    assert [step["id"] for step in batch] == ["r1", "r2"]
    assert ordered[2]["_scheduler"]["accessMode"] == "write"


def test_backend_tasks_use_goal_priority_deadline_dependency_and_wait_time() -> None:
    tasks = [
        {"id": "blocked", "priority": "urgent", "readiness": {"ready": False}},
        {"id": "old", "priority": "normal", "createdAt": "2026-01-01T00:00:00Z"},
        {"id": "base", "priority": "low"},
        {"id": "dependent", "priority": "urgent", "dependsOn": ["base"]},
        {
            "id": "goal_priority",
            "payload": {
                "desktopWorkOrder": {
                    "planPreview": {
                        "goalContract": {"priority": "high"},
                    }
                }
            },
            "deadlineAt": "2026-07-20T00:00:00Z",
        },
    ]

    ordered = schedule_tasks(
        tasks,
        readiness_provider=lambda task: task.get("readiness", {}).get("ready") is not False,
    )

    assert [task["id"] for task in ordered] == [
        "goal_priority",
        "old",
        "base",
        "dependent",
        "blocked",
    ]


def test_unknown_task_dependency_is_deferred_without_explicit_completion() -> None:
    ordered = schedule_tasks([
        {"id": "ready", "priority": "normal"},
        {"id": "dependent", "priority": "urgent", "dependsOn": ["not_fetched"]},
    ])

    assert [task["id"] for task in ordered] == ["ready", "dependent"]
    assert ordered[1]["_schedulerBlockedReason"] == "unknown_dependency"


def test_executor_runs_independent_reads_with_bounded_parallelism(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    executor = ExecutorCore()
    lock = threading.Lock()
    release = threading.Event()
    active = 0
    max_active = 0

    def execute_step(capability, _args, _state, _source):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
            if active >= 2:
                release.set()
        assert release.wait(timeout=1.0)
        with lock:
            active -= 1
        return {"ok": True, "output": capability, "result": {"kind": capability}, "artifacts": []}, []

    ok, content, _events, error_code, _result, _artifacts = executor.execute_plan_steps(
        steps=[
            {"id": "r1", "capability": "file_read", "args": {"path": "a"}},
            {"id": "r2", "capability": "git_status", "args": {}},
        ],
        state_factory=lambda: {},
        execute_step=execute_step,
        source="confirmed_plan",
    )

    assert ok is True
    assert error_code == ""
    assert max_active == 2
    assert content == "file_read\ngit_status"


def test_executor_preempts_only_after_completed_step_checkpoint(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    executor = ExecutorCore()
    calls: list[str] = []

    def execute_step(capability, _args, _state, _source):
        calls.append(capability)
        executor.request_preemption("exec_preempt", reason="urgent_task_ready")
        return {"ok": True, "output": capability, "result": {"kind": capability}, "artifacts": []}, []

    # P3 ön koşulu girdi dosyasının gerçekten var olmasını ister.
    file_a = tmp_path / "a.txt"
    file_b = tmp_path / "b.txt"
    file_a.write_text("a", encoding="utf-8")
    file_b.write_text("b", encoding="utf-8")

    ok, _content, _events, error_code, _result, _artifacts = executor.execute_plan_steps(
        steps=[
            {"id": "first", "capability": "file_read", "args": {"path": str(file_a)}},
            {"id": "second", "capability": "file_read", "args": {"path": str(file_b)}, "dependsOn": ["first"]},
        ],
        state_factory=lambda: {},
        execute_step=execute_step,
        source="confirmed_plan",
        execution_id="exec_preempt",
    )

    assert ok is False
    assert error_code == "EXECUTION_PREEMPTED"
    assert calls == ["file_read"]
    trace = state_store.snapshot()["runtime"]["executor"]["lastExecutionTrace"]
    assert trace["stopReason"] == "preempted_at_checkpoint"
    assert [checkpoint["stepId"] for checkpoint in trace["checkpoints"]] == ["first"]


def test_executor_never_runs_unready_step(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _isolate_state(monkeypatch, tmp_path)
    executor = ExecutorCore()
    calls: list[str] = []

    ok, _content, _events, error_code, _result, _artifacts = executor.execute_plan_steps(
        steps=[{"id": "blocked", "capability": "file_read", "args": {"path": "a"}}],
        state_factory=lambda: {
            "runtime": {
                "capabilityStates": {
                    "file_read": {"ready": False, "available": False, "errorCode": "DEPENDENCY_UNAVAILABLE"}
                }
            }
        },
        execute_step=lambda capability, *_args: calls.append(capability),
        source="confirmed_plan",
    )

    assert ok is False
    assert error_code == "CAPABILITY_NOT_READY"
    assert calls == []


def test_parallel_grants_capture_step_specific_trust_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    executor = ExecutorCore()
    current_step = {"id": ""}
    observed: list[tuple[str, str]] = []

    def authorize(step_id, _capability, _args, _source, _task_id):
        current_step["id"] = step_id
        return {"grantId": f"grant_{step_id}"}

    def state_factory():
        return {"runtime": {"executionTrust": {"stepId": current_step["id"]}}}

    def execute_step(capability, args, state, _source):
        observed.append((args["_capabilityGrant"]["grantId"], state["runtime"]["executionTrust"]["stepId"]))
        return {"ok": True, "output": capability, "result": {"kind": capability}, "artifacts": []}, []

    ok, *_rest = executor.execute_plan_steps(
        steps=[
            {"id": "r1", "capability": "file_read", "args": {"path": "a"}},
            {"id": "r2", "capability": "git_status", "args": {}},
        ],
        state_factory=state_factory,
        execute_step=execute_step,
        authorize_step=authorize,
        source="runtime_task",
    )

    assert ok is True
    assert sorted(observed) == [("grant_r1", "r1"), ("grant_r2", "r2")]


def test_parallel_batch_is_one_preemption_checkpoint_group(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    executor = ExecutorCore()
    calls: list[str] = []

    def execute_step(capability, _args, _state, _source):
        calls.append(capability)
        executor.request_preemption("exec_parallel_preempt")
        return {"ok": True, "output": capability, "result": {"kind": capability}, "artifacts": []}, []

    ok, _content, _events, error_code, _result, _artifacts = executor.execute_plan_steps(
        steps=[
            {"id": "r1", "capability": "file_read", "args": {"path": "a"}},
            {"id": "r2", "capability": "git_status", "args": {}},
            {"id": "after", "capability": "file_read", "args": {"path": "b"}, "dependsOn": ["r1", "r2"]},
        ],
        state_factory=lambda: {},
        execute_step=execute_step,
        source="confirmed_plan",
        execution_id="exec_parallel_preempt",
    )

    assert ok is False
    assert error_code == "EXECUTION_PREEMPTED"
    assert sorted(calls) == ["file_read", "git_status"]
    trace = state_store.snapshot()["runtime"]["executor"]["lastExecutionTrace"]
    assert [item["stepId"] for item in trace["checkpoints"]] == ["r1", "r2"]
