from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

import pytest

import core.billing.workspace_billing as workspace_billing_module
import core.cowork_threads as cowork_threads_module
import core.run_store as run_store_module
import core.security.approval_engine as approval_engine_module
from core.billing.workspace_billing import get_workspace_billing_store
from core.cowork_threads import get_cowork_thread_store
from core.persistence import get_runtime_database, reset_runtime_database
from core.run_store import RunRecord, RunStore
from core.security.approval_engine import ApprovalEngine
from core.protocol.shared_types import RiskLevel


@pytest.fixture(autouse=True)
def isolated_runtime_db(monkeypatch, tmp_path):
    monkeypatch.setenv("ELYAN_DATA_DIR", str(tmp_path / "elyan"))
    monkeypatch.setenv("ELYAN_RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.setenv("ELYAN_RUNTIME_DB_PATH", str(tmp_path / "elyan" / "db" / "runtime.sqlite3"))
    cowork_threads_module._thread_store = None
    workspace_billing_module._workspace_billing_store = None
    run_store_module._run_store = None
    approval_engine_module._approval_engine = None
    reset_runtime_database()
    yield
    cowork_threads_module._thread_store = None
    workspace_billing_module._workspace_billing_store = None
    run_store_module._run_store = None
    approval_engine_module._approval_engine = None
    reset_runtime_database()


@pytest.mark.asyncio
async def test_cowork_threads_backfill_legacy_json_into_runtime_db(tmp_path):
    legacy_path = tmp_path / "elyan" / "cowork" / "threads.json"
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_path.write_text(
        json.dumps(
            {
                "thread_legacy": {
                    "thread_id": "thread_legacy",
                    "workspace_id": "workspace-alpha",
                    "session_id": "desktop",
                    "title": "Legacy thread",
                    "current_mode": "cowork",
                    "status": "queued",
                    "created_at": 100.0,
                    "updated_at": 101.0,
                    "turns": [
                        {
                            "turn_id": "turn_legacy",
                            "role": "user",
                            "content": "Review the roadmap.",
                            "created_at": 100.0,
                            "mode": "cowork",
                            "status": "completed",
                            "metadata": {},
                        }
                    ],
                    "metadata": {"source": "legacy"},
                }
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    detail = await get_cowork_thread_store().get_thread_detail("thread_legacy")

    assert detail["thread_id"] == "thread_legacy"
    assert detail["workspace_id"] == "workspace-alpha"
    assert detail["turns"][0]["content"] == "Review the roadmap."

    stored = get_runtime_database().threads.load_all_threads()
    assert "thread_legacy" in stored
    assert stored["thread_legacy"]["metadata"]["source"] == "legacy"


def test_workspace_billing_backfill_legacy_json_into_runtime_db(tmp_path):
    legacy_path = tmp_path / "elyan" / "billing" / "workspaces.json"
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_path.write_text(
        json.dumps(
            {
                "workspace-team": {
                    "workspace_id": "workspace-team",
                    "plan_id": "team",
                    "status": "active",
                    "billing_customer": "ws_customer",
                    "metadata": {"workspace_owned": True},
                    "usage": [
                        {"usage_id": "usage_1", "workspace_id": "workspace-team", "metric": "connectors", "amount": 2, "created_at": 10.0, "metadata": {}}
                    ],
                }
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    store = get_workspace_billing_store()
    summary = store.get_workspace_summary("workspace-team")

    assert summary["plan"]["id"] == "team"
    assert summary["usage"]["totals"]["connectors"] == 2

    stored = get_runtime_database().billing.load_workspace_records()
    assert stored["workspace-team"]["billing_customer"] == "ws_customer"


@pytest.mark.asyncio
async def test_approval_requests_persist_to_runtime_db(monkeypatch):
    monkeypatch.setenv("ELYAN_APPROVAL_PERSIST", "force")

    class _Uncertainty:
        @staticmethod
        def should_ask_approval(_action: str) -> bool:
            return True

    engine = ApprovalEngine()
    task = None
    with patch("core.reasoning.uncertainty_engine.get_uncertainty_engine", return_value=_Uncertainty()):
        task = asyncio.create_task(
            engine.request_approval(
                session_id="sess_approval",
                run_id="run_approval",
                action_type="execute_shell",
                payload={"cmd": "rm -rf /tmp/demo", "workspace_id": "workspace-alpha"},
                risk_level=RiskLevel.DESTRUCTIVE,
                reason="Need confirmation",
            )
        )
        await asyncio.sleep(0.05)
        pending = get_runtime_database().approvals.list_pending()
        assert len(pending) == 1
        assert pending[0]["payload"]["cmd"] == "rm -rf /tmp/demo"
        assert pending[0]["workspace_id"] == "workspace-alpha"
        engine.resolve_approval(pending[0]["request_id"], True, "resolver")
        assert await asyncio.wait_for(task, timeout=1.0) is True

    assert get_runtime_database().approvals.list_pending() == []


@pytest.mark.asyncio
async def test_run_store_mirrors_run_index_and_checkpoints(tmp_path):
    store = RunStore(store_path=tmp_path / "runs")
    record = RunRecord(
        run_id="run_db_index",
        session_id="desktop-main",
        status="completed",
        intent="Create runtime db checkpoint",
        workflow_state="completed",
        task_type="document",
        steps=[
            {
                "step_id": "step_1",
                "name": "scope_workflow",
                "status": "completed",
                "started_at": 10.0,
                "completed_at": 12.0,
                "result": {"audience": "developer"},
                "rollback_available": False,
            }
        ],
        artifacts=[
            {
                "artifact_id": "artifact_1",
                "label": "brief.pdf",
                "path": str(tmp_path / "artifacts" / "brief.pdf"),
                "kind": "document",
                "created_at": 20.0,
            }
        ],
        review_report={"status": "passed"},
        metadata={"workspace_id": "workspace-alpha", "thread_id": "thread_123"},
    )

    await store.record_run(record)

    indexed = get_runtime_database().run_index.get_run_index("run_db_index")
    assert indexed is not None
    assert indexed["workspace_id"] == "workspace-alpha"
    assert indexed["artifacts"][0]["label"] == "brief.pdf"
    assert indexed["replay_checkpoints"][0]["step_id"] == "step_1"

