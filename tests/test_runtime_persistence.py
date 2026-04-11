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
from core.persistence.runtime_db import (
    conversation_messages_table,
    conversation_sessions_table,
    local_user_sessions_table,
    outbox_events_table,
    permission_grants_table,
)
from core.runtime.session_store import RuntimeSessionAPI
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


def test_workspace_access_invites_roles_and_seats():
    runtime_db = get_runtime_database()
    owner = runtime_db.auth.bootstrap_owner(
        email="owner@example.com",
        password="secret123",
        display_name="Owner",
        workspace_id="workspace-alpha",
    )
    runtime_db.billing.upsert_workspace(
        {
            "workspace_id": "workspace-alpha",
            "plan_id": "team",
            "status": "active",
            "billing_customer": "ws_alpha",
            "seats": 2,
            "metadata": {"workspace_owned": True},
            "updated_at": 10.0,
        }
    )

    listed = runtime_db.access.list_workspaces(actor_id=owner["user_id"])
    assert listed[0]["membership"]["role"] == "owner"
    assert runtime_db.access.has_active_seat(workspace_id="workspace-alpha", actor_id=owner["user_id"]) is True

    member = runtime_db.auth.upsert_user(
        email="member@example.com",
        password="secret123",
        display_name="Member",
        workspace_id="workspace-alpha",
        metadata={"workspace_role": "member"},
    )
    invite = runtime_db.access.create_invite(
        workspace_id="workspace-alpha",
        email="member@example.com",
        role="operator",
        invited_by=owner["user_id"],
    )
    accepted = runtime_db.access.accept_invite(
        invite_id=invite["invite_id"],
        actor_id=member["user_id"],
        email="member@example.com",
    )

    assert accepted is not None
    assert accepted["membership"]["role"] == "operator"

    assignment = runtime_db.access.assign_seat(
        workspace_id="workspace-alpha",
        actor_id=member["user_id"],
        assigned_by=owner["user_id"],
    )
    assert assignment["actor_id"] == member["user_id"]

    members = runtime_db.access.list_memberships("workspace-alpha", include_users=True)
    invited_member = next(item for item in members if item["actor_id"] == member["user_id"])
    assert invited_member["seat_assigned"] is True
    assert invited_member["user"]["email"] == "member@example.com"

    role_update = runtime_db.access.update_membership_role(
        workspace_id="workspace-alpha",
        actor_id=member["user_id"],
        role="viewer",
        updated_by=owner["user_id"],
    )
    assert role_update["role"] == "viewer"
    assert runtime_db.access.seat_summary("workspace-alpha")["seats_used"] == 2


def test_workspace_access_rejects_last_owner_demotion_and_email_mismatch():
    runtime_db = get_runtime_database()
    owner = runtime_db.auth.bootstrap_owner(
        email="owner@example.com",
        password="secret123",
        display_name="Owner",
        workspace_id="workspace-alpha",
    )
    invite = runtime_db.access.create_invite(
        workspace_id="workspace-alpha",
        email="member@example.com",
        role="operator",
        invited_by=owner["user_id"],
    )

    with pytest.raises(PermissionError, match="invite_email_mismatch"):
        runtime_db.access.accept_invite(
            invite_id=invite["invite_id"],
            actor_id="user_member",
            email="wrong@example.com",
        )

    with pytest.raises(RuntimeError, match="workspace_requires_owner"):
        runtime_db.access.update_membership_role(
            workspace_id="workspace-alpha",
            actor_id=owner["user_id"],
            role="viewer",
            updated_by=owner["user_id"],
        )


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


def test_privacy_repository_summary_export_and_delete():
    runtime_db = get_runtime_database()
    runtime_db.privacy.set_workspace_policy(
        workspace_id="workspace-alpha",
        allow_global_aggregation=False,
        metadata={"source": "test"},
    )
    runtime_db.privacy.record_privacy_decision(
        workspace_id="workspace-alpha",
        user_id="user-privacy",
        source_kind="interaction",
        text="iletisimim user@example.com",
        payload={"request": "user@example.com"},
        classification="personal",
    )
    runtime_db.privacy.record_dataset_entry(
        workspace_id="workspace-alpha",
        user_id="user-privacy",
        source_kind="feedback",
        source_id="event-1",
        text="model fallback latency",
        payload={"latency_ms": 220.0},
        classification="operational",
    )

    summary = runtime_db.privacy.summary(workspace_id="workspace-alpha", user_id="user-privacy", limit=5)
    bundle = runtime_db.privacy.export_bundle(workspace_id="workspace-alpha", user_id="user-privacy", limit=5)
    deleted = runtime_db.privacy.delete_user_data("user-privacy", workspace_id="workspace-alpha")

    assert summary["workspace_id"] == "workspace-alpha"
    assert summary["total_entries"] == 2
    assert summary["classification_counts"]["personal"] == 1
    assert summary["classification_counts"]["operational"] == 1
    assert "personal data" in summary["what_is_excluded"]
    assert bundle["privacy_decisions"]
    assert bundle["dataset_entries"]
    assert deleted["deleted"]["dataset_entries"] == 1
    assert runtime_db.privacy.summary(workspace_id="workspace-alpha", user_id="user-privacy", limit=5)["total_entries"] == 0


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


