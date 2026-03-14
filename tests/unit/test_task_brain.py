from __future__ import annotations

import json
from pathlib import Path

from core.evidence.run_store import RunStore
from core.task_brain import TaskBrain


def test_task_brain_creates_stateful_task():
    brain = TaskBrain(storage_path=Path("/tmp/test_task_brain_creates_stateful_task.json"))
    task = brain.create_task(
        objective="Fourier hakkında araştırma yap",
        user_input="Fourier hakkında araştırma yap",
        channel="telegram",
        user_id="u1",
        attachments=["/tmp/a.png"],
    )
    assert task.task_id.startswith("task_")
    assert task.state == "pending"
    assert task.history
    assert task.context["attachments"] == ["/tmp/a.png"]


def test_task_brain_transitions_and_registers_artifacts():
    brain = TaskBrain(storage_path=Path("/tmp/test_task_brain_transitions_and_registers_artifacts.json"))
    task = brain.create_task(
        objective="ekrana bak",
        user_input="ekrana bak",
        channel="cli",
        user_id="u2",
    )
    task.transition("planning", note="planner_started")
    task.register_artifacts([{"path": "/tmp/shot.png", "type": "image"}])
    task.transition("completed", note="done")
    payload = task.to_dict()
    assert payload["state"] == "completed"
    assert payload["artifacts"][0]["path"] == "/tmp/shot.png"
    states = [item["state"] for item in payload["history"]]
    assert states == ["pending", "planning", "completed"]


def test_run_store_writes_task_state(tmp_path, monkeypatch):
    monkeypatch.setattr("core.evidence.run_store.resolve_runs_root", lambda: tmp_path / "runs")
    store = RunStore("run_task_state_001")
    task_state = {
        "task_id": "task_001",
        "objective": "araştırma yap",
        "state": "executing",
        "history": [{"state": "pending", "ts": 1.0}],
    }
    out = store.write_task(
        {"contract_id": "research_report_v1"},
        user_input="araştırma yap",
        metadata={"channel": "cli"},
        task_state=task_state,
    )
    payload = json.loads(Path(out).read_text(encoding="utf-8"))
    assert payload["task_state"]["task_id"] == "task_001"
    assert payload["task_state"]["state"] == "executing"


def test_run_store_emits_lifecycle_events(tmp_path, monkeypatch):
    monkeypatch.setattr("core.evidence.run_store.resolve_runs_root", lambda: tmp_path / "runs")
    store = RunStore("run_task_events_001")
    store.write_evidence(manifest_path="/tmp/manifest.json", steps=[{"id": "s1"}], artifacts=[{"path": "/tmp/a.txt"}], metadata={"status": "success"})
    store.write_summary(status="success", response_text="ok", artifacts=[{"path": "/tmp/a.txt"}])

    trace_path = tmp_path / "runs" / "run_task_events_001" / "trace.jsonl"
    lines = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    events = [row["event"] for row in lines]
    assert events == ["run.started", "verify.finished", "deliver.finished", "run.completed"]


def test_run_store_summary_includes_research_quality_metrics(tmp_path, monkeypatch):
    monkeypatch.setattr("core.evidence.run_store.resolve_runs_root", lambda: tmp_path / "runs")
    store = RunStore("run_research_metrics_001")
    summary_path = store.write_summary(
        status="partial",
        response_text="araştırma tamamlandı",
        artifacts=[],
        metadata={
            "claim_coverage": 1.0,
            "critical_claim_coverage": 0.5,
            "uncertainty_count": 2,
            "conflict_count": 1,
            "manual_review_claim_count": 3,
            "claim_map_path": "/tmp/claim_map.json",
            "revision_summary_path": "/tmp/revision_summary.md",
            "team_quality_avg": 0.82,
            "team_research_claim_coverage": 1.0,
            "team_research_critical_claim_coverage": 0.5,
            "team_research_uncertainty_count": 2,
        },
    )
    summary = Path(summary_path).read_text(encoding="utf-8")
    assert "- Claim coverage: 1.00" in summary
    assert "- Critical claim coverage: 0.50" in summary
    assert "- Uncertainty count: 2" in summary
    assert "- Conflict count: 1" in summary
    assert "- Manual review claims: 3" in summary
    assert "- Claim map: /tmp/claim_map.json" in summary
    assert "- Revision summary: /tmp/revision_summary.md" in summary
    assert "- Team quality avg: 0.82" in summary
    assert "- Team research claim coverage: 1.00" in summary
    assert "- Team research critical coverage: 0.50" in summary
    assert "- Team research uncertainty count: 2" in summary


