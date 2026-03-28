from core.action_lock import ActionLockManager


def test_action_lock_queues_conflicts_and_auto_handoffs():
    manager = ActionLockManager()

    first = manager.request_lock("job_a", "first", policy_scope="deliverable:doc", conflict_key="doc", owner="orchestrator")
    assert first["acquired"] is True
    assert manager.is_locked is True
    assert manager.current_task_id == "job_a"

    second = manager.request_lock("job_b", "second", policy_scope="deliverable:doc", conflict_key="doc", owner="orchestrator")
    assert second["acquired"] is False
    assert second["queued"] is True
    assert second["conflict"] is True
    assert manager.snapshot()["queue_depth"] == 1
    assert manager.last_conflict["active_task_id"] == "job_a"

    manager.unlock(reason="completed")

    assert manager.is_locked is True
    assert manager.current_task_id == "job_b"
    assert manager.snapshot()["queue_depth"] == 0


def test_action_lock_refreshes_same_task_without_conflict():
    manager = ActionLockManager()

    first = manager.request_lock("job_a", "first", policy_scope="deliverable:web", conflict_key="web", owner="orchestrator")
    second = manager.request_lock("job_a", "refresh", policy_scope="deliverable:web", conflict_key="web", owner="orchestrator")

    assert first["acquired"] is True
    assert second["acquired"] is True
    assert second["conflict"] is False
    assert manager.status_message == "refresh"
