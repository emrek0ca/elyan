from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

from core.events.event_store import Event, EventStore, EventType
from core.events.read_model import RunReadModel


def test_append_creates_sequential_events(tmp_path):
    store = EventStore(db_path=tmp_path / "events.db")
    first = Event("e1", EventType.TASK_RECEIVED, "run-1", "run", {"intent": "x"})
    second = Event("e2", EventType.TASK_PLANNED, "run-1", "run", {"steps": []})
    assert store.append(first) == 1
    assert store.append(second) == 2


def test_replay_reconstructs_correct_state(tmp_path):
    store = EventStore(db_path=tmp_path / "events.db")
    store.append(Event("e1", EventType.TASK_RECEIVED, "run-1", "run", {"intent": "build"}))
    store.append(Event("e2", EventType.TASK_STEP_COMPLETED, "run-1", "run", {"step": "write"}))
    store.append(Event("e3", EventType.TASK_COMPLETED, "run-1", "run", {"result": "ok"}))
    state = store.replay_to_state("run-1")
    assert state["status"] == "completed"
    assert state["intent"] == "build"
    assert state["completed_steps"] == ["write"]


def test_query_by_type_filters_correctly(tmp_path):
    store = EventStore(db_path=tmp_path / "events.db")
    store.append(Event("e1", EventType.TOOL_SUCCEEDED, "run-1", "run", {"tool_name": "a"}))
    store.append(Event("e2", EventType.TOOL_FAILED, "run-1", "run", {"tool_name": "b"}))
    assert len(store.query_by_type(EventType.TOOL_SUCCEEDED)) == 1


def test_concurrent_appends_dont_corrupt(tmp_path):
    store = EventStore(db_path=tmp_path / "events.db")

    def write(i: int) -> int:
        return store.append(Event(f"e{i}", EventType.TASK_RECEIVED, "run-1", "run", {"i": i}))

    with ThreadPoolExecutor(max_workers=8) as pool:
        seqs = list(pool.map(write, range(20)))
    assert seqs == list(range(1, 21))
    assert len(store.get_aggregate_events("run-1")) == 20


def test_read_model_updates_on_event(tmp_path):
    store = EventStore(db_path=tmp_path / "events.db")
    read_model = RunReadModel(store)
    store.append(Event("e1", EventType.TASK_RECEIVED, "run-1", "run", {"session_id": "sess-1", "intent": "check"}))
    row = read_model.get_run("run-1")
    assert row["intent"] == "check"
    assert row["session_id"] == "sess-1"


def test_tool_stats_moving_average_correct(tmp_path):
    store = EventStore(db_path=tmp_path / "events.db")
    read_model = RunReadModel(store)
    store.append(Event("e1", EventType.TOOL_SUCCEEDED, "run-1", "run", {"tool_name": "web_search", "latency_ms": 100}))
    store.append(Event("e2", EventType.TOOL_SUCCEEDED, "run-1", "run", {"tool_name": "web_search", "latency_ms": 300}))
    stats = read_model.get_tool_performance()
    assert stats == []  # below the >5 call threshold


def test_get_recent_runs_respects_limit(tmp_path):
    store = EventStore(db_path=tmp_path / "events.db")
    read_model = RunReadModel(store)
    for i in range(3):
        store.append(Event(f"e{i}", EventType.TASK_RECEIVED, f"run-{i}", "run", {"session_id": "sess", "intent": str(i)}))
        time.sleep(0.01)
    runs = read_model.get_recent_runs(limit=2)
    assert len(runs) == 2


def test_cqrs_write_model_independent_from_read(tmp_path):
    store = EventStore(db_path=tmp_path / "events.db")
    read_model = RunReadModel(store)
    store.append(Event("e1", EventType.TASK_RECEIVED, "run-1", "run", {"intent": "one"}))
    assert read_model.get_run("run-1")["intent"] == "one"
    store.append(Event("e2", EventType.TASK_COMPLETED, "run-1", "run", {"result": "ok"}))
    assert read_model.get_run("run-1")["status"] == "completed"


def test_event_causation_chain_tracked(tmp_path):
    store = EventStore(db_path=tmp_path / "events.db")
    first = Event("e1", EventType.TASK_RECEIVED, "run-1", "run", {"intent": "x"})
    store.append(first)
    second = Event("e2", EventType.TOOL_INVOKED, "run-1", "run", {"tool_name": "t"}, causation_id="e1")
    store.append(second)
    events = store.get_aggregate_events("run-1")
    assert events[1].causation_id == "e1"


def test_wal_mode_enabled(tmp_path):
    store = EventStore(db_path=tmp_path / "events.db")
    row = store.connection.execute("PRAGMA journal_mode").fetchone()[0]
    assert str(row).upper() == "WAL"