def test_run_store_emits_capability_selected_event(tmp_path, monkeypatch):
    monkeypatch.setattr("core.evidence.run_store.resolve_runs_root", lambda: tmp_path / "runs")
    store = RunStore("run_capability_selected_001")
    store.write_task(
        {"contract_id": "research_report_v1"},
        user_input="araştırma yap",
        metadata={
            "capability_domain": "research",
            "workflow_id": "research.default",
            "job_type": "report",
            "action": "research",
            "phase": "selected",
        },
        task_state={"task_id": "task_001", "state": "planning"},
    )

    trace_path = tmp_path / "runs" / "run_capability_selected_001" / "trace.jsonl"
    lines = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    selected = [row for row in lines if row["event"] == "capability.selected"]
    assert len(selected) == 1
    assert selected[0]["selected_capability"] == "research"
    assert selected[0]["workflow_path"] == ["research.default"]
    assert selected[0]["payload"]["job_type"] == "report"


def test_run_store_emits_plan_created_event(tmp_path, monkeypatch):
    monkeypatch.setattr("core.evidence.run_store.resolve_runs_root", lambda: tmp_path / "runs")
    store = RunStore("run_plan_created_001")
    store.write_task(
        {"contract_id": "screen_operator_v1"},
        user_input="ekrandaki butona tıkla",
        metadata={
            "capability_domain": "screen_operator",
            "workflow_id": "screen.loop",
            "job_type": "ui_task",
            "action": "click",
        },
        task_state={
            "task_id": "task_002",
            "state": "planning",
            "subtasks": [{"id": "observe"}, {"id": "click"}, {"id": "verify"}],
        },
    )

    trace_path = tmp_path / "runs" / "run_plan_created_001" / "trace.jsonl"
    lines = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    created = [row for row in lines if row["event"] == "plan.created"]
    assert len(created) == 1
    assert created[0]["selected_capability"] == "screen_operator"
    assert created[0]["workflow_path"] == ["screen.loop"]
    assert created[0]["payload"]["step_count"] == 3


def test_task_brain_persists_and_lists_for_user(tmp_path, monkeypatch):
    monkeypatch.setattr("core.task_brain.ELYAN_DIR", tmp_path)
    from core.task_brain import TaskBrain

    brain = TaskBrain(storage_path=tmp_path / "task_brain.json")
    task = brain.create_task(
        objective="kod yaz",
        user_input="kod yaz",
        channel="telegram",
        user_id="u-list",
    )
    task.transition("completed", note="done")
    brain.save_task(task)

    reloaded = TaskBrain(storage_path=tmp_path / "task_brain.json")
    items = reloaded.list_for_user("u-list")
    assert len(items) == 1
    assert items[0].task_id == task.task_id
    assert items[0].state == "completed"


def test_task_brain_list_all_and_get(tmp_path, monkeypatch):
    monkeypatch.setattr("core.task_brain.ELYAN_DIR", tmp_path)
    from core.task_brain import TaskBrain

    brain = TaskBrain(storage_path=tmp_path / "task_brain.json")
    first = brain.create_task(
        objective="ilk gorev",
        user_input="ilk gorev",
        channel="cli",
        user_id="u-admin",
    )
    second = brain.create_task(
        objective="ikinci gorev",
        user_input="ikinci gorev",
        channel="telegram",
        user_id="u-admin",
    )
    first.transition("completed", note="done")
    brain.save_task(first)

    assert brain.get(second.task_id) is not None
    items = brain.list_all()
    assert len(items) == 2
    assert {item.task_id for item in items} == {first.task_id, second.task_id}
    completed = brain.list_all(states=["completed"])
    assert [item.task_id for item in completed] == [first.task_id]
