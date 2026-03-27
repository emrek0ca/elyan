from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import (
    Boolean,
    Column,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    event,
    func,
    select,
)
from sqlalchemy.engine import Connection, Engine

from core.observability.logger import get_structured_logger
from core.security.encrypted_vault import get_encrypted_vault
from core.storage_paths import resolve_runtime_db_path

slog = get_structured_logger("runtime_db")


def _now() -> float:
    return time.time()


def _json_dumps(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, default=str)


def _json_loads(value: Any, default: Any) -> Any:
    if value in (None, ""):
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        data = json.loads(str(value))
    except Exception:
        return default
    return data if isinstance(data, type(default)) else default


class EncryptedFieldCodec:
    def __init__(self) -> None:
        self._vault = get_encrypted_vault()

    def dumps(self, value: Any, *, context: str, classification: str = "sensitive") -> str:
        if value in (None, "", [], {}):
            return ""
        return _json_dumps(
            {
                "__elyan_encrypted__": True,
                "classification": str(classification or "sensitive"),
                "envelope": self._vault.encrypt(value, context=context),
            }
        )

    def loads(self, value: str, *, context: str, default: Any) -> Any:
        if not value:
            return default
        payload = _json_loads(value, {})
        if not isinstance(payload, dict):
            return default
        if payload.get("__elyan_encrypted__") is True and isinstance(payload.get("envelope"), dict):
            try:
                return self._vault.decrypt(dict(payload.get("envelope") or {}), context=context)
            except Exception as exc:
                slog.log_event(
                    "runtime_db_decrypt_error",
                    {"context": context, "error": str(exc)},
                    level="warning",
                )
                return default
        return payload.get("value", default)


LOCAL_METADATA = MetaData()
WORKSPACE_METADATA = MetaData()

schema_migrations = Table(
    "schema_migrations",
    LOCAL_METADATA,
    Column("name", String(64), primary_key=True),
    Column("applied_at", Float, nullable=False, default=_now),
)

cowork_threads_table = Table(
    "cowork_threads",
    LOCAL_METADATA,
    Column("thread_id", String(64), primary_key=True),
    Column("workspace_id", String(128), nullable=False),
    Column("session_id", String(128), nullable=False),
    Column("title", String(256), nullable=False),
    Column("current_mode", String(32), nullable=False, default="cowork"),
    Column("status", String(64), nullable=False, default="queued"),
    Column("active_run_id", String(128), nullable=False, default=""),
    Column("active_mission_id", String(128), nullable=False, default=""),
    Column("metadata_json", Text, nullable=False, default="{}"),
    Column("created_at", Float, nullable=False, default=_now),
    Column("updated_at", Float, nullable=False, default=_now),
    Column("version", Integer, nullable=False, default=1),
)
Index("ix_cowork_threads_workspace_updated", cowork_threads_table.c.workspace_id, cowork_threads_table.c.updated_at)

cowork_turns_table = Table(
    "cowork_turns",
    LOCAL_METADATA,
    Column("turn_id", String(64), primary_key=True),
    Column("thread_id", String(64), ForeignKey("cowork_threads.thread_id", ondelete="CASCADE"), nullable=False),
    Column("role", String(32), nullable=False),
    Column("content", Text, nullable=False, default=""),
    Column("created_at", Float, nullable=False, default=_now),
    Column("mode", String(32), nullable=False, default="cowork"),
    Column("status", String(64), nullable=False, default="completed"),
    Column("mission_id", String(128), nullable=False, default=""),
    Column("run_id", String(128), nullable=False, default=""),
    Column("metadata_json", Text, nullable=False, default="{}"),
)
Index("ix_cowork_turns_thread_created", cowork_turns_table.c.thread_id, cowork_turns_table.c.created_at)

approvals_table = Table(
    "approvals",
    LOCAL_METADATA,
    Column("request_id", String(64), primary_key=True),
    Column("workspace_id", String(128), nullable=False, default="local-workspace"),
    Column("session_id", String(128), nullable=False),
    Column("run_id", String(128), nullable=False, default=""),
    Column("action_type", String(128), nullable=False),
    Column("payload_encrypted", Text, nullable=False, default=""),
    Column("risk_level", String(64), nullable=False),
    Column("reason", Text, nullable=False, default=""),
    Column("status", String(64), nullable=False, default="pending"),
    Column("resolver_id", String(128), nullable=False, default=""),
    Column("resolution_note", Text, nullable=False, default=""),
    Column("created_at", Float, nullable=False, default=_now),
    Column("resolved_at", Float, nullable=False, default=0.0),
    Column("updated_at", Float, nullable=False, default=_now),
)
Index("ix_approvals_status_created", approvals_table.c.status, approvals_table.c.created_at)

billing_workspaces_table = Table(
    "billing_workspaces",
    LOCAL_METADATA,
    Column("workspace_id", String(128), primary_key=True),
    Column("plan_id", String(64), nullable=False, default="free"),
    Column("status", String(64), nullable=False, default="inactive"),
    Column("billing_customer", String(128), nullable=False, default=""),
    Column("stripe_customer_id", String(128), nullable=False, default=""),
    Column("stripe_subscription_id", String(128), nullable=False, default=""),
    Column("current_period_end", Float, nullable=False, default=0.0),
    Column("seats", Integer, nullable=False, default=1),
    Column("checkout_url", Text, nullable=False, default=""),
    Column("portal_url", Text, nullable=False, default=""),
    Column("metadata_json", Text, nullable=False, default="{}"),
    Column("updated_at", Float, nullable=False, default=_now),
)
Index("ix_billing_workspaces_updated", billing_workspaces_table.c.updated_at)

usage_ledger_table = Table(
    "usage_ledger",
    LOCAL_METADATA,
    Column("usage_id", String(96), primary_key=True),
    Column("workspace_id", String(128), ForeignKey("billing_workspaces.workspace_id", ondelete="CASCADE"), nullable=False),
    Column("metric", String(64), nullable=False),
    Column("amount", Integer, nullable=False, default=0),
    Column("metadata_json", Text, nullable=False, default="{}"),
    Column("created_at", Float, nullable=False, default=_now),
)
Index("ix_usage_ledger_workspace_created", usage_ledger_table.c.workspace_id, usage_ledger_table.c.created_at)

task_runs_table = Table(
    "task_runs",
    LOCAL_METADATA,
    Column("run_id", String(128), primary_key=True),
    Column("session_id", String(128), nullable=False),
    Column("workspace_id", String(128), nullable=False, default="local-workspace"),
    Column("status", String(64), nullable=False),
    Column("workflow_state", String(64), nullable=False, default=""),
    Column("task_type", String(64), nullable=False, default=""),
    Column("intent", Text, nullable=False, default=""),
    Column("artifact_path", Text, nullable=False, default=""),
    Column("review_report_json", Text, nullable=False, default="{}"),
    Column("metadata_json", Text, nullable=False, default="{}"),
    Column("error_encrypted", Text, nullable=False, default=""),
    Column("started_at", Float, nullable=False, default=_now),
    Column("completed_at", Float, nullable=False, default=0.0),
    Column("updated_at", Float, nullable=False, default=_now),
)
Index("ix_task_runs_workspace_updated", task_runs_table.c.workspace_id, task_runs_table.c.updated_at)

