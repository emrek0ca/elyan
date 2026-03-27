from __future__ import annotations

from pathlib import Path

import pytest

from core.persistence import get_runtime_database, reset_runtime_database
import core.run_store as run_store_module
import core.workflow.vertical_runner as vertical_runner_module
from core.workflow.vertical_runner import VerticalWorkflowRunner


@pytest.fixture(autouse=True)
def isolated_runs_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("ELYAN_RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.setenv("ELYAN_RUNTIME_DB_PATH", str(tmp_path / "runtime" / "runtime.sqlite3"))
    run_store_module._run_store = None
    reset_runtime_database()
    yield
    run_store_module._run_store = None
    reset_runtime_database()


class _FakeOutbox:
    def __init__(self):
        self._pending: list[dict[str, object]] = []
        self.delivered: list[str] = []

    def enqueue(
        self,
        _conn=None,
        *,
        workspace_id="local-workspace",
        aggregate_type="unknown",
        aggregate_id="",
        event_type="unknown",
        payload=None,
    ):
        event_id = f"evt_{len(self._pending) + 1}"
        self._pending.append(
            {
                "event_id": event_id,
                "workspace_id": workspace_id,
                "aggregate_type": aggregate_type,
                "aggregate_id": aggregate_id,
                "event_type": event_type,
                "payload": dict(payload or {}),
                "sync_state": "pending",
            }
        )
        return event_id

    def list_pending(self, limit=100):
        _ = limit
        return [dict(item) for item in self._pending if str(item.get("sync_state") or "") == "pending"]

    def mark_delivered(self, event_id: str):
        self.delivered.append(event_id)
        for item in self._pending:
            if str(item.get("event_id") or "") == event_id:
                item["sync_state"] = "delivered"
                break


class _FakeWorkspaceSync:
    def __init__(self):
        self.enabled = True
        self.received: list[dict[str, object]] = []

    def accept_outbox_event(self, payload):
        self.received.append(dict(payload or {}))
        return True


class _FakeExecutionRepo:
    def __init__(self, outbox: _FakeOutbox):
        self.outbox = outbox
        self.calls: list[tuple[str, dict[str, object]]] = []

    def _record(self, method_name: str, payload):
        data = dict(payload or {})
        self.calls.append((method_name, data))
        self.outbox.enqueue(
            workspace_id=str(data.get("workspace_id") or "local-workspace"),
            aggregate_type="task_run",
            aggregate_id=str(data.get("run_id") or data.get("workflow_id") or "run"),
            event_type=f"workflow.{method_name}",
            payload=data,
        )

    def persist_plan(self, **payload):
        self._record("persist_plan", payload)

    def start_execution_step(self, **payload):
        self._record("start_execution_step", payload)
        return f"exec_{len(self.calls)}"

    def complete_execution_step(self, **payload):
        self._record("complete_execution_step", payload)

    def record_verification(self, **payload):
        self._record("record_verification", payload)

    def record_recovery(self, **payload):
        self._record("record_recovery", payload)

    def record_checkpoint(self, **payload):
        self._record("record_checkpoint", payload)


class _FakeRunIndexRepo:
    def __init__(self):
        self.upserts: list[dict[str, object]] = []
        self.status_updates: list[dict[str, object]] = []

    def upsert_run(self, payload):
        self.upserts.append(dict(payload or {}))

    def mark_status(self, run_id, *, status, completed_at=None):
        self.status_updates.append(
            {"run_id": run_id, "status": status, "completed_at": completed_at}
        )


class _FakeRuntimeDb:
    def __init__(self):
        self.outbox = _FakeOutbox()
        self.workspace_sync = _FakeWorkspaceSync()
        self.execution = _FakeExecutionRepo(self.outbox)
        self.run_index = _FakeRunIndexRepo()


@pytest.fixture
def fake_runtime_db(monkeypatch):
    runtime_db = _FakeRuntimeDb()
    monkeypatch.setattr(vertical_runner_module, "get_runtime_database", lambda: runtime_db)
    monkeypatch.setattr(run_store_module, "get_runtime_database", lambda: runtime_db)
    run_store_module._run_store = None
    yield runtime_db
    run_store_module._run_store = None


@pytest.mark.asyncio
async def test_document_flow_creates_export_ready_artifacts(tmp_path):
    runner = VerticalWorkflowRunner()
    record = await runner.start_workflow(
        task_type="document",
        title="Elyan Document Flow",
        brief="Create a concise technical brief for Elyan runtime architecture.",
        output_dir=str(tmp_path / "artifacts"),
        background=False,
    )

    assert record.status == "completed"
    assert record.task_type == "document"
    assert record.artifact_path
    assert Path(record.artifact_path).exists()
    assert record.review_report
    assert record.review_report["status"] == "passed"
    assert any(Path(item["path"]).suffix.lower() in {".docx", ".pdf", ".md"} for item in record.artifacts)


@pytest.mark.asyncio
async def test_presentation_flow_creates_pptx(tmp_path):
    runner = VerticalWorkflowRunner()
    record = await runner.start_workflow(
        task_type="presentation",
        title="Elyan Deck",
        brief="Prepare an executive product presentation about Elyan as an AI operating system.",
        output_dir=str(tmp_path / "artifacts"),
        background=False,
    )

    assert record.status == "completed"
    assert record.task_type == "presentation"
    assert record.review_report
    assert record.review_report["status"] == "passed"
    assert any(Path(item["path"]).suffix.lower() == ".pptx" for item in record.artifacts)


@pytest.mark.asyncio
async def test_website_flow_creates_react_scaffold(tmp_path):
    runner = VerticalWorkflowRunner()
    record = await runner.start_workflow(
        task_type="website",
        title="Elyan Site",
        brief="Build a premium React landing scaffold for Elyan with calm command center positioning.",
        output_dir=str(tmp_path / "artifacts"),
        background=False,
    )

    assert record.status == "completed"
    assert record.task_type == "website"
    assert record.artifact_path
    root = Path(record.artifact_path)
    assert root.exists()
    assert (root / "package.json").exists()
    assert (root / "README.md").exists()
    assert record.review_report
    assert record.review_report["status"] == "passed"


@pytest.mark.asyncio
async def test_document_flow_respects_requested_output_profile(tmp_path):
    runner = VerticalWorkflowRunner()
    record = await runner.start_workflow(
        task_type="document",
        title="Elyan PDF Brief",
        brief="Create a concise architecture brief as a PDF-only artifact.",
        audience="developer",
        language="en",
        preferred_formats=["pdf"],
        output_dir=str(tmp_path / "artifacts"),
        background=False,
    )

    assert record.status == "completed"
    assert any(Path(item["path"]).suffix.lower() == ".pdf" for item in record.artifacts)
    assert not any(Path(item["path"]).suffix.lower() == ".docx" for item in record.artifacts)
    scope_step = next(step for step in record.steps if step["name"] == "scope_workflow")
    assert scope_step["result"]["audience"] == "developer"
    assert scope_step["result"]["language"] == "en"
    assert scope_step["result"]["preferred_formats"] == ["pdf"]


@pytest.mark.asyncio
async def test_workflow_persists_template_routing_and_review_contract(tmp_path):
    runner = VerticalWorkflowRunner()
    record = await runner.start_workflow(
        task_type="website",
        title="Elyan Launch Site",
        brief="Build a premium website scaffold for Elyan with clear information architecture.",
        project_template_id="web-launch",
        project_name="Web Launch",
        routing_profile="quality_first",
        review_strictness="strict",
        output_dir=str(tmp_path / "artifacts"),
        background=False,
    )

    assert record.status == "completed"
    classify_step = next(step for step in record.steps if step["name"] == "classify_request")
    scope_step = next(step for step in record.steps if step["name"] == "scope_workflow")
    review_step = next(step for step in record.steps if step["name"] == "review_artifact_output")

    assert classify_step["result"]["routing_profile"] == "quality_first"
    assert classify_step["result"]["review_strictness"] == "strict"
    assert classify_step["result"]["candidate_chain"]
    assert scope_step["result"]["project_template_id"] == "web-launch"
    assert scope_step["result"]["project_name"] == "Web Launch"
    assert review_step["result"]["strictness"] == "strict"


@pytest.mark.asyncio
async def test_vertical_runner_writes_execution_persistence_and_drains_outbox(tmp_path, fake_runtime_db):
    runner = VerticalWorkflowRunner()
    record = await runner.start_workflow(
        task_type="document",
        title="DB-backed brief",
        brief="Create a concise technical brief for Elyan runtime persistence.",
        output_dir=str(tmp_path / "artifacts"),
        background=False,
    )

    assert record.status == "completed"
    calls = fake_runtime_db.execution.calls
    method_names = [name for name, _ in calls]

    assert "persist_plan" in method_names
    assert "start_execution_step" in method_names
    assert "complete_execution_step" in method_names
    assert "record_verification" in method_names
    assert "record_checkpoint" in method_names
    assert fake_runtime_db.workspace_sync.received
    assert fake_runtime_db.outbox.delivered

    verification = next(payload for name, payload in calls if name == "record_verification")
    checkpoint = next(
        payload
        for name, payload in calls
        if name == "record_checkpoint" and payload["step_id"] == "review_artifact_output"
    )
    plan = next(payload for name, payload in calls if name == "persist_plan")

    assert verification["status"] == "passed"
    assert checkpoint["step_id"] == "review_artifact_output"
    assert checkpoint["workflow_state"] == "reviewing"
    assert plan["steps"]
    assert any(step["planned_step_id"].startswith(f"plan_{record.run_id}_") for step in plan["steps"])
    assert any(event["event_type"] == "workflow.record_verification" for event in fake_runtime_db.workspace_sync.received)
    assert any(event["event_type"] == "workflow.record_checkpoint" for event in fake_runtime_db.workspace_sync.received)


@pytest.mark.asyncio
async def test_vertical_runner_records_recovery_and_failure_checkpoint(tmp_path, fake_runtime_db, monkeypatch):
    runner = VerticalWorkflowRunner()

    async def _failing_review(**_kwargs):
        return {"status": "failed", "recommended_action": "revise"}

    monkeypatch.setattr(runner, "_review_execution_result", _failing_review)

    record = await runner.start_workflow(
        task_type="presentation",
        title="Recovery deck",
        brief="Prepare a short presentation that should fail review.",
        output_dir=str(tmp_path / "artifacts"),
        background=False,
    )

    assert record.status == "failed"
    recovery = next(payload for name, payload in fake_runtime_db.execution.calls if name == "record_recovery")
    checkpoint = next(
        payload
        for name, payload in fake_runtime_db.execution.calls
        if name == "record_checkpoint" and payload["workflow_state"] == "reviewing"
    )
    verification = next(payload for name, payload in fake_runtime_db.execution.calls if name == "record_verification")

    assert recovery["decision"] == "revise"
    assert checkpoint["step_id"] == "review_artifact_output"
    assert checkpoint["summary"]["status"] == "failed"
    assert verification["status"] == "failed"


@pytest.mark.asyncio
async def test_vertical_runner_persists_execution_rows_to_runtime_db(tmp_path):
    runner = VerticalWorkflowRunner()
    record = await runner.start_workflow(
        task_type="document",
        title="Persistent brief",
        brief="Create a concise technical brief for Elyan runtime persistence.",
        output_dir=str(tmp_path / "artifacts"),
        background=False,
    )

    execution_repo = get_runtime_database().execution
    steps = execution_repo.list_execution_steps(record.run_id)
    verifications = execution_repo.list_verifications(record.run_id)
    checkpoints = execution_repo.list_checkpoints(record.run_id)

    assert record.status == "completed"
    assert any(step["tool_name"] == "execute_artifact_flow" and step["status"] == "completed" for step in steps)
    assert any(step["tool_name"] == "review_artifact_output" for step in steps)
    assert any(item["method"] == "artifact_review" and item["status"] == "passed" for item in verifications)
    assert any(item["step_id"] == "review_artifact_output" for item in checkpoints)
