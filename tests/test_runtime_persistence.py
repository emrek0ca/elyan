from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

import pytest
from sqlalchemy import select

import core.billing.workspace_billing as workspace_billing_module
import core.cowork_threads as cowork_threads_module
import core.run_store as run_store_module
import core.security.approval_engine as approval_engine_module
from core.billing.workspace_billing import get_workspace_billing_store
from core.cowork_threads import get_cowork_thread_store
from core.learning.policy_learner import ResponsePolicyLearner
from core.persistence import get_runtime_database, reset_runtime_database
from core.persistence.runtime_db import local_user_sessions_table, outbox_events_table, permission_grants_table
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


def test_permission_grants_issue_revoke_and_expire():
    runtime_db = get_runtime_database()
    issued = runtime_db.permission_grants.issue_grant(
        workspace_id="workspace-alpha",
        device_id="macbook-pro",
        scope="filesystem.read",
        resource="/Users/emrekoca/Desktop/bot",
        allowed_actions=["list", "read_text"],
        ttl_seconds=1,
        issued_by="desktop_operator",
    )

    active = runtime_db.permission_grants.list_active(workspace_id="workspace-alpha")
    assert len(active) == 1
    assert active[0]["resource"] == "/Users/emrekoca/Desktop/bot"

    assert runtime_db.permission_grants.revoke_grant(issued["grant_id"], revoked_by="desktop_operator")
    assert runtime_db.permission_grants.list_active(workspace_id="workspace-alpha") == []

    expired = runtime_db.permission_grants.issue_grant(
        workspace_id="workspace-alpha",
        device_id="macbook-pro",
        scope="filesystem.read",
        resource="/tmp/ephemeral",
        allowed_actions=["list"],
        ttl_seconds=60,
        issued_by="desktop_operator",
    )
    with runtime_db.local_engine.begin() as conn:
        conn.execute(
            permission_grants_table.update()
            .where(permission_grants_table.c.grant_id == expired["grant_id"])
            .values(expires_at=0.1)
        )
    assert runtime_db.permission_grants.expire_stale() == 1
    assert runtime_db.permission_grants.list_active(workspace_id="workspace-alpha") == []


def test_local_auth_sessions_are_hashed_and_workspace_scoped():
    runtime_db = get_runtime_database()
    user = runtime_db.auth.upsert_user(
        email="multiuser@example.com",
        password="TopSecret123",
        display_name="Multi User",
    )

    assert user["workspace_id"].startswith("ws_")

    session, session_token = runtime_db.auth_sessions.create_session(
        user=user,
        metadata={"client": "desktop_test"},
    )
    resolved = runtime_db.auth_sessions.resolve_session(session_token)

    assert resolved is not None
    assert resolved["user_id"] == user["user_id"]
    assert resolved["workspace_id"] == user["workspace_id"]
    assert resolved["email"] == "multiuser@example.com"

    with runtime_db.local_engine.begin() as conn:
        row = conn.execute(
            select(local_user_sessions_table).where(local_user_sessions_table.c.session_id == session["session_id"])
        ).mappings().first()

    assert row is not None
    assert str(row["session_token_hash"]) != session_token


def test_outbox_retry_transitions_to_dead_letter():
    runtime_db = get_runtime_database()
    with runtime_db.local_engine.begin() as conn:
        event_id = runtime_db.outbox.enqueue(
            conn,
            workspace_id="workspace-alpha",
            aggregate_type="cowork_thread",
            aggregate_id="thread_123",
            event_type="cowork.thread.updated",
            payload={"thread_id": "thread_123"},
        )

    for _ in range(5):
        runtime_db.outbox.mark_retry(event_id, error="sync failed")

    with runtime_db.local_engine.begin() as conn:
        row = conn.execute(
            select(outbox_events_table).where(outbox_events_table.c.event_id == event_id)
        ).mappings().first()

    assert row is not None
    assert row["sync_state"] == "dead_letter"
    assert int(row["delivery_attempts"] or 0) >= 5


def test_learning_repository_and_policy_learner_persist_to_runtime_db():
    runtime_db = get_runtime_database()
    profile = runtime_db.learning.upsert_user_preference_profile(
        workspace_id="workspace-alpha",
        user_id="user-1",
        explanation_style="technical",
        approval_sensitivity_hint="strict",
        preferred_route="quality_first",
        preferred_model="gpt-4o",
        task_templates=["website_scaffold"],
        metadata={"source": "test"},
    )

    feedback = runtime_db.learning.record_operational_feedback(
        workspace_id="workspace-alpha",
        user_id="user-1",
        category="tool",
        entity_id="github.commit",
        outcome="success",
        reward=0.8,
        latency_ms=120.0,
        recovery_count=0,
        payload={"thread_id": "thread_123"},
    )

    learner = ResponsePolicyLearner(workspace_id="workspace-alpha", user_id="user-1")
    learner.policy_weights["concise_answer"] = [0.25] * 64
    learner._persist()
    reloaded = ResponsePolicyLearner(workspace_id="workspace-alpha", user_id="user-1")

    assert profile["preferred_route"] == "quality_first"
    assert feedback["category"] == "tool"
    reliability = runtime_db.learning.get_global_tool_reliability(tool_name="tool:github.commit")
    assert reliability is not None
    assert reliability["success_count"] == 1
    loaded_profile = runtime_db.learning.get_user_preference_profile(workspace_id="workspace-alpha", user_id="user-1")
    assert loaded_profile is not None
    assert loaded_profile["metadata"]["response_policy_weights"]["concise_answer"][0] == pytest.approx(0.25)
    assert reloaded.snapshot()["policy_weights"]["concise_answer"][0] == pytest.approx(0.25)