planned_steps_table = Table(
    "planned_steps",
    LOCAL_METADATA,
    Column("planned_step_id", String(128), primary_key=True),
    Column("run_id", String(128), ForeignKey("task_runs.run_id", ondelete="CASCADE"), nullable=False),
    Column("sequence_number", Integer, nullable=False, default=0),
    Column("step_type", String(64), nullable=False, default="task"),
    Column("objective", Text, nullable=False, default=""),
    Column("expected_artifacts_json", Text, nullable=False, default="[]"),
    Column("verification_method", String(128), nullable=False, default=""),
    Column("rollback_strategy", String(128), nullable=False, default=""),
    Column("created_at", Float, nullable=False, default=_now),
)
Index("ix_planned_steps_run_sequence", planned_steps_table.c.run_id, planned_steps_table.c.sequence_number)

execution_steps_table = Table(
    "execution_steps",
    LOCAL_METADATA,
    Column("execution_step_id", String(128), primary_key=True),
    Column("run_id", String(128), ForeignKey("task_runs.run_id", ondelete="CASCADE"), nullable=False),
    Column("planned_step_id", String(128), nullable=False, default=""),
    Column("status", String(64), nullable=False, default="queued"),
    Column("tool_name", String(128), nullable=False, default=""),
    Column("payload_json", Text, nullable=False, default="{}"),
    Column("result_json", Text, nullable=False, default="{}"),
    Column("started_at", Float, nullable=False, default=_now),
    Column("completed_at", Float, nullable=False, default=0.0),
)
Index("ix_execution_steps_run_started", execution_steps_table.c.run_id, execution_steps_table.c.started_at)

verification_results_table = Table(
    "verification_results",
    LOCAL_METADATA,
    Column("verification_id", String(128), primary_key=True),
    Column("run_id", String(128), ForeignKey("task_runs.run_id", ondelete="CASCADE"), nullable=False),
    Column("execution_step_id", String(128), nullable=False, default=""),
    Column("status", String(64), nullable=False, default="pending"),
    Column("method", String(128), nullable=False, default=""),
    Column("payload_json", Text, nullable=False, default="{}"),
    Column("created_at", Float, nullable=False, default=_now),
)
Index("ix_verification_results_run_created", verification_results_table.c.run_id, verification_results_table.c.created_at)

recovery_actions_table = Table(
    "recovery_actions",
    LOCAL_METADATA,
    Column("recovery_id", String(128), primary_key=True),
    Column("run_id", String(128), ForeignKey("task_runs.run_id", ondelete="CASCADE"), nullable=False),
    Column("verification_id", String(128), nullable=False, default=""),
    Column("decision", String(64), nullable=False, default="retry"),
    Column("payload_json", Text, nullable=False, default="{}"),
    Column("created_at", Float, nullable=False, default=_now),
)
Index("ix_recovery_actions_run_created", recovery_actions_table.c.run_id, recovery_actions_table.c.created_at)

tool_invocations_table = Table(
    "tool_invocations",
    LOCAL_METADATA,
    Column("tool_call_id", String(128), primary_key=True),
    Column("run_id", String(128), ForeignKey("task_runs.run_id", ondelete="CASCADE"), nullable=False),
    Column("tool_name", String(128), nullable=False),
    Column("payload_encrypted", Text, nullable=False, default=""),
    Column("result_encrypted", Text, nullable=False, default=""),
    Column("risk_level", String(64), nullable=False, default="read_only"),
    Column("created_at", Float, nullable=False, default=_now),
)
Index("ix_tool_invocations_run_created", tool_invocations_table.c.run_id, tool_invocations_table.c.created_at)

artifact_manifests_table = Table(
    "artifact_manifests",
    LOCAL_METADATA,
    Column("artifact_id", String(128), primary_key=True),
    Column("run_id", String(128), ForeignKey("task_runs.run_id", ondelete="CASCADE"), nullable=False),
    Column("label", String(256), nullable=False, default="artifact"),
    Column("path", Text, nullable=False, default=""),
    Column("kind", String(64), nullable=False, default="artifact"),
    Column("sha256", String(128), nullable=False, default=""),
    Column("metadata_json", Text, nullable=False, default="{}"),
    Column("created_at", Float, nullable=False, default=_now),
)
Index("ix_artifact_manifests_run_created", artifact_manifests_table.c.run_id, artifact_manifests_table.c.created_at)

artifact_diffs_table = Table(
    "artifact_diffs",
    LOCAL_METADATA,
    Column("artifact_diff_id", String(128), primary_key=True),
    Column("run_id", String(128), ForeignKey("task_runs.run_id", ondelete="CASCADE"), nullable=False),
    Column("artifact_id", String(128), nullable=False, default=""),
    Column("before_hash", String(128), nullable=False, default=""),
    Column("after_hash", String(128), nullable=False, default=""),
    Column("summary_json", Text, nullable=False, default="{}"),
    Column("created_at", Float, nullable=False, default=_now),
)
Index("ix_artifact_diffs_run_created", artifact_diffs_table.c.run_id, artifact_diffs_table.c.created_at)

file_mutations_table = Table(
    "file_mutations",
    LOCAL_METADATA,
    Column("mutation_id", String(128), primary_key=True),
    Column("run_id", String(128), ForeignKey("task_runs.run_id", ondelete="CASCADE"), nullable=False),
    Column("path", Text, nullable=False),
    Column("before_hash", String(128), nullable=False, default=""),
    Column("after_hash", String(128), nullable=False, default=""),
    Column("rollback_available", Boolean, nullable=False, default=False),
    Column("summary_json", Text, nullable=False, default="{}"),
    Column("created_at", Float, nullable=False, default=_now),
)
Index("ix_file_mutations_run_created", file_mutations_table.c.run_id, file_mutations_table.c.created_at)

replay_checkpoints_table = Table(
    "replay_checkpoints",
    LOCAL_METADATA,
    Column("checkpoint_id", String(128), primary_key=True),
    Column("run_id", String(128), ForeignKey("task_runs.run_id", ondelete="CASCADE"), nullable=False),
    Column("step_id", String(128), nullable=False, default=""),
    Column("sequence_number", Integer, nullable=False, default=0),
    Column("workflow_state", String(64), nullable=False, default=""),
    Column("summary_json", Text, nullable=False, default="{}"),
    Column("created_at", Float, nullable=False, default=_now),
)
Index("ix_replay_checkpoints_run_sequence", replay_checkpoints_table.c.run_id, replay_checkpoints_table.c.sequence_number)

permission_grants_table = Table(
    "permission_grants",
    LOCAL_METADATA,
    Column("grant_id", String(96), primary_key=True),
    Column("workspace_id", String(128), nullable=False, default="local-workspace"),
    Column("device_id", String(128), nullable=False, default="local-device"),
    Column("scope", String(128), nullable=False),
    Column("resource", String(256), nullable=False),
    Column("allowed_actions_json", Text, nullable=False, default="[]"),
    Column("ttl_seconds", Integer, nullable=False, default=0),
    Column("issued_by", String(128), nullable=False, default="runtime"),
    Column("revocable", Boolean, nullable=False, default=True),
    Column("created_at", Float, nullable=False, default=_now),
    Column("expires_at", Float, nullable=False, default=0.0),
    Column("metadata_json", Text, nullable=False, default="{}"),
)

outbox_events_table = Table(
    "outbox_events",
    LOCAL_METADATA,
    Column("event_id", String(96), primary_key=True),
    Column("workspace_id", String(128), nullable=False, default="local-workspace"),
    Column("aggregate_type", String(64), nullable=False),
    Column("aggregate_id", String(128), nullable=False),
    Column("event_type", String(128), nullable=False),
    Column("payload_json", Text, nullable=False, default="{}"),
    Column("sync_state", String(32), nullable=False, default="pending"),
    Column("delivery_attempts", Integer, nullable=False, default=0),
    Column("last_error", Text, nullable=False, default=""),
    Column("created_at", Float, nullable=False, default=_now),
    Column("updated_at", Float, nullable=False, default=_now),
)
Index("ix_outbox_state_created", outbox_events_table.c.sync_state, outbox_events_table.c.created_at)

