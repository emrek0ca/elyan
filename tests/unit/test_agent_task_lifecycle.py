"""Tests for core/multi_agent/agent_task.py and task_tracker.py."""
from __future__ import annotations

import asyncio
import time

import pytest

from core.multi_agent.agent_task import AgentTask, TaskStatus


# ── AgentTask state machine ─────────────────────────────────────────────────


def test_task_initial_state():
    t = AgentTask(objective="build feature")
    assert t.status == TaskStatus.PENDING
    assert t.duration_s is None
    assert not t.is_overdue
    assert t.task_id.startswith("task_")


def test_task_start_transition():
    t = AgentTask()
    t.start()
    assert t.status == TaskStatus.RUNNING
    assert t.started_at is not None


def test_task_complete_transition():
    t = AgentTask()
    t.start()
    t.complete({"output": "done"})
    assert t.status == TaskStatus.COMPLETED
    assert t.result == {"output": "done"}
    assert t.completed_at is not None
    assert t.duration_s is not None
    assert t.duration_s >= 0


def test_task_fail_transition():
    t = AgentTask()
    t.start()
    t.fail("connection timeout")
    assert t.status == TaskStatus.FAILED
    assert t.error == "connection timeout"


def test_task_cancel_from_pending():
    t = AgentTask()
    t.cancel()
    assert t.status == TaskStatus.CANCELLED


def test_task_cancel_from_running():
    t = AgentTask()
    t.start()
    t.cancel()
    assert t.status == TaskStatus.CANCELLED


def test_task_retry():
    t = AgentTask(max_retries=3)
    t.start()
    t.fail("error1")
    t.retry()
    assert t.status == TaskStatus.RUNNING
    assert t.retry_count == 1


def test_task_max_retries_exceeded():
    t = AgentTask(max_retries=1)
    t.start()
    t.fail("e1")
    t.retry()  # retry_count = 1, max = 1
    t.fail("e2")
    with pytest.raises(ValueError, match="Max retries"):
        t.retry()


def test_invalid_transition_raises():
    t = AgentTask()
    t.start()
    t.complete()
    with pytest.raises(ValueError, match="Invalid transition"):
        t.start()  # COMPLETED → RUNNING is invalid


def test_task_is_overdue():
    t = AgentTask(deadline_s=0.001)
    t.start()
    time.sleep(0.01)
    assert t.is_overdue is True


def test_task_not_overdue_when_completed():
    t = AgentTask(deadline_s=0.001)
    t.start()
    time.sleep(0.01)
    t.complete()
    assert t.is_overdue is False


# ── Serialization ────────────────────────────────────────────────────────────


def test_task_roundtrip():
    t = AgentTask(
        objective="test",
        assigned_to="builder",
        constraints=["no-cloud"],
        priority=80,
    )
    t.start()
    d = t.to_dict()
    assert d["status"] == "running"
    assert d["duration_s"] is not None

    restored = AgentTask.from_dict(d)
    assert restored.objective == "test"
    assert restored.status == TaskStatus.RUNNING
    assert restored.priority == 80


# ── TaskTracker ──────────────────────────────────────────────────────────────


@pytest.fixture
def tracker(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "core.multi_agent.message_bus.resolve_elyan_data_dir",
        lambda: tmp_path,
    )
    from core.multi_agent.task_tracker import AgentTaskTracker
    return AgentTaskTracker()


@pytest.mark.asyncio
async def test_tracker_register_and_get(tracker):
    task = AgentTask(objective="hello", assigned_to="lead")
    await tracker.register(task)
    assert tracker.get(task.task_id) is task


@pytest.mark.asyncio
async def test_tracker_lifecycle(tracker):
    task = AgentTask(objective="build", assigned_to="builder")
    await tracker.register(task)
    await tracker.start(task.task_id)
    assert tracker.get(task.task_id).status == TaskStatus.RUNNING

    await tracker.complete(task.task_id, {"code": "ok"})
    assert tracker.get(task.task_id).status == TaskStatus.COMPLETED


@pytest.mark.asyncio
async def test_tracker_cancel_cascades(tracker):
    parent = AgentTask(task_id="p1", objective="parent")
    child = AgentTask(task_id="c1", parent_task_id="p1", objective="child")
    grandchild = AgentTask(task_id="gc1", parent_task_id="c1", objective="grandchild")

    await tracker.register(parent)
    await tracker.register(child)
    await tracker.register(grandchild)

    await tracker.start(parent.task_id)
    await tracker.start(child.task_id)
    await tracker.start(grandchild.task_id)

    await tracker.cancel(parent.task_id)

    assert tracker.get("p1").status == TaskStatus.CANCELLED
    assert tracker.get("c1").status == TaskStatus.CANCELLED
    assert tracker.get("gc1").status == TaskStatus.CANCELLED


@pytest.mark.asyncio
async def test_tracker_list_active(tracker):
    t1 = AgentTask(task_id="a", objective="a", priority=10)
    t2 = AgentTask(task_id="b", objective="b", priority=90)
    await tracker.register(t1)
    await tracker.register(t2)

    active = tracker.list_active()
    assert len(active) == 2
    assert active[0].task_id == "b"  # Higher priority first


@pytest.mark.asyncio
async def test_tracker_task_tree(tracker):
    root = AgentTask(task_id="r", objective="root")
    c1 = AgentTask(task_id="c1", parent_task_id="r", objective="child1")
    c2 = AgentTask(task_id="c2", parent_task_id="r", objective="child2")

    await tracker.register(root)
    await tracker.register(c1)
    await tracker.register(c2)

    tree = tracker.task_tree("r")
    assert tree["task"]["task_id"] == "r"
    assert len(tree["children"]) == 2


@pytest.mark.asyncio
async def test_tracker_metrics(tracker):
    t1 = AgentTask(task_id="m1", objective="a")
    t2 = AgentTask(task_id="m2", objective="b")
    await tracker.register(t1)
    await tracker.register(t2)
    await tracker.start("m1")
    await tracker.complete("m1")
    await tracker.start("m2")
    await tracker.fail("m2", "err")

    m = tracker.metrics()
    assert m["total"] == 2
    assert m["success_rate"] == 0.5
    assert m["by_status"]["completed"] == 1
    assert m["by_status"]["failed"] == 1


@pytest.mark.asyncio
async def test_tracker_prune(tracker):
    t = AgentTask(task_id="old", objective="old")
    await tracker.register(t)
    await tracker.start("old")
    await tracker.complete("old")
    # Artificially age it
    tracker.get("old").completed_at = time.time() - 7200

    removed = await tracker.prune_completed(max_age_s=3600)
    assert removed == 1
    assert tracker.get("old") is None
