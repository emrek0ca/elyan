from __future__ import annotations

import pytest
from sqlalchemy import select

from core.persistence import RuntimeSyncWorker, get_runtime_database, reset_runtime_database
from core.persistence.runtime_db import (
    connector_accounts_table,
    connector_action_traces_table,
    sync_receipts_table,
)


@pytest.fixture(autouse=True)
def isolated_sync_databases(monkeypatch, tmp_path):
    monkeypatch.setenv("ELYAN_DATA_DIR", str(tmp_path / "elyan"))
    monkeypatch.setenv("ELYAN_RUNTIME_DB_PATH", str(tmp_path / "elyan" / "db" / "runtime.sqlite3"))
    monkeypatch.setenv("ELYAN_WORKSPACE_DATABASE_URL", f"sqlite:///{tmp_path / 'workspace.sqlite3'}")
    reset_runtime_database()
    yield
    reset_runtime_database()


@pytest.mark.asyncio
async def test_runtime_sync_worker_delivers_connector_outbox_to_workspace_db():
    runtime_db = get_runtime_database()
    runtime_db.connectors.upsert_account(
        {
            "workspace_id": "workspace-alpha",
            "provider": "google",
            "connector_name": "gmail",
            "account_alias": "work",
            "display_name": "Work",
            "email": "work@example.com",
            "status": "ready",
            "auth_strategy": "oauth",
            "granted_scopes": ["email.read"],
            "metadata": {"workspace_id": "workspace-alpha"},
        }
    )
    runtime_db.connectors.record_trace(
        {
            "workspace_id": "workspace-alpha",
            "provider": "google",
            "connector_name": "gmail",
            "integration_type": "email",
            "account_alias": "work",
            "operation": "connector",
            "status": "success",
            "success": True,
            "latency_ms": 14.2,
            "metadata": {"workspace_id": "workspace-alpha"},
        }
    )

    assert len(runtime_db.outbox.list_pending(limit=20)) >= 2

    worker = RuntimeSyncWorker(interval_seconds=0.05, batch_size=20)
    await worker.start()
    await worker.run_once()
    await worker.stop()

    assert runtime_db.outbox.list_pending(limit=20) == []

    assert runtime_db.workspace_sync.engine is not None
    with runtime_db.workspace_sync.engine.begin() as conn:
        account = conn.execute(
            select(connector_accounts_table).where(connector_accounts_table.c.account_id == "google::work")
        ).mappings().first()
        trace = conn.execute(select(connector_action_traces_table)).mappings().first()
        receipts = conn.execute(select(sync_receipts_table)).mappings().all()

    assert account is not None
    assert account["workspace_id"] == "workspace-alpha"
    assert trace is not None
    assert trace["connector_name"] == "gmail"
    assert len(receipts) >= 2