retention_policies_table = Table(
    "retention_policies",
    LOCAL_METADATA,
    Column("policy_id", String(96), primary_key=True),
    Column("scope_type", String(64), nullable=False),
    Column("scope_id", String(128), nullable=False),
    Column("retention_class", String(32), nullable=False, default="standard"),
    Column("no_store", Boolean, nullable=False, default=False),
    Column("redacted", Boolean, nullable=False, default=True),
    Column("metadata_json", Text, nullable=False, default="{}"),
    Column("updated_at", Float, nullable=False, default=_now),
)

secret_refs_table = Table(
    "secret_refs",
    LOCAL_METADATA,
    Column("secret_ref_id", String(96), primary_key=True),
    Column("workspace_id", String(128), nullable=False, default="local-workspace"),
    Column("device_id", String(128), nullable=False, default="local-device"),
    Column("scope", String(128), nullable=False),
    Column("classification", String(64), nullable=False, default="secret"),
    Column("cipher_envelope", Text, nullable=False, default=""),
    Column("metadata_json", Text, nullable=False, default="{}"),
    Column("created_at", Float, nullable=False, default=_now),
    Column("updated_at", Float, nullable=False, default=_now),
)

audit_events_table = Table(
    "audit_events",
    LOCAL_METADATA,
    Column("event_id", String(96), primary_key=True),
    Column("workspace_id", String(128), nullable=False, default="local-workspace"),
    Column("event_type", String(128), nullable=False),
    Column("payload_json", Text, nullable=False, default="{}"),
    Column("created_at", Float, nullable=False, default=_now),
)
Index("ix_audit_events_type_created", audit_events_table.c.event_type, audit_events_table.c.created_at)

workspaces_table = Table(
    "workspaces",
    WORKSPACE_METADATA,
    Column("workspace_id", String(128), primary_key=True),
    Column("display_name", String(256), nullable=False, default=""),
    Column("status", String(64), nullable=False, default="active"),
    Column("metadata_json", Text, nullable=False, default="{}"),
    Column("updated_at", Float, nullable=False, default=_now),
)

workspace_memberships_table = Table(
    "workspace_memberships",
    WORKSPACE_METADATA,
    Column("membership_id", String(128), primary_key=True),
    Column("workspace_id", String(128), nullable=False),
    Column("actor_id", String(128), nullable=False),
    Column("role", String(64), nullable=False, default="member"),
    Column("status", String(64), nullable=False, default="active"),
    Column("updated_at", Float, nullable=False, default=_now),
)
Index("ix_workspace_memberships_workspace_actor", workspace_memberships_table.c.workspace_id, workspace_memberships_table.c.actor_id)

workspace_devices_table = Table(
    "workspace_devices",
    WORKSPACE_METADATA,
    Column("device_id", String(128), primary_key=True),
    Column("workspace_id", String(128), nullable=False),
    Column("platform", String(64), nullable=False, default="unknown"),
    Column("status", String(64), nullable=False, default="active"),
    Column("metadata_json", Text, nullable=False, default="{}"),
    Column("updated_at", Float, nullable=False, default=_now),
)
Index("ix_workspace_devices_workspace_updated", workspace_devices_table.c.workspace_id, workspace_devices_table.c.updated_at)

workspace_policies_table = Table(
    "workspace_policies",
    WORKSPACE_METADATA,
    Column("policy_id", String(128), primary_key=True),
    Column("workspace_id", String(128), nullable=False),
    Column("policy_type", String(64), nullable=False),
    Column("payload_json", Text, nullable=False, default="{}"),
    Column("updated_at", Float, nullable=False, default=_now),
)
Index("ix_workspace_policies_workspace_type", workspace_policies_table.c.workspace_id, workspace_policies_table.c.policy_type)

workspace_threads_table = Table(
    "workspace_threads",
    WORKSPACE_METADATA,
    Column("thread_id", String(64), primary_key=True),
    Column("workspace_id", String(128), nullable=False),
    Column("status", String(64), nullable=False, default="queued"),
    Column("current_mode", String(32), nullable=False, default="cowork"),
    Column("summary_json", Text, nullable=False, default="{}"),
    Column("updated_at", Float, nullable=False, default=_now),
)
Index("ix_workspace_threads_workspace_updated", workspace_threads_table.c.workspace_id, workspace_threads_table.c.updated_at)

workspace_thread_snapshots_table = Table(
    "workspace_thread_snapshots",
    WORKSPACE_METADATA,
    Column("snapshot_id", String(96), primary_key=True),
    Column("workspace_id", String(128), nullable=False),
    Column("thread_id", String(64), nullable=False),
    Column("status", String(64), nullable=False, default="queued"),
    Column("payload_json", Text, nullable=False, default="{}"),
    Column("created_at", Float, nullable=False, default=_now),
)
Index("ix_workspace_thread_snapshots_workspace_created", workspace_thread_snapshots_table.c.workspace_id, workspace_thread_snapshots_table.c.created_at)

workspace_approvals_table = Table(
    "workspace_approvals",
    WORKSPACE_METADATA,
    Column("request_id", String(64), primary_key=True),
    Column("workspace_id", String(128), nullable=False),
    Column("status", String(64), nullable=False, default="pending"),
    Column("payload_json", Text, nullable=False, default="{}"),
    Column("updated_at", Float, nullable=False, default=_now),
)

connector_accounts_table = Table(
    "connector_accounts",
    WORKSPACE_METADATA,
    Column("account_id", String(128), primary_key=True),
    Column("workspace_id", String(128), nullable=False),
    Column("connector_name", String(64), nullable=False),
    Column("provider", String(64), nullable=False, default=""),
    Column("display_name", String(256), nullable=False, default=""),
    Column("status", String(64), nullable=False, default="connected"),
    Column("scopes_json", Text, nullable=False, default="[]"),
    Column("metadata_json", Text, nullable=False, default="{}"),
    Column("updated_at", Float, nullable=False, default=_now),
)
Index("ix_connector_accounts_workspace_updated", connector_accounts_table.c.workspace_id, connector_accounts_table.c.updated_at)

connector_definitions_table = Table(
    "connector_definitions",
    WORKSPACE_METADATA,
    Column("connector_name", String(64), primary_key=True),
    Column("provider", String(64), nullable=False, default=""),
    Column("label", String(128), nullable=False, default=""),
    Column("capabilities_json", Text, nullable=False, default="[]"),
    Column("updated_at", Float, nullable=False, default=_now),
)

connector_scopes_table = Table(
    "connector_scopes",
    WORKSPACE_METADATA,
    Column("scope_id", String(128), primary_key=True),
    Column("account_id", String(128), nullable=False),
    Column("workspace_id", String(128), nullable=False),
    Column("scope", String(128), nullable=False),
    Column("status", String(64), nullable=False, default="granted"),
    Column("updated_at", Float, nullable=False, default=_now),
)
Index("ix_connector_scopes_workspace_account", connector_scopes_table.c.workspace_id, connector_scopes_table.c.account_id)

