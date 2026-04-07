from __future__ import annotations

import time

from core.events.event_store import Event, EventStore, EventType
from core.observability.dora_metrics import MetricsCollector


def test_completion_rate_calculated_from_events(tmp_path):
    store = EventStore(db_path=tmp_path / "events.db")
    collector = MetricsCollector(store)
    store.append(Event("e1", EventType.TASK_RECEIVED, "run-1", "run", {"intent": "a"}))
    store.append(Event("e2", EventType.TASK_COMPLETED, "run-1", "run", {"result": "ok"}))
    snap = collector.compute_snapshot()
    assert snap.task_completion_rate == 1.0


def test_lead_time_computed_correctly(tmp_path):
    store = EventStore(db_path=tmp_path / "events.db")
    collector = MetricsCollector(store)
    start = time.time()
    store.append(Event("e1", EventType.TASK_RECEIVED, "run-1", "run", {"intent": "a"}, timestamp=start))
    store.append(Event("e2", EventType.TASK_COMPLETED, "run-1", "run", {"result": "ok"}, timestamp=start + 2))
    snap = collector.compute_snapshot()
    assert 1900 <= snap.avg_time_to_first_result_ms <= 2100


def test_performance_level_elite_threshold(tmp_path):
    store = EventStore(db_path=tmp_path / "events.db")
    collector = MetricsCollector(store)
    for i in range(10):
        store.append(Event(f"r{i}", EventType.TASK_RECEIVED, f"run-{i}", "run", {"intent": "a"}))
        store.append(Event(f"c{i}", EventType.TASK_COMPLETED, f"run-{i}", "run", {"result": "ok"}))
    snap = collector.compute_snapshot()
    assert snap.performance_level() in {"High", "Elite"}


def test_improvement_suggestion_for_high_approval(tmp_path):
    store = EventStore(db_path=tmp_path / "events.db")
    collector = MetricsCollector(store)
    store.append(Event("e1", EventType.TASK_RECEIVED, "run-1", "run", {"intent": "a"}))
    store.append(Event("e2", EventType.APPROVAL_REQUESTED, "run-1", "run", {"action": "x"}))
    snap = collector.compute_snapshot()
    assert any("UncertaintyEngine" in item for item in snap.improvement_suggestions())


def test_snapshot_with_zero_tasks(tmp_path):
    store = EventStore(db_path=tmp_path / "events.db")
    collector = MetricsCollector(store)
    snap = collector.compute_snapshot()
    assert snap.task_completion_rate == 0.0


def test_period_filtering_works(tmp_path):
    store = EventStore(db_path=tmp_path / "events.db")
    collector = MetricsCollector(store)
    old = time.time() - 10 * 3600
    store.append(Event("e1", EventType.TASK_RECEIVED, "run-1", "run", {"intent": "a"}, timestamp=old))
    store.append(Event("e2", EventType.TASK_COMPLETED, "run-1", "run", {"result": "ok"}, timestamp=old))
    snap = collector.compute_snapshot(period_hours=1)
    assert snap.task_completion_rate == 0.0
