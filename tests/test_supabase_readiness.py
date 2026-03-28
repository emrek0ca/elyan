import asyncio

from sqlalchemy import select

from core.persistence.runtime_db import (
    get_runtime_database,
    reset_runtime_database,
    sync_receipts_table,
    workspace_operational_feedback_table,
    workspace_tool_reliability_table,
    workspace_user_preference_profiles_table,
)
from core.persistence.sync_worker import sync_runtime_outbox_once
from core.persistence.workspace_config import resolve_workspace_auth_backend, resolve_workspace_database_mode, resolve_workspace_database_url


def test_workspace_database_env_prefers_supabase(monkeypatch):
    monkeypatch.delenv("ELYAN_WORKSPACE_DATABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_DB_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("ELYAN_SUPABASE_DATABASE_URL", "postgresql://postgres:secret@db.example.supabase.co:5432/postgres")

    assert resolve_workspace_database_url() == "postgresql://postgres:secret@db.example.supabase.co:5432/postgres"
    assert resolve_workspace_database_mode() == "supabase"


def test_workspace_auth_backend_persists_isolated_users_and_sessions(monkeypatch, tmp_path):
    monkeypatch.setenv("ELYAN_RUNTIME_DB_PATH", str(tmp_path / "runtime.sqlite3"))
    monkeypatch.setenv("ELYAN_WORKSPACE_DATABASE_URL", f"sqlite:///{tmp_path / 'workspace.sqlite3'}")
    monkeypatch.setenv("ELYAN_AUTH_BACKEND", "workspace")
    reset_runtime_database()

    runtime_db = get_runtime_database()
    assert resolve_workspace_auth_backend() == "workspace"

    user = runtime_db.auth.upsert_user(
        email="osmanemrekoca@gmail.com",
        password="Emre1187",
        display_name="Emre",
    )
    assert user["workspace_id"].startswith("ws_")

    policy = runtime_db.workspace_data_policies.get_policy(workspace_id=user["workspace_id"])
    assert policy is not None
    assert policy["allow_non_personal_learning"] is True
    assert policy["allow_personal_data_learning"] is False

    authenticated = runtime_db.auth.authenticate_user(
        email="osmanemrekoca@gmail.com",
        password="Emre1187",
        workspace_id=user["workspace_id"],
    )
    assert authenticated is not None
    assert authenticated["workspace_id"] == user["workspace_id"]

    session, session_token = runtime_db.auth_sessions.create_session(user=authenticated, metadata={"client": "desktop"})
    resolved = runtime_db.auth_sessions.resolve_session(session_token)

    assert resolved is not None
    assert resolved["workspace_id"] == user["workspace_id"]
    assert resolved["user_id"] == authenticated["user_id"]
    assert runtime_db.auth_sessions.revoke_session(session_token) is True

    reset_runtime_database()


def test_workspace_learning_sync_populates_supabase_ready_tables(monkeypatch, tmp_path):
    monkeypatch.setenv("ELYAN_RUNTIME_DB_PATH", str(tmp_path / "runtime.sqlite3"))
    monkeypatch.setenv("ELYAN_WORKSPACE_DATABASE_URL", f"sqlite:///{tmp_path / 'workspace.sqlite3'}")
    monkeypatch.setenv("ELYAN_AUTH_BACKEND", "workspace")
    reset_runtime_database()

    runtime_db = get_runtime_database()
    user = runtime_db.auth.upsert_user(
        email="osmanemrekoca@gmail.com",
        password="Emre1187",
        display_name="Emre",
    )

    runtime_db.learning.upsert_user_preference_profile(
        workspace_id=user["workspace_id"],
        user_id=user["user_id"],
        explanation_style="concise",
        approval_sensitivity_hint="strict",
        preferred_route="balanced",
        preferred_model="gpt-5.4",
        task_templates=["developer-workstation"],
    )
    runtime_db.learning.record_operational_feedback(
        workspace_id=user["workspace_id"],
        user_id=user["user_id"],
        category="tool",
        entity_id="github.commit",
        outcome="success",
        reward=1.0,
        latency_ms=240.0,
        recovery_count=0,
        payload={"non_personal": True},
    )

    delivered = asyncio.run(sync_runtime_outbox_once(runtime_db=runtime_db, limit=50))
    assert delivered >= 3

    with runtime_db.workspace_sync.engine.begin() as conn:
        profile_row = conn.execute(select(workspace_user_preference_profiles_table)).mappings().first()
        feedback_row = conn.execute(select(workspace_operational_feedback_table)).mappings().first()
        reliability_row = conn.execute(select(workspace_tool_reliability_table)).mappings().first()
        receipt_count = conn.execute(select(sync_receipts_table)).mappings().all()

    assert profile_row is not None
    assert feedback_row is not None
    assert reliability_row is not None
    assert reliability_row["tool_name"] == "tool:github.commit"
    assert len(receipt_count) >= 3

    reset_runtime_database()