connector_health_table = Table(
    "connector_health",
    WORKSPACE_METADATA,
    Column("health_id", String(128), primary_key=True),
    Column("account_id", String(128), nullable=False),
    Column("workspace_id", String(128), nullable=False),
    Column("status", String(64), nullable=False, default="healthy"),
    Column("payload_json", Text, nullable=False, default="{}"),
    Column("updated_at", Float, nullable=False, default=_now),
)
Index("ix_connector_health_workspace_updated", connector_health_table.c.workspace_id, connector_health_table.c.updated_at)

connector_action_traces_table = Table(
    "connector_action_traces",
    WORKSPACE_METADATA,
    Column("trace_id", String(128), primary_key=True),
    Column("workspace_id", String(128), nullable=False),
    Column("connector_account_id", String(128), nullable=False),
    Column("connector_name", String(64), nullable=False),
    Column("event_type", String(128), nullable=False),
    Column("payload_json", Text, nullable=False, default="{}"),
    Column("created_at", Float, nullable=False, default=_now),
)
Index("ix_connector_action_traces_workspace_created", connector_action_traces_table.c.workspace_id, connector_action_traces_table.c.created_at)

billing_customers_table = Table(
    "billing_customers",
    WORKSPACE_METADATA,
    Column("workspace_id", String(128), primary_key=True),
    Column("billing_customer", String(128), nullable=False, default=""),
    Column("stripe_customer_id", String(128), nullable=False, default=""),
    Column("updated_at", Float, nullable=False, default=_now),
)

subscriptions_table = Table(
    "subscriptions",
    WORKSPACE_METADATA,
    Column("workspace_id", String(128), primary_key=True),
    Column("plan_id", String(64), nullable=False, default="free"),
    Column("status", String(64), nullable=False, default="inactive"),
    Column("current_period_end", Float, nullable=False, default=0.0),
    Column("payload_json", Text, nullable=False, default="{}"),
    Column("updated_at", Float, nullable=False, default=_now),
)

entitlement_snapshots_table = Table(
    "entitlement_snapshots",
    WORKSPACE_METADATA,
    Column("snapshot_id", String(96), primary_key=True),
    Column("workspace_id", String(128), nullable=False),
    Column("scope", String(64), nullable=False, default="workspace"),
    Column("payload_json", Text, nullable=False, default="{}"),
    Column("created_at", Float, nullable=False, default=_now),
)
Index("ix_entitlement_snapshots_scope_updated", entitlement_snapshots_table.c.scope, entitlement_snapshots_table.c.created_at)

workspace_usage_ledger_table = Table(
    "usage_ledger",
    WORKSPACE_METADATA,
    Column("usage_id", String(96), primary_key=True),
    Column("workspace_id", String(128), nullable=False),
    Column("metric", String(64), nullable=False),
    Column("amount", Integer, nullable=False, default=0),
    Column("payload_json", Text, nullable=False, default="{}"),
    Column("created_at", Float, nullable=False, default=_now),
)

workspace_audit_index_table = Table(
    "workspace_audit_index",
    WORKSPACE_METADATA,
    Column("event_id", String(96), primary_key=True),
    Column("workspace_id", String(128), nullable=False),
    Column("event_type", String(128), nullable=False),
    Column("payload_json", Text, nullable=False, default="{}"),
    Column("created_at", Float, nullable=False, default=_now),
)
Index("ix_workspace_audit_index_type_created", workspace_audit_index_table.c.event_type, workspace_audit_index_table.c.created_at)

sync_receipts_table = Table(
    "sync_receipts",
    WORKSPACE_METADATA,
    Column("event_id", String(96), primary_key=True),
    Column("workspace_id", String(128), nullable=False),
    Column("accepted_at", Float, nullable=False, default=_now),
)