def test_runtime_session_api_persists_conversation_turns_with_workspace_scope():
    runtime_db = get_runtime_database()
    user = runtime_db.auth.upsert_user(
        email="conversation@example.com",
        password="TopSecret123",
        display_name="Conversation User",
    )
    session, _session_token = runtime_db.auth_sessions.create_session(
        user=user,
        metadata={"client": "desktop"},
    )
    session_api = RuntimeSessionAPI(runtime_db)

    conversation = session_api.append_turn(
        user_id=str(user["user_id"]),
        user_input="Merhaba Elyan",
        response_text="Merhaba, nasil yardimci olayim?",
        action="chat",
        success=True,
        runtime_metadata={
            "workspace_id": str(user["workspace_id"]),
            "session_id": str(session["session_id"]),
            "channel": "desktop",
            "device_id": "macbook-pro",
        },
    )
    history = session_api.get_recent_conversations(
        user_id=str(user["user_id"]),
        limit=5,
        runtime_metadata={
            "workspace_id": str(user["workspace_id"]),
            "session_id": str(session["session_id"]),
            "channel": "desktop",
            "device_id": "macbook-pro",
        },
    )

    assert conversation["workspace_id"] == user["workspace_id"]
    assert conversation["actor_id"] == user["user_id"]
    assert conversation["message_count"] == 2
    assert history
    assert history[0]["user_message"] == "Merhaba Elyan"
    assert history[0]["bot_response"] == "Merhaba, nasil yardimci olayim?"
    assert history[0]["workspace_id"] == user["workspace_id"]

    with runtime_db.local_engine.begin() as conn:
        conversation_row = conn.execute(
            select(conversation_sessions_table).where(
                conversation_sessions_table.c.conversation_session_id == conversation["conversation_session_id"]
            )
        ).mappings().first()
        message_rows = conn.execute(
            select(conversation_messages_table)
            .where(conversation_messages_table.c.conversation_session_id == conversation["conversation_session_id"])
            .order_by(conversation_messages_table.c.message_index.asc())
        ).mappings().all()

    assert conversation_row is not None
    assert conversation_row["workspace_id"] == user["workspace_id"]
    assert conversation_row["auth_session_id"] == session["session_id"]
    assert len(message_rows) == 2
    assert [str(row["role"]) for row in message_rows] == ["user", "assistant"]


def test_runtime_session_api_recall_searches_across_conversation_sessions():
    runtime_db = get_runtime_database()
    user = runtime_db.auth.upsert_user(
        email="recall@example.com",
        password="TopSecret123",
        display_name="Recall User",
    )
    desktop_session, _ = runtime_db.auth_sessions.create_session(
        user=user,
        metadata={"client": "desktop"},
    )
    telegram_session, _ = runtime_db.auth_sessions.create_session(
        user=user,
        metadata={"client": "telegram"},
    )
    session_api = RuntimeSessionAPI(runtime_db)

    session_api.append_turn(
        user_id=str(user["user_id"]),
        user_input="Iyzico webhook imzasini nasil dogruluyorduk?",
        response_text="Webhook imzasini hmac.compare_digest ile sabit zamanli karsilastiriyoruz.",
        action="chat",
        success=True,
        runtime_metadata={
            "workspace_id": str(user["workspace_id"]),
            "session_id": str(desktop_session["session_id"]),
            "channel": "desktop",
            "device_id": "macbook-pro",
        },
    )
    session_api.append_turn(
        user_id=str(user["user_id"]),
        user_input="Dun konustugumuz iyzico checkout hatasini hatirlat.",
        response_text="Telegram akisinda checkout linkini sabitlemistik.",
        action="chat",
        success=True,
        runtime_metadata={
            "workspace_id": str(user["workspace_id"]),
            "session_id": str(telegram_session["session_id"]),
            "channel": "telegram",
            "device_id": "iphone",
        },
    )
    session_api.append_turn(
        user_id=str(user["user_id"]),
        user_input="Bugun hava nasil?",
        response_text="Bugun gunesli gorunuyor.",
        action="chat",
        success=True,
        runtime_metadata={
            "workspace_id": str(user["workspace_id"]),
            "session_id": str(telegram_session["session_id"]),
            "channel": "telegram",
            "device_id": "iphone",
        },
    )

    results = session_api.search_history(
        user_id=str(user["user_id"]),
        query="iyzico",
        limit=5,
        runtime_metadata={"workspace_id": str(user["workspace_id"])},
    )

    assert len(results) == 2
    assert {item["channel"] for item in results} == {"desktop", "telegram"}
    assert all(item["workspace_id"] == str(user["workspace_id"]) for item in results)
    assert any("hmac.compare_digest" in item["bot_response"] for item in results)
    assert any("checkout linkini sabitlemistik" in item["bot_response"] for item in results)


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