class OutboxRepository:
    def __init__(self, db: "RuntimeDatabase") -> None:
        self._db = db

    def enqueue(
        self,
        conn: Connection,
        *,
        workspace_id: str,
        aggregate_type: str,
        aggregate_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> str:
        event_id = f"evt_{uuid.uuid4().hex[:16]}"
        now = _now()
        conn.execute(
            outbox_events_table.insert().values(
                event_id=event_id,
                workspace_id=str(workspace_id or "local-workspace"),
                aggregate_type=str(aggregate_type or "unknown"),
                aggregate_id=str(aggregate_id or ""),
                event_type=str(event_type or "unknown"),
                payload_json=_json_dumps(payload),
                sync_state="pending",
                delivery_attempts=0,
                last_error="",
                created_at=now,
                updated_at=now,
            )
        )
        return event_id

    def list_pending(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self._db.local_engine.begin() as conn:
            rows = conn.execute(
                select(outbox_events_table)
                .where(outbox_events_table.c.sync_state == "pending")
                .order_by(outbox_events_table.c.created_at.asc())
                .limit(max(1, int(limit or 100)))
            ).mappings().all()
        return [self._db._decode_outbox_row(row) for row in rows]

    def mark_delivered(self, event_id: str) -> None:
        with self._db.local_engine.begin() as conn:
            conn.execute(
                outbox_events_table.update()
                .where(outbox_events_table.c.event_id == str(event_id))
                .values(sync_state="delivered", updated_at=_now())
            )


class ThreadRepository:
    def __init__(self, db: "RuntimeDatabase") -> None:
        self._db = db

    def ensure_legacy_import(self, legacy_path: Path) -> None:
        with self._db.local_engine.begin() as conn:
            existing = conn.execute(select(func.count()).select_from(cowork_threads_table)).scalar_one()
            if existing:
                return
        if not legacy_path.exists():
            return
        try:
            payload = json.loads(legacy_path.read_text(encoding="utf-8"))
        except Exception as exc:
            slog.log_event("runtime_db_threads_legacy_read_error", {"error": str(exc)}, level="warning")
            return
        if not isinstance(payload, dict):
            return
        with self._db.local_engine.begin() as conn:
            for item in payload.values():
                if not isinstance(item, dict):
                    continue
                turns = list(item.get("turns") or [])
                self._upsert_thread(conn, item, turns, enqueue=False)

    def load_all_threads(self) -> dict[str, dict[str, Any]]:
        with self._db.local_engine.begin() as conn:
            rows = conn.execute(select(cowork_threads_table)).mappings().all()
            turn_rows = conn.execute(
                select(cowork_turns_table).order_by(cowork_turns_table.c.created_at.asc())
            ).mappings().all()
        turns_by_thread: dict[str, list[dict[str, Any]]] = {}
        for row in turn_rows:
            turns_by_thread.setdefault(str(row["thread_id"]), []).append(self._db._decode_turn_row(row))
        out: dict[str, dict[str, Any]] = {}
        for row in rows:
            item = self._db._decode_thread_row(row)
            item["turns"] = turns_by_thread.get(item["thread_id"], [])
            out[item["thread_id"]] = item
        return out

    def thread_count(self, *, workspace_id: str) -> int:
        with self._db.local_engine.begin() as conn:
            return int(
                conn.execute(
                    select(func.count()).select_from(cowork_threads_table).where(cowork_threads_table.c.workspace_id == str(workspace_id))
                ).scalar_one()
            )

    def save_thread(self, thread_payload: dict[str, Any], turns: list[dict[str, Any]]) -> None:
        with self._db.local_engine.begin() as conn:
            self._upsert_thread(conn, thread_payload, turns, enqueue=True)

    def _upsert_thread(self, conn: Connection, thread_payload: dict[str, Any], turns: list[dict[str, Any]], *, enqueue: bool) -> None:
        thread_id = str(thread_payload.get("thread_id") or "")
        if not thread_id:
            return
        now = _now()
        base_values = {
            "thread_id": thread_id,
            "workspace_id": str(thread_payload.get("workspace_id") or "local-workspace"),
            "session_id": str(thread_payload.get("session_id") or "desktop"),
            "title": str(thread_payload.get("title") or "Cowork thread"),
            "current_mode": str(thread_payload.get("current_mode") or "cowork"),
            "status": str(thread_payload.get("status") or "queued"),
            "active_run_id": str(thread_payload.get("active_run_id") or ""),
            "active_mission_id": str(thread_payload.get("active_mission_id") or ""),
            "metadata_json": _json_dumps(dict(thread_payload.get("metadata") or {})),
            "created_at": float(thread_payload.get("created_at") or now),
            "updated_at": float(thread_payload.get("updated_at") or now),
            "version": max(1, int(thread_payload.get("version") or 1)),
        }
        existing = conn.execute(
            select(cowork_threads_table.c.thread_id).where(cowork_threads_table.c.thread_id == thread_id)
        ).first()
        if existing:
            conn.execute(
                cowork_threads_table.update()
                .where(cowork_threads_table.c.thread_id == thread_id)
                .values(**base_values)
            )
        else:
            conn.execute(cowork_threads_table.insert().values(**base_values))
        conn.execute(cowork_turns_table.delete().where(cowork_turns_table.c.thread_id == thread_id))
        for turn in turns:
            conn.execute(
                cowork_turns_table.insert().values(
                    turn_id=str(turn.get("turn_id") or f"turn_{uuid.uuid4().hex[:10]}"),
                    thread_id=thread_id,
                    role=str(turn.get("role") or "user"),
                    content=str(turn.get("content") or ""),
                    created_at=float(turn.get("created_at") or now),
                    mode=str(turn.get("mode") or "cowork"),
                    status=str(turn.get("status") or "completed"),
                    mission_id=str(turn.get("mission_id") or ""),
                    run_id=str(turn.get("run_id") or ""),
                    metadata_json=_json_dumps(dict(turn.get("metadata") or {})),
                )
            )
        if enqueue:
            self._db.outbox.enqueue(
                conn,
                workspace_id=base_values["workspace_id"],
                aggregate_type="cowork_thread",
                aggregate_id=thread_id,
                event_type="cowork.thread.updated",
                payload={
                    "thread_id": thread_id,
                    "workspace_id": base_values["workspace_id"],
                    "status": base_values["status"],
                    "current_mode": base_values["current_mode"],
                    "updated_at": base_values["updated_at"],
                },
            )


class ApprovalRepository:
    def __init__(self, db: "RuntimeDatabase") -> None:
        self._db = db

    def ensure_legacy_import(self, legacy_path: Path) -> None:
        with self._db.local_engine.begin() as conn:
            pending = conn.execute(
                select(func.count()).select_from(approvals_table).where(approvals_table.c.status == "pending")
            ).scalar_one()
            if pending:
                return
        if not legacy_path.exists():
            return
        try:
            payload = json.loads(legacy_path.read_text(encoding="utf-8"))
        except Exception as exc:
            slog.log_event("runtime_db_approvals_legacy_read_error", {"error": str(exc)}, level="warning")
            return
        if not isinstance(payload, list):
            return
        with self._db.local_engine.begin() as conn:
            for item in payload:
                if isinstance(item, dict):
                    self._upsert(conn, item, enqueue=False)

    def list_pending(self) -> list[dict[str, Any]]:
        with self._db.local_engine.begin() as conn:
            rows = conn.execute(
                select(approvals_table)
                .where(approvals_table.c.status == "pending")
                .order_by(approvals_table.c.created_at.asc())
            ).mappings().all()
        return [self._db._decode_approval_row(row) for row in rows]

    def upsert_pending(self, approval_payload: dict[str, Any]) -> None:
        with self._db.local_engine.begin() as conn:
            self._upsert(conn, approval_payload, enqueue=True)

    def mark_resolved(self, request_id: str, *, approved: bool, resolver_id: str, note: str = "") -> None:
        status = "approved" if approved else "denied"
        with self._db.local_engine.begin() as conn:
            row = conn.execute(
                select(approvals_table).where(approvals_table.c.request_id == str(request_id))
            ).mappings().first()
            if row is None:
                return
            now = _now()
            conn.execute(
                approvals_table.update()
                .where(approvals_table.c.request_id == str(request_id))
                .values(status=status, resolver_id=str(resolver_id or ""), resolution_note=str(note or ""), resolved_at=now, updated_at=now)
            )
            decoded = self._db._decode_approval_row(row)
            self._db.outbox.enqueue(
                conn,
                workspace_id=str(decoded.get("workspace_id") or "local-workspace"),
                aggregate_type="approval",
                aggregate_id=str(request_id),
                event_type="cowork.approval.resolved",
                payload={"request_id": str(request_id), "status": status, "resolver_id": str(resolver_id or "")},
            )

    def mark_timed_out(self, request_id: str) -> None:
        with self._db.local_engine.begin() as conn:
            conn.execute(
                approvals_table.update()
                .where(approvals_table.c.request_id == str(request_id))
                .values(status="timed_out", resolved_at=_now(), updated_at=_now())
            )

    def _upsert(self, conn: Connection, approval_payload: dict[str, Any], *, enqueue: bool) -> None:
        request_id = str(approval_payload.get("request_id") or "")
        if not request_id:
            return
        now = _now()
        workspace_id = str(
            approval_payload.get("workspace_id")
            or approval_payload.get("metadata", {}).get("workspace_id")
            or "local-workspace"
        )
        values = {
            "request_id": request_id,
            "workspace_id": workspace_id,
            "session_id": str(approval_payload.get("session_id") or "unknown"),
            "run_id": str(approval_payload.get("run_id") or ""),
            "action_type": str(approval_payload.get("action_type") or "unknown"),
            "payload_encrypted": self._db.codec.dumps(
                dict(approval_payload.get("payload") or {}),
                context=f"approval:{request_id}:payload",
                classification="secret",
            ),
            "risk_level": str(approval_payload.get("risk_level") or "write_safe"),
            "reason": str(approval_payload.get("reason") or ""),
            "status": str(approval_payload.get("status") or "pending"),
            "resolver_id": str(approval_payload.get("resolver_id") or ""),
            "resolution_note": str(approval_payload.get("resolution_note") or ""),
            "created_at": float(approval_payload.get("created_at") or now),
            "resolved_at": float(approval_payload.get("resolved_at") or 0.0),
            "updated_at": now,
        }
        existing = conn.execute(
            select(approvals_table.c.request_id).where(approvals_table.c.request_id == request_id)
        ).first()
        if existing:
            conn.execute(approvals_table.update().where(approvals_table.c.request_id == request_id).values(**values))
        else:
            conn.execute(approvals_table.insert().values(**values))
        if enqueue:
            self._db.outbox.enqueue(
                conn,
                workspace_id=workspace_id,
                aggregate_type="approval",
                aggregate_id=request_id,
                event_type="cowork.approval.requested",
                payload={
                    "request_id": request_id,
                    "workspace_id": workspace_id,
                    "action_type": values["action_type"],
                    "status": values["status"],
                    "risk_level": values["risk_level"],
                },
            )


class BillingRepository:
    def __init__(self, db: "RuntimeDatabase") -> None:
        self._db = db

    def ensure_legacy_import(self, legacy_path: Path) -> None:
        with self._db.local_engine.begin() as conn:
            existing = conn.execute(select(func.count()).select_from(billing_workspaces_table)).scalar_one()
            if existing:
                return
        if not legacy_path.exists():
            return
        try:
            payload = json.loads(legacy_path.read_text(encoding="utf-8"))
        except Exception as exc:
            slog.log_event("runtime_db_billing_legacy_read_error", {"error": str(exc)}, level="warning")
            return
        if not isinstance(payload, dict):
            return
        with self._db.local_engine.begin() as conn:
            for item in payload.values():
                if not isinstance(item, dict):
                    continue
                self._upsert_workspace(conn, item, enqueue=False)
                for usage in list(item.get("usage") or []):
                    if isinstance(usage, dict):
                        self._insert_usage(conn, usage)

    def load_workspace_records(self) -> dict[str, dict[str, Any]]:
        with self._db.local_engine.begin() as conn:
            rows = conn.execute(select(billing_workspaces_table)).mappings().all()
            usage_rows = conn.execute(
                select(usage_ledger_table).order_by(usage_ledger_table.c.created_at.asc())
            ).mappings().all()
        usage_by_workspace: dict[str, list[dict[str, Any]]] = {}
        for row in usage_rows:
            item = self._db._decode_usage_row(row)
            usage_by_workspace.setdefault(item["workspace_id"], []).append(item)
        out: dict[str, dict[str, Any]] = {}
        for row in rows:
            item = self._db._decode_billing_row(row)
            item["usage"] = usage_by_workspace.get(item["workspace_id"], [])
            out[item["workspace_id"]] = item
        return out

    def upsert_workspace(self, workspace_payload: dict[str, Any]) -> None:
        with self._db.local_engine.begin() as conn:
            self._upsert_workspace(conn, workspace_payload, enqueue=True)

    def record_usage(self, usage_payload: dict[str, Any]) -> None:
        with self._db.local_engine.begin() as conn:
            self._insert_usage(conn, usage_payload)
            self._db.outbox.enqueue(
                conn,
                workspace_id=str(usage_payload.get("workspace_id") or "local-workspace"),
                aggregate_type="usage",
                aggregate_id=str(usage_payload.get("usage_id") or ""),
                event_type="billing.usage.recorded",
                payload={"workspace_id": str(usage_payload.get("workspace_id") or "local-workspace"), "metric": str(usage_payload.get("metric") or "unknown"), "amount": int(usage_payload.get("amount") or 0)},
            )

    def _upsert_workspace(self, conn: Connection, workspace_payload: dict[str, Any], *, enqueue: bool) -> None:
        workspace_id = str(workspace_payload.get("workspace_id") or "local-workspace")
        values = {
            "workspace_id": workspace_id,
            "plan_id": str(workspace_payload.get("plan_id") or "free"),
            "status": str(workspace_payload.get("status") or "inactive"),
            "billing_customer": str(workspace_payload.get("billing_customer") or ""),
            "stripe_customer_id": str(workspace_payload.get("stripe_customer_id") or ""),
            "stripe_subscription_id": str(workspace_payload.get("stripe_subscription_id") or ""),
            "current_period_end": float(workspace_payload.get("current_period_end") or 0.0),
            "seats": max(1, int(workspace_payload.get("seats") or 1)),
            "checkout_url": str(workspace_payload.get("checkout_url") or ""),
            "portal_url": str(workspace_payload.get("portal_url") or ""),
            "metadata_json": _json_dumps(dict(workspace_payload.get("metadata") or {})),
            "updated_at": float(workspace_payload.get("updated_at") or _now()),
        }
        existing = conn.execute(
            select(billing_workspaces_table.c.workspace_id).where(billing_workspaces_table.c.workspace_id == workspace_id)
        ).first()
        if existing:
            conn.execute(
                billing_workspaces_table.update().where(billing_workspaces_table.c.workspace_id == workspace_id).values(**values)
            )
        else:
            conn.execute(billing_workspaces_table.insert().values(**values))
        if enqueue:
            self._db.outbox.enqueue(
                conn,
                workspace_id=workspace_id,
                aggregate_type="billing_workspace",
                aggregate_id=workspace_id,
                event_type="billing.workspace.updated",
                payload={"workspace_id": workspace_id, "plan_id": values["plan_id"], "status": values["status"]},
            )

    def _insert_usage(self, conn: Connection, usage_payload: dict[str, Any]) -> None:
        usage_id = str(usage_payload.get("usage_id") or f"usage_{int(_now() * 1000)}")
        existing = conn.execute(
            select(usage_ledger_table.c.usage_id).where(usage_ledger_table.c.usage_id == usage_id)
        ).first()
        if existing:
            return
        conn.execute(
            usage_ledger_table.insert().values(
                usage_id=usage_id,
                workspace_id=str(usage_payload.get("workspace_id") or "local-workspace"),
                metric=str(usage_payload.get("metric") or "unknown"),
                amount=max(0, int(usage_payload.get("amount") or 0)),
                metadata_json=_json_dumps(dict(usage_payload.get("metadata") or {})),
                created_at=float(usage_payload.get("created_at") or _now()),
            )
        )


class RunIndexRepository:
    def __init__(self, db: "RuntimeDatabase") -> None:
        self._db = db

    def upsert_run(self, run_payload: dict[str, Any]) -> None:
        run_id = str(run_payload.get("run_id") or "")
        if not run_id:
            return
        metadata = dict(run_payload.get("metadata") or {})
        workspace_id = str(metadata.get("workspace_id") or "local-workspace")
        with self._db.local_engine.begin() as conn:
            values = {
                "run_id": run_id,
                "session_id": str(run_payload.get("session_id") or "desktop"),
                "workspace_id": workspace_id,
                "status": str(run_payload.get("status") or "unknown"),
                "workflow_state": str(run_payload.get("workflow_state") or ""),
                "task_type": str(run_payload.get("task_type") or ""),
                "intent": str(run_payload.get("intent") or ""),
                "artifact_path": str(run_payload.get("artifact_path") or ""),
                "review_report_json": _json_dumps(dict(run_payload.get("review_report") or {})),
                "metadata_json": _json_dumps(metadata),
                "error_encrypted": self._db.codec.dumps(
                    run_payload.get("error"),
                    context=f"run_index:{run_id}:error",
                    classification="sensitive",
                ),
                "started_at": float(run_payload.get("started_at") or _now()),
                "completed_at": float(run_payload.get("completed_at") or 0.0),
                "updated_at": _now(),
            }
            existing = conn.execute(select(task_runs_table.c.run_id).where(task_runs_table.c.run_id == run_id)).first()
            if existing:
                conn.execute(task_runs_table.update().where(task_runs_table.c.run_id == run_id).values(**values))
            else:
                conn.execute(task_runs_table.insert().values(**values))

            conn.execute(artifact_manifests_table.delete().where(artifact_manifests_table.c.run_id == run_id))
            for index, artifact in enumerate(list(run_payload.get("artifacts") or []), start=1):
                if not isinstance(artifact, dict):
                    continue
                conn.execute(
                    artifact_manifests_table.insert().values(
                        artifact_id=str(artifact.get("artifact_id") or artifact.get("path") or f"{run_id}_artifact_{index}"),
                        run_id=run_id,
                        label=str(artifact.get("label") or artifact.get("path") or f"artifact_{index}"),
                        path=str(artifact.get("path") or ""),
                        kind=str(artifact.get("kind") or values["task_type"] or "artifact"),
                        sha256=str(artifact.get("sha256") or ""),
                        metadata_json=_json_dumps(dict(artifact.get("metadata") or {})),
                        created_at=float(artifact.get("created_at") or values["completed_at"] or values["started_at"]),
                    )
                )

            conn.execute(replay_checkpoints_table.delete().where(replay_checkpoints_table.c.run_id == run_id))
            sequence_number = 0
            for step in list(run_payload.get("steps") or []):
                if not isinstance(step, dict):
                    continue
                if str(step.get("status") or "") not in {"completed", "passed"}:
                    continue
                sequence_number += 1
                conn.execute(
                    replay_checkpoints_table.insert().values(
                        checkpoint_id=f"chk_{run_id}_{sequence_number}",
                        run_id=run_id,
                        step_id=str(step.get("step_id") or f"step_{sequence_number}"),
                        sequence_number=sequence_number,
                        workflow_state=str(values["workflow_state"] or values["status"] or ""),
                        summary_json=_json_dumps(
                            {
                                "name": str(step.get("name") or "step"),
                                "status": str(step.get("status") or "completed"),
                                "result": step.get("result") if isinstance(step.get("result"), dict) else {},
                                "rollback_available": bool(step.get("rollback_available") or False),
                            }
                        ),
                        created_at=float(step.get("completed_at") or step.get("started_at") or _now()),
                    )
                )

            self._db.outbox.enqueue(
                conn,
                workspace_id=workspace_id,
                aggregate_type="task_run",
                aggregate_id=run_id,
                event_type="cowork.run.state_changed",
                payload={"run_id": run_id, "workspace_id": workspace_id, "status": values["status"], "workflow_state": values["workflow_state"]},
            )

    def mark_status(self, run_id: str, *, status: str, completed_at: float | None = None) -> None:
        with self._db.local_engine.begin() as conn:
            conn.execute(
                task_runs_table.update()
                .where(task_runs_table.c.run_id == str(run_id))
                .values(status=str(status or "unknown"), completed_at=float(completed_at or 0.0), updated_at=_now())
            )

    def get_run_index(self, run_id: str) -> dict[str, Any] | None:
        with self._db.local_engine.begin() as conn:
            row = conn.execute(select(task_runs_table).where(task_runs_table.c.run_id == str(run_id))).mappings().first()
            if row is None:
                return None
            artifacts = conn.execute(
                select(artifact_manifests_table)
                .where(artifact_manifests_table.c.run_id == str(run_id))
                .order_by(artifact_manifests_table.c.created_at.asc())
            ).mappings().all()
            checkpoints = conn.execute(
                select(replay_checkpoints_table)
                .where(replay_checkpoints_table.c.run_id == str(run_id))
                .order_by(replay_checkpoints_table.c.sequence_number.asc())
            ).mappings().all()
        payload = self._db._decode_run_row(row)
        payload["artifacts"] = [self._db._decode_artifact_row(item) for item in artifacts]
        payload["replay_checkpoints"] = [self._db._decode_checkpoint_row(item) for item in checkpoints]
        return payload


class WorkspaceSyncAdapter:
    def __init__(self, database_url: str = "") -> None:
        self.database_url = str(database_url or os.getenv("ELYAN_WORKSPACE_DATABASE_URL", "") or "").strip()
        self.enabled = bool(self.database_url)
        self.engine: Engine | None = None
        if not self.enabled:
            return
        self.engine = create_engine(self.database_url, future=True)
        WORKSPACE_METADATA.create_all(self.engine)

    def accept_outbox_event(self, event_payload: dict[str, Any]) -> bool:
        if not self.enabled or self.engine is None:
            return False
        workspace_id = str(event_payload.get("workspace_id") or "local-workspace")
        event_id = str(event_payload.get("event_id") or "")
        if not event_id:
            return False
        with self.engine.begin() as conn:
            existing = conn.execute(
                select(sync_receipts_table.c.event_id).where(sync_receipts_table.c.event_id == event_id)
            ).first()
            if existing:
                return True
            event_type = str(event_payload.get("event_type") or "unknown")
            aggregate_type = str(event_payload.get("aggregate_type") or "unknown")
            payload = dict(event_payload.get("payload") or {})
            if aggregate_type == "cowork_thread":
                existing_thread = conn.execute(
                    select(workspace_threads_table.c.thread_id).where(workspace_threads_table.c.thread_id == str(event_payload.get("aggregate_id") or ""))
                ).first()
                thread_values = {
                    "thread_id": str(event_payload.get("aggregate_id") or ""),
                    "workspace_id": workspace_id,
                    "status": str(payload.get("status") or "queued"),
                    "current_mode": str(payload.get("current_mode") or "cowork"),
                    "summary_json": _json_dumps(payload),
                    "updated_at": _now(),
                }
                if existing_thread:
                    conn.execute(
                        workspace_threads_table.update()
                        .where(workspace_threads_table.c.thread_id == thread_values["thread_id"])
                        .values(**thread_values)
                    )
                else:
                    conn.execute(workspace_threads_table.insert().values(**thread_values))
                conn.execute(
                    workspace_thread_snapshots_table.insert().values(
                        snapshot_id=f"snap_{uuid.uuid4().hex[:16]}",
                        workspace_id=workspace_id,
                        thread_id=str(event_payload.get("aggregate_id") or ""),
                        status=str(payload.get("status") or "queued"),
                        payload_json=_json_dumps(payload),
                        created_at=float(event_payload.get("created_at") or _now()),
                    )
                )
            elif aggregate_type == "approval":
                request_id = str(event_payload.get("aggregate_id") or event_id)
                approval_values = {
                    "request_id": request_id,
                    "workspace_id": workspace_id,
                    "status": str(payload.get("status") or "pending"),
                    "payload_json": _json_dumps(payload),
                    "updated_at": _now(),
                }
                existing_approval = conn.execute(
                    select(workspace_approvals_table.c.request_id).where(workspace_approvals_table.c.request_id == request_id)
                ).first()
                if existing_approval:
                    conn.execute(
                        workspace_approvals_table.update()
                        .where(workspace_approvals_table.c.request_id == request_id)
                        .values(**approval_values)
                    )
                else:
                    conn.execute(workspace_approvals_table.insert().values(**approval_values))
            elif aggregate_type == "billing_workspace":
                subscription_values = {
                    "workspace_id": workspace_id,
                    "plan_id": str(payload.get("plan_id") or "free"),
                    "status": str(payload.get("status") or "inactive"),
                    "current_period_end": 0.0,
                    "payload_json": _json_dumps(payload),
                    "updated_at": _now(),
                }
                existing_subscription = conn.execute(
                    select(subscriptions_table.c.workspace_id).where(subscriptions_table.c.workspace_id == workspace_id)
                ).first()
                if existing_subscription:
                    conn.execute(
                        subscriptions_table.update()
                        .where(subscriptions_table.c.workspace_id == workspace_id)
                        .values(**subscription_values)
                    )
                else:
                    conn.execute(subscriptions_table.insert().values(**subscription_values))
            elif aggregate_type == "task_run":
                conn.execute(
                    workspace_audit_index_table.insert().values(
                        event_id=event_id,
                        workspace_id=workspace_id,
                        event_type=event_type,
                        payload_json=_json_dumps(payload),
                        created_at=float(event_payload.get("created_at") or _now()),
                    )
                )
            conn.execute(sync_receipts_table.insert().values(event_id=event_id, workspace_id=workspace_id, accepted_at=_now()))
        return True


class RuntimeDatabase:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = Path(db_path or resolve_runtime_db_path()).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.codec = EncryptedFieldCodec()
        self.local_engine = create_engine(
            f"sqlite+pysqlite:///{self.db_path}",
            future=True,
            connect_args={"check_same_thread": False},
        )
        self._configure_sqlite(self.local_engine)
        LOCAL_METADATA.create_all(self.local_engine)
        self._stamp_schema()
        self.outbox = OutboxRepository(self)
        self.threads = ThreadRepository(self)
        self.approvals = ApprovalRepository(self)
        self.billing = BillingRepository(self)
        self.run_index = RunIndexRepository(self)
        self.workspace_sync = WorkspaceSyncAdapter()

    @staticmethod
    def _configure_sqlite(engine: Engine) -> None:
        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_connection, _connection_record):  # type: ignore[no-untyped-def]
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.close()

    def _stamp_schema(self) -> None:
        with self.local_engine.begin() as conn:
            existing = conn.execute(
                select(schema_migrations.c.name).where(schema_migrations.c.name == "runtime_db_v1")
            ).first()
            if existing:
                return
            conn.execute(schema_migrations.insert().values(name="runtime_db_v1", applied_at=_now()))

    def _decode_thread_row(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "thread_id": str(row["thread_id"]),
            "workspace_id": str(row["workspace_id"]),
            "session_id": str(row["session_id"]),
            "title": str(row["title"]),
            "current_mode": str(row["current_mode"]),
            "status": str(row["status"]),
            "active_run_id": str(row["active_run_id"] or ""),
            "active_mission_id": str(row["active_mission_id"] or ""),
            "created_at": float(row["created_at"] or 0.0),
            "updated_at": float(row["updated_at"] or 0.0),
            "metadata": _json_loads(row["metadata_json"], {}),
        }

    def _decode_turn_row(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "turn_id": str(row["turn_id"]),
            "role": str(row["role"]),
            "content": str(row["content"] or ""),
            "created_at": float(row["created_at"] or 0.0),
            "mode": str(row["mode"] or "cowork"),
            "status": str(row["status"] or "completed"),
            "mission_id": str(row["mission_id"] or ""),
            "run_id": str(row["run_id"] or ""),
            "metadata": _json_loads(row["metadata_json"], {}),
        }

    def _decode_approval_row(self, row: dict[str, Any]) -> dict[str, Any]:
        request_id = str(row["request_id"])
        payload = self.codec.loads(row["payload_encrypted"], context=f"approval:{request_id}:payload", default={})
        return {
            "request_id": request_id,
            "workspace_id": str(row["workspace_id"] or "local-workspace"),
            "session_id": str(row["session_id"] or ""),
            "run_id": str(row["run_id"] or ""),
            "action_type": str(row["action_type"] or ""),
            "payload": payload if isinstance(payload, dict) else {},
            "risk_level": str(row["risk_level"] or "write_safe"),
            "reason": str(row["reason"] or ""),
            "status": str(row["status"] or "pending"),
            "resolver_id": str(row["resolver_id"] or ""),
            "resolution_note": str(row["resolution_note"] or ""),
            "created_at": float(row["created_at"] or 0.0),
            "resolved_at": float(row["resolved_at"] or 0.0),
        }

    def _decode_billing_row(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "workspace_id": str(row["workspace_id"]),
            "plan_id": str(row["plan_id"] or "free"),
            "status": str(row["status"] or "inactive"),
            "billing_customer": str(row["billing_customer"] or ""),
            "stripe_customer_id": str(row["stripe_customer_id"] or ""),
            "stripe_subscription_id": str(row["stripe_subscription_id"] or ""),
            "current_period_end": float(row["current_period_end"] or 0.0),
            "seats": max(1, int(row["seats"] or 1)),
            "checkout_url": str(row["checkout_url"] or ""),
            "portal_url": str(row["portal_url"] or ""),
            "updated_at": float(row["updated_at"] or 0.0),
            "metadata": _json_loads(row["metadata_json"], {}),
        }

    def _decode_usage_row(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "usage_id": str(row["usage_id"]),
            "workspace_id": str(row["workspace_id"]),
            "metric": str(row["metric"] or "unknown"),
            "amount": int(row["amount"] or 0),
            "created_at": float(row["created_at"] or 0.0),
            "metadata": _json_loads(row["metadata_json"], {}),
        }

    def _decode_run_row(self, row: dict[str, Any]) -> dict[str, Any]:
        run_id = str(row["run_id"])
        error_value = self.codec.loads(row["error_encrypted"], context=f"run_index:{run_id}:error", default="")
        return {
            "run_id": run_id,
            "session_id": str(row["session_id"] or ""),
            "workspace_id": str(row["workspace_id"] or "local-workspace"),
            "status": str(row["status"] or "unknown"),
            "workflow_state": str(row["workflow_state"] or ""),
            "task_type": str(row["task_type"] or ""),
            "intent": str(row["intent"] or ""),
            "artifact_path": str(row["artifact_path"] or ""),
            "review_report": _json_loads(row["review_report_json"], {}),
            "metadata": _json_loads(row["metadata_json"], {}),
            "error": error_value if isinstance(error_value, str) else "",
            "started_at": float(row["started_at"] or 0.0),
            "completed_at": float(row["completed_at"] or 0.0),
            "updated_at": float(row["updated_at"] or 0.0),
        }

    @staticmethod
    def _decode_artifact_row(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "artifact_id": str(row["artifact_id"]),
            "run_id": str(row["run_id"]),
            "label": str(row["label"] or "artifact"),
            "path": str(row["path"] or ""),
            "kind": str(row["kind"] or "artifact"),
            "sha256": str(row["sha256"] or ""),
            "created_at": float(row["created_at"] or 0.0),
            "metadata": _json_loads(row["metadata_json"], {}),
        }

    @staticmethod
    def _decode_checkpoint_row(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "checkpoint_id": str(row["checkpoint_id"]),
            "run_id": str(row["run_id"]),
            "step_id": str(row["step_id"] or ""),
            "sequence_number": int(row["sequence_number"] or 0),
            "workflow_state": str(row["workflow_state"] or ""),
            "summary": _json_loads(row["summary_json"], {}),
            "created_at": float(row["created_at"] or 0.0),
        }

    @staticmethod
    def _decode_outbox_row(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "event_id": str(row["event_id"]),
            "workspace_id": str(row["workspace_id"] or "local-workspace"),
            "aggregate_type": str(row["aggregate_type"] or "unknown"),
            "aggregate_id": str(row["aggregate_id"] or ""),
            "event_type": str(row["event_type"] or "unknown"),
            "payload": _json_loads(row["payload_json"], {}),
            "sync_state": str(row["sync_state"] or "pending"),
            "delivery_attempts": int(row["delivery_attempts"] or 0),
            "last_error": str(row["last_error"] or ""),
            "created_at": float(row["created_at"] or 0.0),
            "updated_at": float(row["updated_at"] or 0.0),
        }


_runtime_database: RuntimeDatabase | None = None
_runtime_database_key: str = ""


def get_runtime_database(db_path: Path | None = None) -> RuntimeDatabase:
    global _runtime_database, _runtime_database_key
    resolved = str(Path(db_path or resolve_runtime_db_path()).expanduser().resolve())
    if _runtime_database is None or _runtime_database_key != resolved:
        _runtime_database = RuntimeDatabase(Path(resolved))
        _runtime_database_key = resolved
    return _runtime_database


def reset_runtime_database() -> None:
    global _runtime_database, _runtime_database_key
    _runtime_database = None
    _runtime_database_key = ""


__all__ = [
    "ApprovalRepository",
    "BillingRepository",
    "OutboxRepository",
    "RunIndexRepository",
    "RuntimeDatabase",
    "ThreadRepository",
    "WorkspaceSyncAdapter",
    "get_runtime_database",
    "reset_runtime_database",
]
