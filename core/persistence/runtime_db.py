from __future__ import annotations

import json
import os
import secrets
import time
import uuid
import hmac
import hashlib
import re
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
    or_,
    select,
)
from sqlalchemy.engine import Connection, Engine

from core.observability.logger import get_structured_logger
from core.data_governance import (
    ConsentPolicy,
    DataClassification,
    DatasetEntry,
    PrivacyDecision,
    RetentionPolicy,
    WorkspaceDataPolicy,
    build_dataset_entry,
    build_privacy_decision,
    build_workspace_data_policy,
)
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

usage_events_table = Table(
    "usage_events",
    LOCAL_METADATA,
    Column("event_id", String(96), primary_key=True),
    Column("workspace_id", String(128), ForeignKey("billing_workspaces.workspace_id", ondelete="CASCADE"), nullable=False),
    Column("actor_id", String(128), nullable=False, default=""),
    Column("session_id", String(128), nullable=False, default=""),
    Column("run_id", String(128), nullable=False, default=""),
    Column("usage_id", String(96), nullable=False, default=""),
    Column("metric", String(64), nullable=False),
    Column("event_type", String(64), nullable=False, default="usage"),
    Column("status", String(64), nullable=False, default="recorded"),
    Column("reference_id", String(128), nullable=False, default=""),
    Column("provider", String(64), nullable=False, default=""),
    Column("model_name", String(128), nullable=False, default=""),
    Column("priority", String(32), nullable=False, default="normal"),
    Column("input_tokens", Integer, nullable=False, default=0),
    Column("output_tokens", Integer, nullable=False, default=0),
    Column("reasoning_tokens", Integer, nullable=False, default=0),
    Column("tool_calls", Integer, nullable=False, default=0),
    Column("memory_ops", Integer, nullable=False, default=0),
    Column("prompt_length", Integer, nullable=False, default=0),
    Column("estimated_credits", Integer, nullable=False, default=0),
    Column("actual_credits", Integer, nullable=False, default=0),
    Column("bucket", String(32), nullable=False, default=""),
    Column("metadata_json", Text, nullable=False, default="{}"),
    Column("created_at", Float, nullable=False, default=_now),
)
Index("ix_usage_events_workspace_created", usage_events_table.c.workspace_id, usage_events_table.c.created_at)
Index("ix_usage_events_workspace_actor_created", usage_events_table.c.workspace_id, usage_events_table.c.actor_id, usage_events_table.c.created_at)
Index("ix_usage_events_workspace_metric_created", usage_events_table.c.workspace_id, usage_events_table.c.metric, usage_events_table.c.created_at)

rate_limit_buckets_table = Table(
    "rate_limit_buckets",
    LOCAL_METADATA,
    Column("bucket_id", String(96), primary_key=True),
    Column("workspace_id", String(128), ForeignKey("billing_workspaces.workspace_id", ondelete="CASCADE"), nullable=False),
    Column("actor_id", String(128), nullable=False, default=""),
    Column("metric", String(64), nullable=False, default=""),
    Column("bucket_type", String(64), nullable=False),
    Column("bucket_key", String(96), nullable=False),
    Column("request_count", Integer, nullable=False, default=0),
    Column("credit_spend", Integer, nullable=False, default=0),
    Column("hard_cap", Integer, nullable=False, default=0),
    Column("soft_cap", Integer, nullable=False, default=0),
    Column("status", String(64), nullable=False, default="open"),
    Column("last_allowed_at", Float, nullable=False, default=0.0),
    Column("last_blocked_at", Float, nullable=False, default=0.0),
    Column("last_reason", String(128), nullable=False, default=""),
    Column("metadata_json", Text, nullable=False, default="{}"),
    Column("created_at", Float, nullable=False, default=_now),
    Column("updated_at", Float, nullable=False, default=_now),
)
Index("ix_rate_limit_buckets_workspace_bucket", rate_limit_buckets_table.c.workspace_id, rate_limit_buckets_table.c.bucket_type, rate_limit_buckets_table.c.bucket_key)
Index("ix_rate_limit_buckets_workspace_actor", rate_limit_buckets_table.c.workspace_id, rate_limit_buckets_table.c.actor_id, rate_limit_buckets_table.c.updated_at)

billing_events_table = Table(
    "billing_events",
    LOCAL_METADATA,
    Column("event_id", String(96), primary_key=True),
    Column("workspace_id", String(128), ForeignKey("billing_workspaces.workspace_id", ondelete="CASCADE"), nullable=False),
    Column("provider", String(64), nullable=False, default="internal"),
    Column("event_type", String(128), nullable=False),
    Column("status", String(64), nullable=False, default="pending"),
    Column("reference_id", String(128), nullable=False, default=""),
    Column("payload_json", Text, nullable=False, default="{}"),
    Column("created_at", Float, nullable=False, default=_now),
)
Index("ix_billing_events_workspace_created", billing_events_table.c.workspace_id, billing_events_table.c.created_at)

billing_checkout_sessions_table = Table(
    "billing_checkout_sessions",
    LOCAL_METADATA,
    Column("reference_id", String(128), primary_key=True),
    Column("workspace_id", String(128), ForeignKey("billing_workspaces.workspace_id", ondelete="CASCADE"), nullable=False),
    Column("mode", String(64), nullable=False, default="subscription"),
    Column("catalog_id", String(128), nullable=False, default=""),
    Column("provider", String(64), nullable=False, default="iyzico"),
    Column("provider_token", String(256), nullable=False, default=""),
    Column("provider_payment_id", String(128), nullable=False, default=""),
    Column("subscription_reference_code", String(128), nullable=False, default=""),
    Column("status", String(64), nullable=False, default="pending"),
    Column("payment_page_url", Text, nullable=False, default=""),
    Column("callback_url", Text, nullable=False, default=""),
    Column("raw_last_payload_encrypted", Text, nullable=False, default=""),
    Column("created_at", Float, nullable=False, default=_now),
    Column("updated_at", Float, nullable=False, default=_now),
    Column("completed_at", Float, nullable=False, default=0.0),
)
Index("ix_billing_checkout_workspace_updated", billing_checkout_sessions_table.c.workspace_id, billing_checkout_sessions_table.c.updated_at)
Index("ix_billing_checkout_provider_token", billing_checkout_sessions_table.c.provider_token)
Index("ix_billing_checkout_subscription_ref", billing_checkout_sessions_table.c.subscription_reference_code)

workspace_billing_profiles_table = Table(
    "workspace_billing_profiles",
    LOCAL_METADATA,
    Column("workspace_id", String(128), ForeignKey("billing_workspaces.workspace_id", ondelete="CASCADE"), primary_key=True),
    Column("profile_encrypted", Text, nullable=False, default=""),
    Column("created_at", Float, nullable=False, default=_now),
    Column("updated_at", Float, nullable=False, default=_now),
)
Index("ix_workspace_billing_profiles_updated", workspace_billing_profiles_table.c.updated_at)

credit_ledger_table = Table(
    "credit_ledger",
    LOCAL_METADATA,
    Column("entry_id", String(96), primary_key=True),
    Column("workspace_id", String(128), ForeignKey("billing_workspaces.workspace_id", ondelete="CASCADE"), nullable=False),
    Column("bucket", String(32), nullable=False, default="purchased"),
    Column("entry_type", String(64), nullable=False, default="adjustment"),
    Column("delta_credits", Integer, nullable=False, default=0),
    Column("balance_after", Integer, nullable=False, default=0),
    Column("reference_id", String(128), nullable=False, default=""),
    Column("metadata_json", Text, nullable=False, default="{}"),
    Column("created_at", Float, nullable=False, default=_now),
)
Index("ix_credit_ledger_workspace_created", credit_ledger_table.c.workspace_id, credit_ledger_table.c.created_at)

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

local_connector_accounts_table = Table(
    "connector_accounts",
    LOCAL_METADATA,
    Column("account_id", String(128), primary_key=True),
    Column("workspace_id", String(128), nullable=False, default="local-workspace"),
    Column("provider", String(64), nullable=False, default=""),
    Column("connector_name", String(64), nullable=False, default=""),
    Column("account_alias", String(128), nullable=False, default="default"),
    Column("display_name", String(256), nullable=False, default=""),
    Column("email", String(256), nullable=False, default=""),
    Column("status", String(64), nullable=False, default="needs_input"),
    Column("auth_strategy", String(64), nullable=False, default="oauth"),
    Column("auth_url", Text, nullable=False, default=""),
    Column("redirect_uri", Text, nullable=False, default=""),
    Column("scopes_json", Text, nullable=False, default="[]"),
    Column("metadata_json", Text, nullable=False, default="{}"),
    Column("updated_at", Float, nullable=False, default=_now),
)
Index("ix_local_connector_accounts_workspace_updated", local_connector_accounts_table.c.workspace_id, local_connector_accounts_table.c.updated_at)
Index("ix_local_connector_accounts_provider_alias", local_connector_accounts_table.c.provider, local_connector_accounts_table.c.account_alias)

local_connector_health_table = Table(
    "connector_health",
    LOCAL_METADATA,
    Column("health_id", String(128), primary_key=True),
    Column("account_id", String(128), nullable=False),
    Column("workspace_id", String(128), nullable=False, default="local-workspace"),
    Column("status", String(64), nullable=False, default="healthy"),
    Column("payload_json", Text, nullable=False, default="{}"),
    Column("updated_at", Float, nullable=False, default=_now),
)
Index("ix_local_connector_health_workspace_updated", local_connector_health_table.c.workspace_id, local_connector_health_table.c.updated_at)

local_connector_action_traces_table = Table(
    "connector_action_traces",
    LOCAL_METADATA,
    Column("trace_id", String(128), primary_key=True),
    Column("workspace_id", String(128), nullable=False, default="local-workspace"),
    Column("connector_account_id", String(128), nullable=False, default=""),
    Column("provider", String(64), nullable=False, default=""),
    Column("connector_name", String(64), nullable=False, default=""),
    Column("integration_type", String(64), nullable=False, default=""),
    Column("event_type", String(128), nullable=False, default="connector"),
    Column("status", String(64), nullable=False, default=""),
    Column("success", Boolean, nullable=False, default=False),
    Column("latency_ms", Float, nullable=False, default=0.0),
    Column("payload_json", Text, nullable=False, default="{}"),
    Column("created_at", Float, nullable=False, default=_now),
)
Index("ix_local_connector_traces_workspace_created", local_connector_action_traces_table.c.workspace_id, local_connector_action_traces_table.c.created_at)

user_preference_profiles_table = Table(
    "user_preference_profiles",
    LOCAL_METADATA,
    Column("profile_id", String(128), primary_key=True),
    Column("workspace_id", String(128), nullable=False, default="local-workspace"),
    Column("user_id", String(128), nullable=False, default="local-user"),
    Column("explanation_style", String(64), nullable=False, default="concise"),
    Column("approval_sensitivity_hint", String(64), nullable=False, default="balanced"),
    Column("preferred_route", String(64), nullable=False, default="balanced"),
    Column("preferred_model", String(128), nullable=False, default=""),
    Column("task_templates_json", Text, nullable=False, default="[]"),
    Column("metadata_json", Text, nullable=False, default="{}"),
    Column("updated_at", Float, nullable=False, default=_now),
)
Index("ix_user_preference_profiles_workspace_updated", user_preference_profiles_table.c.workspace_id, user_preference_profiles_table.c.updated_at)
Index("ix_user_preference_profiles_workspace_user", user_preference_profiles_table.c.workspace_id, user_preference_profiles_table.c.user_id)

preference_update_queue_table = Table(
    "preference_update_queue",
    LOCAL_METADATA,
    Column("queue_id", String(128), primary_key=True),
    Column("workspace_id", String(128), nullable=False, default="local-workspace"),
    Column("user_id", String(128), nullable=False, default="local-user"),
    Column("conversation_session_id", String(128), nullable=False, default=""),
    Column("preference_key", String(128), nullable=False, default=""),
    Column("proposed_value_json", Text, nullable=False, default="{}"),
    Column("rationale", Text, nullable=False, default=""),
    Column("confidence", Float, nullable=False, default=0.0),
    Column("status", String(32), nullable=False, default="draft"),
    Column("metadata_json", Text, nullable=False, default="{}"),
    Column("created_at", Float, nullable=False, default=_now),
    Column("updated_at", Float, nullable=False, default=_now),
    Column("reviewed_at", Float, nullable=False, default=0.0),
    Column("applied_at", Float, nullable=False, default=0.0),
)
Index("ix_preference_update_queue_workspace_user_status", preference_update_queue_table.c.workspace_id, preference_update_queue_table.c.user_id, preference_update_queue_table.c.status)
Index("ix_preference_update_queue_updated", preference_update_queue_table.c.updated_at)

skill_draft_queue_table = Table(
    "skill_draft_queue",
    LOCAL_METADATA,
    Column("draft_id", String(128), primary_key=True),
    Column("workspace_id", String(128), nullable=False, default="local-workspace"),
    Column("user_id", String(128), nullable=False, default="local-user"),
    Column("conversation_session_id", String(128), nullable=False, default=""),
    Column("name_hint", String(128), nullable=False, default="workflow_draft"),
    Column("description", Text, nullable=False, default=""),
    Column("trigger_text", Text, nullable=False, default=""),
    Column("source_action", String(128), nullable=False, default=""),
    Column("tool_names_json", Text, nullable=False, default="[]"),
    Column("confidence", Float, nullable=False, default=0.0),
    Column("status", String(32), nullable=False, default="draft"),
    Column("metadata_json", Text, nullable=False, default="{}"),
    Column("created_at", Float, nullable=False, default=_now),
    Column("updated_at", Float, nullable=False, default=_now),
    Column("reviewed_at", Float, nullable=False, default=0.0),
)
Index("ix_skill_draft_queue_workspace_user_status", skill_draft_queue_table.c.workspace_id, skill_draft_queue_table.c.user_id, skill_draft_queue_table.c.status)
Index("ix_skill_draft_queue_updated", skill_draft_queue_table.c.updated_at)

routine_draft_queue_table = Table(
    "routine_draft_queue",
    LOCAL_METADATA,
    Column("draft_id", String(128), primary_key=True),
    Column("workspace_id", String(128), nullable=False, default="local-workspace"),
    Column("user_id", String(128), nullable=False, default="local-user"),
    Column("conversation_session_id", String(128), nullable=False, default=""),
    Column("name_hint", String(128), nullable=False, default="routine_draft"),
    Column("description", Text, nullable=False, default=""),
    Column("trigger_text", Text, nullable=False, default=""),
    Column("schedule_expression", String(128), nullable=False, default=""),
    Column("delivery_channel", String(64), nullable=False, default=""),
    Column("source_action", String(128), nullable=False, default=""),
    Column("confidence", Float, nullable=False, default=0.0),
    Column("status", String(32), nullable=False, default="draft"),
    Column("metadata_json", Text, nullable=False, default="{}"),
    Column("created_at", Float, nullable=False, default=_now),
    Column("updated_at", Float, nullable=False, default=_now),
    Column("reviewed_at", Float, nullable=False, default=0.0),
)
Index("ix_routine_draft_queue_workspace_user_status", routine_draft_queue_table.c.workspace_id, routine_draft_queue_table.c.user_id, routine_draft_queue_table.c.status)
Index("ix_routine_draft_queue_updated", routine_draft_queue_table.c.updated_at)

channel_identity_links_table = Table(
    "channel_identity_links",
    LOCAL_METADATA,
    Column("link_id", String(192), primary_key=True),
    Column("workspace_id", String(128), nullable=False, default="local-workspace"),
    Column("channel", String(64), nullable=False, default="cli"),
    Column("external_user_id", String(256), nullable=False, default=""),
    Column("actor_id", String(128), nullable=False, default="local-user"),
    Column("display_name", String(256), nullable=False, default=""),
    Column("metadata_json", Text, nullable=False, default="{}"),
    Column("created_at", Float, nullable=False, default=_now),
    Column("updated_at", Float, nullable=False, default=_now),
    Column("last_seen_at", Float, nullable=False, default=0.0),
)
Index("ix_channel_identity_workspace_channel_user", channel_identity_links_table.c.workspace_id, channel_identity_links_table.c.channel, channel_identity_links_table.c.external_user_id)
Index("ix_channel_identity_workspace_actor", channel_identity_links_table.c.workspace_id, channel_identity_links_table.c.actor_id)

operational_feedback_table = Table(
    "operational_feedback",
    LOCAL_METADATA,
    Column("feedback_id", String(128), primary_key=True),
    Column("workspace_id", String(128), nullable=False, default="local-workspace"),
    Column("user_id", String(128), nullable=False, default="local-user"),
    Column("category", String(64), nullable=False, default="runtime"),
    Column("entity_id", String(128), nullable=False, default=""),
    Column("outcome", String(32), nullable=False, default="neutral"),
    Column("reward", Float, nullable=False, default=0.0),
    Column("latency_ms", Float, nullable=False, default=0.0),
    Column("recovery_count", Integer, nullable=False, default=0),
    Column("payload_json", Text, nullable=False, default="{}"),
    Column("created_at", Float, nullable=False, default=_now),
)
Index("ix_operational_feedback_workspace_created", operational_feedback_table.c.workspace_id, operational_feedback_table.c.created_at)
Index("ix_operational_feedback_entity_created", operational_feedback_table.c.entity_id, operational_feedback_table.c.created_at)

global_tool_reliability_table = Table(
    "global_tool_reliability",
    LOCAL_METADATA,
    Column("stat_id", String(160), primary_key=True),
    Column("scope", String(64), nullable=False, default="global"),
    Column("tool_name", String(128), nullable=False),
    Column("success_count", Integer, nullable=False, default=0),
    Column("failure_count", Integer, nullable=False, default=0),
    Column("sample_count", Integer, nullable=False, default=0),
    Column("avg_reward", Float, nullable=False, default=0.0),
    Column("avg_latency_ms", Float, nullable=False, default=0.0),
    Column("metadata_json", Text, nullable=False, default="{}"),
    Column("updated_at", Float, nullable=False, default=_now),
)
Index("ix_global_tool_reliability_scope_updated", global_tool_reliability_table.c.scope, global_tool_reliability_table.c.updated_at)

workspace_data_policies_table = Table(
    "workspace_data_policies",
    LOCAL_METADATA,
    Column("workspace_id", String(128), primary_key=True),
    Column("allow_personal_data_learning", Boolean, nullable=False, default=False),
    Column("allow_workspace_data_learning", Boolean, nullable=False, default=True),
    Column("allow_operational_data_learning", Boolean, nullable=False, default=True),
    Column("allow_public_data_learning", Boolean, nullable=False, default=True),
    Column("allow_secret_data_learning", Boolean, nullable=False, default=False),
    Column("allow_global_aggregation", Boolean, nullable=False, default=True),
    Column("redact_personal_data", Boolean, nullable=False, default=True),
    Column("redact_secret_data", Boolean, nullable=False, default=True),
    Column("learning_scope", String(64), nullable=False, default="workspace"),
    Column("retention_policy_json", Text, nullable=False, default="{}"),
    Column("metadata_json", Text, nullable=False, default="{}"),
    Column("updated_at", Float, nullable=False, default=_now),
)
Index("ix_workspace_data_policies_updated", workspace_data_policies_table.c.updated_at)

consent_records_table = Table(
    "consent_records",
    LOCAL_METADATA,
    Column("consent_id", String(128), primary_key=True),
    Column("workspace_id", String(128), nullable=False, default="local-workspace"),
    Column("user_id", String(128), nullable=False, default="local-user"),
    Column("scope", String(128), nullable=False, default="workspace"),
    Column("granted", Boolean, nullable=False, default=False),
    Column("source", String(128), nullable=False, default="runtime"),
    Column("expires_at", Float, nullable=False, default=0.0),
    Column("metadata_json", Text, nullable=False, default="{}"),
    Column("created_at", Float, nullable=False, default=_now),
    Column("updated_at", Float, nullable=False, default=_now),
)
Index("ix_consent_records_workspace_user", consent_records_table.c.workspace_id, consent_records_table.c.user_id)
Index("ix_consent_records_workspace_created", consent_records_table.c.workspace_id, consent_records_table.c.created_at)

privacy_decisions_table = Table(
    "privacy_decisions",
    LOCAL_METADATA,
    Column("decision_id", String(128), primary_key=True),
    Column("workspace_id", String(128), nullable=False, default="local-workspace"),
    Column("user_id", String(128), nullable=False, default="local-user"),
    Column("source_kind", String(128), nullable=False, default="runtime"),
    Column("classification", String(32), nullable=False, default="operational"),
    Column("learning_scope", String(64), nullable=False, default="workspace"),
    Column("shared_learning_eligible", Boolean, nullable=False, default=True),
    Column("redacted", Boolean, nullable=False, default=True),
    Column("reason", Text, nullable=False, default=""),
    Column("payload_json", Text, nullable=False, default="{}"),
    Column("text", Text, nullable=False, default=""),
    Column("retention_policy_json", Text, nullable=False, default="{}"),
    Column("consent_policy_json", Text, nullable=False, default="{}"),
    Column("metadata_json", Text, nullable=False, default="{}"),
    Column("created_at", Float, nullable=False, default=_now),
)
Index("ix_privacy_decisions_workspace_created", privacy_decisions_table.c.workspace_id, privacy_decisions_table.c.created_at)
Index("ix_privacy_decisions_user_created", privacy_decisions_table.c.user_id, privacy_decisions_table.c.created_at)

dataset_entries_table = Table(
    "dataset_entries",
    LOCAL_METADATA,
    Column("entry_id", String(128), primary_key=True),
    Column("workspace_id", String(128), nullable=False, default="local-workspace"),
    Column("user_id", String(128), nullable=False, default="local-user"),
    Column("source_kind", String(128), nullable=False, default="runtime"),
    Column("source_id", String(128), nullable=False, default=""),
    Column("classification", String(32), nullable=False, default="operational"),
    Column("learning_scope", String(64), nullable=False, default="workspace"),
    Column("shared_learning_eligible", Boolean, nullable=False, default=True),
    Column("redacted", Boolean, nullable=False, default=True),
    Column("text", Text, nullable=False, default=""),
    Column("payload_json", Text, nullable=False, default="{}"),
    Column("retention_policy_json", Text, nullable=False, default="{}"),
    Column("consent_policy_json", Text, nullable=False, default="{}"),
    Column("metadata_json", Text, nullable=False, default="{}"),
    Column("created_at", Float, nullable=False, default=_now),
)
Index("ix_dataset_entries_workspace_created", dataset_entries_table.c.workspace_id, dataset_entries_table.c.created_at)
Index("ix_dataset_entries_user_created", dataset_entries_table.c.user_id, dataset_entries_table.c.created_at)
Index("ix_dataset_entries_workspace_classification", dataset_entries_table.c.workspace_id, dataset_entries_table.c.classification)

local_users_table = Table(
    "local_users",
    LOCAL_METADATA,
    Column("user_id", String(128), primary_key=True),
    Column("workspace_id", String(128), nullable=False, default="local-workspace"),
    Column("email", String(256), nullable=False),
    Column("display_name", String(256), nullable=False, default=""),
    Column("password_hash", String(256), nullable=False, default=""),
    Column("password_salt", String(128), nullable=False, default=""),
    Column("status", String(64), nullable=False, default="active"),
    Column("metadata_json", Text, nullable=False, default="{}"),
    Column("created_at", Float, nullable=False, default=_now),
    Column("updated_at", Float, nullable=False, default=_now),
)
Index("ix_local_users_workspace_updated", local_users_table.c.workspace_id, local_users_table.c.updated_at)
Index("ix_local_users_workspace_email", local_users_table.c.workspace_id, local_users_table.c.email, unique=True)

local_user_sessions_table = Table(
    "local_user_sessions",
    LOCAL_METADATA,
    Column("session_id", String(128), primary_key=True),
    Column("workspace_id", String(128), nullable=False, default="local-workspace"),
    Column("user_id", String(128), nullable=False),
    Column("session_token_hash", String(128), nullable=False, unique=True),
    Column("status", String(64), nullable=False, default="active"),
    Column("expires_at", Float, nullable=False, default=_now),
    Column("last_seen_at", Float, nullable=False, default=_now),
    Column("metadata_json", Text, nullable=False, default="{}"),
    Column("created_at", Float, nullable=False, default=_now),
    Column("updated_at", Float, nullable=False, default=_now),
)
Index("ix_local_user_sessions_workspace_updated", local_user_sessions_table.c.workspace_id, local_user_sessions_table.c.updated_at)
Index("ix_local_user_sessions_user_updated", local_user_sessions_table.c.user_id, local_user_sessions_table.c.updated_at)

conversation_sessions_table = Table(
    "conversation_sessions",
    LOCAL_METADATA,
    Column("conversation_session_id", String(128), primary_key=True),
    Column("workspace_id", String(128), nullable=False, default="local-workspace"),
    Column("actor_id", String(128), nullable=False, default="local-user"),
    Column("device_id", String(128), nullable=False, default="local-device"),
    Column("channel", String(64), nullable=False, default="cli"),
    Column("auth_session_id", String(128), nullable=False, default=""),
    Column("client_session_id", String(128), nullable=False, default=""),
    Column("parent_session_id", String(128), nullable=False, default=""),
    Column("status", String(32), nullable=False, default="active"),
    Column("title", String(256), nullable=False, default=""),
    Column("summary_text", Text, nullable=False, default=""),
    Column("message_count", Integer, nullable=False, default=0),
    Column("token_input_total", Integer, nullable=False, default=0),
    Column("token_output_total", Integer, nullable=False, default=0),
    Column("metadata_json", Text, nullable=False, default="{}"),
    Column("created_at", Float, nullable=False, default=_now),
    Column("updated_at", Float, nullable=False, default=_now),
    Column("closed_at", Float, nullable=False, default=0.0),
)
Index("ix_conversation_sessions_workspace_actor_updated", conversation_sessions_table.c.workspace_id, conversation_sessions_table.c.actor_id, conversation_sessions_table.c.updated_at)
Index("ix_conversation_sessions_auth_session", conversation_sessions_table.c.auth_session_id)
Index("ix_conversation_sessions_client_session", conversation_sessions_table.c.client_session_id)

conversation_messages_table = Table(
    "conversation_messages",
    LOCAL_METADATA,
    Column("message_id", String(128), primary_key=True),
    Column("conversation_session_id", String(128), ForeignKey("conversation_sessions.conversation_session_id", ondelete="CASCADE"), nullable=False),
    Column("workspace_id", String(128), nullable=False, default="local-workspace"),
    Column("actor_id", String(128), nullable=False, default="local-user"),
    Column("role", String(32), nullable=False, default="user"),
    Column("content", Text, nullable=False, default=""),
    Column("message_index", Integer, nullable=False, default=0),
    Column("run_id", String(128), nullable=False, default=""),
    Column("action", String(128), nullable=False, default=""),
    Column("success", Boolean, nullable=False, default=False),
    Column("metadata_json", Text, nullable=False, default="{}"),
    Column("created_at", Float, nullable=False, default=_now),
)
Index("ix_conversation_messages_session_index", conversation_messages_table.c.conversation_session_id, conversation_messages_table.c.message_index)
Index("ix_conversation_messages_workspace_actor_created", conversation_messages_table.c.workspace_id, conversation_messages_table.c.actor_id, conversation_messages_table.c.created_at)

conversation_message_terms_table = Table(
    "conversation_message_terms",
    LOCAL_METADATA,
    Column("term_entry_id", String(128), primary_key=True),
    Column("message_id", String(128), ForeignKey("conversation_messages.message_id", ondelete="CASCADE"), nullable=False),
    Column("conversation_session_id", String(128), ForeignKey("conversation_sessions.conversation_session_id", ondelete="CASCADE"), nullable=False),
    Column("workspace_id", String(128), nullable=False, default="local-workspace"),
    Column("actor_id", String(128), nullable=False, default="local-user"),
    Column("role", String(32), nullable=False, default="user"),
    Column("term", String(128), nullable=False, default=""),
    Column("created_at", Float, nullable=False, default=_now),
)
Index("ix_conversation_terms_workspace_actor_term", conversation_message_terms_table.c.workspace_id, conversation_message_terms_table.c.actor_id, conversation_message_terms_table.c.term)
Index("ix_conversation_terms_session_term", conversation_message_terms_table.c.conversation_session_id, conversation_message_terms_table.c.term)

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

workspace_invites_table = Table(
    "workspace_invites",
    WORKSPACE_METADATA,
    Column("invite_id", String(128), primary_key=True),
    Column("workspace_id", String(128), nullable=False),
    Column("email", String(256), nullable=False),
    Column("role", String(64), nullable=False, default="member"),
    Column("status", String(64), nullable=False, default="pending"),
    Column("invited_by", String(128), nullable=False, default=""),
    Column("metadata_json", Text, nullable=False, default="{}"),
    Column("expires_at", Float, nullable=False, default=0.0),
    Column("updated_at", Float, nullable=False, default=_now),
)
Index("ix_workspace_invites_workspace_updated", workspace_invites_table.c.workspace_id, workspace_invites_table.c.updated_at)

workspace_seat_assignments_table = Table(
    "workspace_seat_assignments",
    WORKSPACE_METADATA,
    Column("assignment_id", String(128), primary_key=True),
    Column("workspace_id", String(128), nullable=False),
    Column("actor_id", String(128), nullable=False),
    Column("assigned_by", String(128), nullable=False, default=""),
    Column("status", String(64), nullable=False, default="active"),
    Column("created_at", Float, nullable=False, default=_now),
    Column("updated_at", Float, nullable=False, default=_now),
)
Index("ix_workspace_seat_assignments_workspace_actor", workspace_seat_assignments_table.c.workspace_id, workspace_seat_assignments_table.c.actor_id)

workspace_inbox_events_table = Table(
    "workspace_inbox_events",
    WORKSPACE_METADATA,
    Column("event_id", String(128), primary_key=True),
    Column("workspace_id", String(128), nullable=False),
    Column("source_type", String(64), nullable=False, default="manual"),
    Column("source_id", String(128), nullable=False, default=""),
    Column("title", String(256), nullable=False, default=""),
    Column("content_encrypted", Text, nullable=False, default=""),
    Column("status", String(64), nullable=False, default="received"),
    Column("summary_json", Text, nullable=False, default="{}"),
    Column("metadata_json", Text, nullable=False, default="{}"),
    Column("created_at", Float, nullable=False, default=_now),
    Column("updated_at", Float, nullable=False, default=_now),
)
Index("ix_workspace_inbox_events_workspace_updated", workspace_inbox_events_table.c.workspace_id, workspace_inbox_events_table.c.updated_at)

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
    _MAX_ATTEMPTS = 5
    _MAX_BACKOFF_SECONDS = 60.0

    def __init__(self, db: "RuntimeDatabase") -> None:
        self._db = db

    @classmethod
    def retry_delay_seconds(cls, attempts: int) -> float:
        normalized = max(0, int(attempts or 0))
        if normalized <= 0:
            return 0.0
        return min(float(2 ** min(normalized - 1, 5)), cls._MAX_BACKOFF_SECONDS)

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
        now = _now()
        with self._db.local_engine.begin() as conn:
            rows = conn.execute(
                select(outbox_events_table)
                .where(outbox_events_table.c.sync_state == "pending")
                .order_by(outbox_events_table.c.created_at.asc())
                .limit(max(1, int(limit or 100)) * 4)
            ).mappings().all()
        deliverable: list[dict[str, Any]] = []
        for row in rows:
            attempts = int(row["delivery_attempts"] or 0)
            updated_at = float(row["updated_at"] or row["created_at"] or 0.0)
            next_retry_at = updated_at + self.retry_delay_seconds(attempts)
            if attempts > 0 and now < next_retry_at:
                continue
            decoded = self._db._decode_outbox_row(row)
            decoded["next_retry_at"] = next_retry_at
            deliverable.append(decoded)
            if len(deliverable) >= max(1, int(limit or 100)):
                break
        return deliverable

    def mark_delivered(self, event_id: str) -> None:
        with self._db.local_engine.begin() as conn:
            conn.execute(
                outbox_events_table.update()
                .where(outbox_events_table.c.event_id == str(event_id))
                .values(sync_state="delivered", updated_at=_now())
            )

    def mark_retry(self, event_id: str, *, error: str) -> None:
        with self._db.local_engine.begin() as conn:
            row = conn.execute(
                select(outbox_events_table.c.delivery_attempts).where(outbox_events_table.c.event_id == str(event_id))
            ).first()
            attempts = int(row[0] or 0) + 1 if row else 1
            if attempts >= self._MAX_ATTEMPTS:
                conn.execute(
                    outbox_events_table.update()
                    .where(outbox_events_table.c.event_id == str(event_id))
                    .values(
                        sync_state="dead_letter",
                        delivery_attempts=attempts,
                        last_error=str(error or "")[:2000],
                        updated_at=_now(),
                    )
                )
                return
            conn.execute(
                outbox_events_table.update()
                .where(outbox_events_table.c.event_id == str(event_id))
                .values(
                    sync_state="pending",
                    delivery_attempts=attempts,
                    last_error=str(error or "")[:2000],
                    updated_at=_now(),
                )
            )

    def mark_dead_letter(self, event_id: str, *, error: str) -> None:
        with self._db.local_engine.begin() as conn:
            row = conn.execute(
                select(outbox_events_table.c.delivery_attempts).where(outbox_events_table.c.event_id == str(event_id))
            ).first()
            attempts = int(row[0] or 0) if row else 0
            conn.execute(
                outbox_events_table.update()
                .where(outbox_events_table.c.event_id == str(event_id))
                .values(
                    sync_state="dead_letter",
                    delivery_attempts=max(attempts, self._MAX_ATTEMPTS),
                    last_error=str(error or "")[:2000],
                    updated_at=_now(),
                )
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


class InboxRepository:
    def __init__(self, db: "RuntimeDatabase") -> None:
        self._db = db

    @staticmethod
    def _derive_title(content: str, source_type: str) -> str:
        lines = [line.strip() for line in str(content or "").splitlines() if line.strip()]
        first = lines[0] if lines else str(content or "").strip()
        compact = re.sub(r"\s+", " ", first).strip()
        if not compact:
            compact = f"{str(source_type or 'manual').replace('_', ' ').title()} intake"
        return compact[:120]

    def create_event(
        self,
        *,
        workspace_id: str,
        source_type: str,
        content: str,
        source_id: str = "",
        title: str = "",
        summary: dict[str, Any] | None = None,
        status: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        wid = str(workspace_id or "local-workspace").strip() or "local-workspace"
        normalized_content = str(content or "").strip()
        if not normalized_content:
            raise ValueError("content required")
        event_id = f"inbox_{uuid.uuid4().hex[:16]}"
        now = _now()
        summary_payload = dict(summary or {})
        metadata_payload = dict(metadata or {})
        values = {
            "event_id": event_id,
            "workspace_id": wid,
            "source_type": str(source_type or "manual").strip().lower() or "manual",
            "source_id": str(source_id or "").strip(),
            "title": str(title or summary_payload.get("title") or self._derive_title(normalized_content, source_type)).strip()[:256],
            "content_encrypted": self._db.codec.dumps(
                {"content": normalized_content},
                context=f"inbox:{event_id}:content",
                classification="private",
            ),
            "status": str(status or ("triaged" if summary_payload else "received")).strip().lower() or "received",
            "summary_json": _json_dumps(summary_payload),
            "metadata_json": _json_dumps(metadata_payload),
            "created_at": now,
            "updated_at": now,
        }
        with self._db.local_engine.begin() as conn:
            conn.execute(workspace_inbox_events_table.insert().values(**values))
            self._db.outbox.enqueue(
                conn,
                workspace_id=wid,
                aggregate_type="workspace_inbox_event",
                aggregate_id=event_id,
                event_type="workspace.inbox_event.created",
                payload={
                    "event_id": event_id,
                    "workspace_id": wid,
                    "source_type": values["source_type"],
                    "source_id": values["source_id"],
                    "title": values["title"],
                    "status": values["status"],
                    "content_encrypted": values["content_encrypted"],
                    "summary": summary_payload,
                    "metadata": metadata_payload,
                    "created_at": values["created_at"],
                },
            )
        return self._db._decode_workspace_inbox_event_row(values)

    def get_event(self, event_id: str) -> dict[str, Any] | None:
        eid = str(event_id or "").strip()
        if not eid:
            return None
        with self._db.local_engine.begin() as conn:
            row = conn.execute(
                select(workspace_inbox_events_table).where(workspace_inbox_events_table.c.event_id == eid)
            ).mappings().first()
        return self._db._decode_workspace_inbox_event_row(row) if row else None

    def list_events(self, workspace_id: str, *, limit: int = 20, source_type: str = "") -> list[dict[str, Any]]:
        wid = str(workspace_id or "local-workspace").strip() or "local-workspace"
        with self._db.local_engine.begin() as conn:
            stmt = select(workspace_inbox_events_table).where(workspace_inbox_events_table.c.workspace_id == wid)
            if str(source_type or "").strip():
                stmt = stmt.where(workspace_inbox_events_table.c.source_type == str(source_type or "").strip().lower())
            rows = conn.execute(
                stmt.order_by(workspace_inbox_events_table.c.updated_at.desc()).limit(max(1, int(limit or 20)))
            ).mappings().all()
        return [self._db._decode_workspace_inbox_event_row(row) for row in rows]

    def update_summary(self, event_id: str, *, summary: dict[str, Any], status: str = "triaged") -> dict[str, Any] | None:
        eid = str(event_id or "").strip()
        if not eid:
            return None
        now = _now()
        with self._db.local_engine.begin() as conn:
            row = conn.execute(
                select(workspace_inbox_events_table).where(workspace_inbox_events_table.c.event_id == eid)
            ).mappings().first()
            if row is None:
                return None
            conn.execute(
                workspace_inbox_events_table.update()
                .where(workspace_inbox_events_table.c.event_id == eid)
                .values(summary_json=_json_dumps(dict(summary or {})), status=str(status or "triaged"), updated_at=now)
            )
            self._db.outbox.enqueue(
                conn,
                workspace_id=str(row.get("workspace_id") or "local-workspace"),
                aggregate_type="workspace_inbox_event",
                aggregate_id=eid,
                event_type="workspace.inbox_event.updated",
                payload={
                    "event_id": eid,
                    "workspace_id": str(row.get("workspace_id") or "local-workspace"),
                    "source_type": str(row.get("source_type") or "manual"),
                    "source_id": str(row.get("source_id") or ""),
                    "title": str(row.get("title") or ""),
                    "status": str(status or "triaged"),
                    "content_encrypted": str(row.get("content_encrypted") or ""),
                    "summary": dict(summary or {}),
                    "metadata": _json_loads(row.get("metadata_json"), {}),
                    "created_at": float(row.get("created_at") or now),
                },
            )
            updated = dict(row)
            updated["summary_json"] = _json_dumps(dict(summary or {}))
            updated["status"] = str(status or "triaged")
            updated["updated_at"] = now
        return self._db._decode_workspace_inbox_event_row(updated)


class PermissionGrantRepository:
    def __init__(self, db: "RuntimeDatabase") -> None:
        self._db = db

    def issue_grant(
        self,
        *,
        workspace_id: str = "local-workspace",
        device_id: str = "local-device",
        scope: str,
        resource: str,
        allowed_actions: list[str],
        ttl_seconds: int = 0,
        issued_by: str = "runtime",
        revocable: bool = True,
        metadata: dict[str, Any] | None = None,
        grant_id: str = "",
    ) -> dict[str, Any]:
        now = _now()
        normalized_grant_id = str(grant_id or f"grant_{uuid.uuid4().hex[:12]}")
        expires_at = now + max(0, int(ttl_seconds or 0)) if int(ttl_seconds or 0) > 0 else 0.0
        payload = {
            "grant_id": normalized_grant_id,
            "workspace_id": str(workspace_id or "local-workspace"),
            "device_id": str(device_id or "local-device"),
            "scope": str(scope or "").strip(),
            "resource": str(resource or "").strip(),
            "allowed_actions": [str(item).strip() for item in list(allowed_actions or []) if str(item).strip()],
            "ttl_seconds": max(0, int(ttl_seconds or 0)),
            "issued_by": str(issued_by or "runtime"),
            "revocable": bool(revocable),
            "created_at": now,
            "expires_at": expires_at,
            "metadata": dict(metadata or {}),
        }
        with self._db.local_engine.begin() as conn:
            existing = conn.execute(
                select(permission_grants_table.c.grant_id).where(permission_grants_table.c.grant_id == normalized_grant_id)
            ).first()
            values = {
                "grant_id": payload["grant_id"],
                "workspace_id": payload["workspace_id"],
                "device_id": payload["device_id"],
                "scope": payload["scope"],
                "resource": payload["resource"],
                "allowed_actions_json": _json_dumps(payload["allowed_actions"]),
                "ttl_seconds": payload["ttl_seconds"],
                "issued_by": payload["issued_by"],
                "revocable": payload["revocable"],
                "created_at": payload["created_at"],
                "expires_at": payload["expires_at"],
                "metadata_json": _json_dumps(payload["metadata"]),
            }
            if existing:
                conn.execute(
                    permission_grants_table.update()
                    .where(permission_grants_table.c.grant_id == normalized_grant_id)
                    .values(**values)
                )
            else:
                conn.execute(permission_grants_table.insert().values(**values))
            self._db._insert_audit_event(
                conn,
                workspace_id=payload["workspace_id"],
                event_type="security.permission_grant.issued",
                payload={
                    "grant_id": normalized_grant_id,
                    "device_id": payload["device_id"],
                    "scope": payload["scope"],
                    "resource": payload["resource"],
                    "allowed_actions": payload["allowed_actions"],
                    "expires_at": expires_at,
                    "issued_by": payload["issued_by"],
                },
            )
            self._db.outbox.enqueue(
                conn,
                workspace_id=payload["workspace_id"],
                aggregate_type="permission_grant",
                aggregate_id=normalized_grant_id,
                event_type="security.permission_grant.issued",
                payload={
                    "grant_id": normalized_grant_id,
                    "workspace_id": payload["workspace_id"],
                    "device_id": payload["device_id"],
                    "scope": payload["scope"],
                    "resource": payload["resource"],
                    "allowed_actions": payload["allowed_actions"],
                    "expires_at": expires_at,
                    "issued_by": payload["issued_by"],
                },
            )
        return payload

    def list_active(
        self,
        *,
        workspace_id: str = "",
        device_id: str = "",
        scope: str = "",
        resource: str = "",
    ) -> list[dict[str, Any]]:
        self.expire_stale()
        with self._db.local_engine.begin() as conn:
            stmt = select(permission_grants_table)
            if workspace_id:
                stmt = stmt.where(permission_grants_table.c.workspace_id == str(workspace_id))
            if device_id:
                stmt = stmt.where(permission_grants_table.c.device_id == str(device_id))
            if scope:
                stmt = stmt.where(permission_grants_table.c.scope == str(scope))
            if resource:
                stmt = stmt.where(permission_grants_table.c.resource == str(resource))
            stmt = stmt.order_by(permission_grants_table.c.created_at.asc())
            rows = conn.execute(stmt).mappings().all()
        now = _now()
        return [
            self._db._decode_permission_grant_row(row)
            for row in rows
            if float(row["expires_at"] or 0.0) <= 0.0 or float(row["expires_at"] or 0.0) > now
        ]

    def revoke_grant(self, grant_id: str, *, revoked_by: str = "runtime", reason: str = "") -> bool:
        with self._db.local_engine.begin() as conn:
            row = conn.execute(
                select(permission_grants_table).where(permission_grants_table.c.grant_id == str(grant_id))
            ).mappings().first()
            if row is None:
                return False
            decoded = self._db._decode_permission_grant_row(row)
            conn.execute(
                permission_grants_table.delete().where(permission_grants_table.c.grant_id == str(grant_id))
            )
            self._db._insert_audit_event(
                conn,
                workspace_id=str(decoded.get("workspace_id") or "local-workspace"),
                event_type="security.permission_grant.revoked",
                payload={
                    "grant_id": str(grant_id),
                    "revoked_by": str(revoked_by or "runtime"),
                    "reason": str(reason or ""),
                    "scope": str(decoded.get("scope") or ""),
                    "resource": str(decoded.get("resource") or ""),
                },
            )
            self._db.outbox.enqueue(
                conn,
                workspace_id=str(decoded.get("workspace_id") or "local-workspace"),
                aggregate_type="permission_grant",
                aggregate_id=str(grant_id),
                event_type="security.permission_grant.revoked",
                payload={
                    "grant_id": str(grant_id),
                    "revoked_by": str(revoked_by or "runtime"),
                    "reason": str(reason or ""),
                    "scope": str(decoded.get("scope") or ""),
                    "resource": str(decoded.get("resource") or ""),
                },
            )
        return True

    def expire_stale(self) -> int:
        now = _now()
        expired: list[dict[str, Any]] = []
        with self._db.local_engine.begin() as conn:
            rows = conn.execute(
                select(permission_grants_table)
                .where(permission_grants_table.c.expires_at > 0.0)
                .where(permission_grants_table.c.expires_at <= now)
            ).mappings().all()
            expired = [self._db._decode_permission_grant_row(row) for row in rows]
            if rows:
                conn.execute(
                    permission_grants_table.delete()
                    .where(permission_grants_table.c.expires_at > 0.0)
                    .where(permission_grants_table.c.expires_at <= now)
                )
                for row in expired:
                    self._db._insert_audit_event(
                        conn,
                        workspace_id=str(row.get("workspace_id") or "local-workspace"),
                        event_type="security.permission_grant.expired",
                        payload={
                            "grant_id": str(row.get("grant_id") or ""),
                            "scope": str(row.get("scope") or ""),
                            "resource": str(row.get("resource") or ""),
                        },
                    )
        return len(expired)


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

    def list_known_workspace_ids(self) -> list[str]:
        with self._db.local_engine.begin() as conn:
            billing_rows = conn.execute(select(billing_workspaces_table.c.workspace_id)).all()
            workspace_rows = conn.execute(select(workspaces_table.c.workspace_id)).all()
        workspace_ids = {
            str(row[0] or "").strip()
            for row in (*billing_rows, *workspace_rows)
            if str(row[0] or "").strip()
        }
        return sorted(workspace_ids)

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

    def record_usage_event(self, event_payload: dict[str, Any]) -> dict[str, Any]:
        event_id = str(event_payload.get("event_id") or f"usgevt_{uuid.uuid4().hex[:12]}")
        workspace_id = str(event_payload.get("workspace_id") or "local-workspace")
        row = {
            "event_id": event_id,
            "workspace_id": workspace_id,
            "actor_id": str(event_payload.get("actor_id") or ""),
            "session_id": str(event_payload.get("session_id") or ""),
            "run_id": str(event_payload.get("run_id") or ""),
            "usage_id": str(event_payload.get("usage_id") or ""),
            "metric": str(event_payload.get("metric") or "unknown"),
            "event_type": str(event_payload.get("event_type") or "usage"),
            "status": str(event_payload.get("status") or "recorded"),
            "reference_id": str(event_payload.get("reference_id") or ""),
            "provider": str(event_payload.get("provider") or ""),
            "model_name": str(event_payload.get("model_name") or event_payload.get("model") or ""),
            "priority": str(event_payload.get("priority") or "normal"),
            "input_tokens": max(0, int(event_payload.get("input_tokens") or 0)),
            "output_tokens": max(0, int(event_payload.get("output_tokens") or 0)),
            "reasoning_tokens": max(0, int(event_payload.get("reasoning_tokens") or 0)),
            "tool_calls": max(0, int(event_payload.get("tool_calls") or 0)),
            "memory_ops": max(0, int(event_payload.get("memory_ops") or 0)),
            "prompt_length": max(0, int(event_payload.get("prompt_length") or 0)),
            "estimated_credits": max(0, int(event_payload.get("estimated_credits") or 0)),
            "actual_credits": max(0, int(event_payload.get("actual_credits") or 0)),
            "bucket": str(event_payload.get("bucket") or ""),
            "metadata_json": _json_dumps(dict(event_payload.get("metadata") or {})),
            "created_at": float(event_payload.get("created_at") or _now()),
        }
        with self._db.local_engine.begin() as conn:
            existing = conn.execute(
                select(usage_events_table.c.event_id).where(usage_events_table.c.event_id == event_id)
            ).first()
            if existing:
                conn.execute(
                    usage_events_table.update()
                    .where(usage_events_table.c.event_id == event_id)
                    .values(**row)
                )
            else:
                conn.execute(usage_events_table.insert().values(**row))
            self._db.outbox.enqueue(
                conn,
                workspace_id=workspace_id,
                aggregate_type="usage_event",
                aggregate_id=event_id,
                event_type=f"billing.usage.{row['event_type']}",
                payload={
                    "workspace_id": workspace_id,
                    "actor_id": row["actor_id"],
                    "metric": row["metric"],
                    "status": row["status"],
                    "estimated_credits": row["estimated_credits"],
                    "actual_credits": row["actual_credits"],
                },
            )
        return self._db._decode_usage_event_row(row)

    def list_usage_events(
        self,
        workspace_id: str,
        *,
        limit: int = 100,
        actor_id: str = "",
        metric: str = "",
    ) -> list[dict[str, Any]]:
        normalized_workspace = str(workspace_id or "local-workspace").strip() or "local-workspace"
        with self._db.local_engine.begin() as conn:
            stmt = select(usage_events_table).where(usage_events_table.c.workspace_id == normalized_workspace)
            if actor_id:
                stmt = stmt.where(usage_events_table.c.actor_id == str(actor_id or "").strip())
            if metric:
                stmt = stmt.where(usage_events_table.c.metric == str(metric or "").strip())
            rows = conn.execute(
                stmt.order_by(usage_events_table.c.created_at.desc()).limit(max(1, int(limit or 100)))
            ).mappings().all()
        return [self._db._decode_usage_event_row(row) for row in rows]

    def get_usage_event(self, event_id: str) -> dict[str, Any] | None:
        normalized = str(event_id or "").strip()
        if not normalized:
            return None
        with self._db.local_engine.begin() as conn:
            row = conn.execute(
                select(usage_events_table).where(usage_events_table.c.event_id == normalized)
            ).mappings().first()
        return self._db._decode_usage_event_row(row) if row else None

    def upsert_rate_limit_bucket(self, bucket_payload: dict[str, Any]) -> dict[str, Any]:
        bucket_id = str(bucket_payload.get("bucket_id") or f"rl_{uuid.uuid4().hex[:12]}")
        workspace_id = str(bucket_payload.get("workspace_id") or "local-workspace")
        row = {
            "bucket_id": bucket_id,
            "workspace_id": workspace_id,
            "actor_id": str(bucket_payload.get("actor_id") or ""),
            "metric": str(bucket_payload.get("metric") or ""),
            "bucket_type": str(bucket_payload.get("bucket_type") or "request_minute"),
            "bucket_key": str(bucket_payload.get("bucket_key") or ""),
            "request_count": max(0, int(bucket_payload.get("request_count") or 0)),
            "credit_spend": max(0, int(bucket_payload.get("credit_spend") or 0)),
            "hard_cap": max(0, int(bucket_payload.get("hard_cap") or 0)),
            "soft_cap": max(0, int(bucket_payload.get("soft_cap") or 0)),
            "status": str(bucket_payload.get("status") or "open"),
            "last_allowed_at": float(bucket_payload.get("last_allowed_at") or 0.0),
            "last_blocked_at": float(bucket_payload.get("last_blocked_at") or 0.0),
            "last_reason": str(bucket_payload.get("last_reason") or ""),
            "metadata_json": _json_dumps(dict(bucket_payload.get("metadata") or {})),
            "created_at": float(bucket_payload.get("created_at") or _now()),
            "updated_at": float(bucket_payload.get("updated_at") or _now()),
        }
        with self._db.local_engine.begin() as conn:
            existing = conn.execute(
                select(rate_limit_buckets_table.c.bucket_id).where(rate_limit_buckets_table.c.bucket_id == bucket_id)
            ).first()
            if existing:
                current = conn.execute(
                    select(rate_limit_buckets_table).where(rate_limit_buckets_table.c.bucket_id == bucket_id)
                ).mappings().first()
                if current:
                    row["created_at"] = float(current.get("created_at") or row["created_at"])
                conn.execute(
                    rate_limit_buckets_table.update()
                    .where(rate_limit_buckets_table.c.bucket_id == bucket_id)
                    .values(**row)
                )
            else:
                conn.execute(rate_limit_buckets_table.insert().values(**row))
        return self._db._decode_rate_limit_bucket_row(row)

    def get_rate_limit_bucket(self, bucket_id: str) -> dict[str, Any] | None:
        normalized = str(bucket_id or "").strip()
        if not normalized:
            return None
        with self._db.local_engine.begin() as conn:
            row = conn.execute(
                select(rate_limit_buckets_table).where(rate_limit_buckets_table.c.bucket_id == normalized)
            ).mappings().first()
        return self._db._decode_rate_limit_bucket_row(row) if row else None

    def list_rate_limit_buckets(
        self,
        workspace_id: str,
        *,
        limit: int = 50,
        bucket_type: str = "",
    ) -> list[dict[str, Any]]:
        normalized_workspace = str(workspace_id or "local-workspace").strip() or "local-workspace"
        with self._db.local_engine.begin() as conn:
            stmt = select(rate_limit_buckets_table).where(rate_limit_buckets_table.c.workspace_id == normalized_workspace)
            if bucket_type:
                stmt = stmt.where(rate_limit_buckets_table.c.bucket_type == str(bucket_type or "").strip())
            rows = conn.execute(
                stmt.order_by(rate_limit_buckets_table.c.updated_at.desc()).limit(max(1, int(limit or 50)))
            ).mappings().all()
        return [self._db._decode_rate_limit_bucket_row(row) for row in rows]

    def get_usage(self, usage_id: str) -> dict[str, Any] | None:
        normalized = str(usage_id or "").strip()
        if not normalized:
            return None
        with self._db.local_engine.begin() as conn:
            row = conn.execute(
                select(usage_ledger_table).where(usage_ledger_table.c.usage_id == normalized)
            ).mappings().first()
        return self._db._decode_usage_row(row) if row else None

    def update_usage_metadata(self, usage_id: str, metadata: dict[str, Any]) -> dict[str, Any] | None:
        normalized = str(usage_id or "").strip()
        if not normalized:
            return None
        with self._db.local_engine.begin() as conn:
            row = conn.execute(
                select(usage_ledger_table).where(usage_ledger_table.c.usage_id == normalized)
            ).mappings().first()
            if row is None:
                return None
            conn.execute(
                usage_ledger_table.update()
                .where(usage_ledger_table.c.usage_id == normalized)
                .values(metadata_json=_json_dumps(dict(metadata or {})))
            )
            updated = dict(row)
            updated["metadata_json"] = _json_dumps(dict(metadata or {}))
        return self._db._decode_usage_row(updated)

    def record_billing_event(self, event_payload: dict[str, Any]) -> dict[str, Any]:
        event_id = str(event_payload.get("event_id") or f"bill_{uuid.uuid4().hex[:12]}")
        workspace_id = str(event_payload.get("workspace_id") or "local-workspace")
        row = {
            "event_id": event_id,
            "workspace_id": workspace_id,
            "provider": str(event_payload.get("provider") or "internal"),
            "event_type": str(event_payload.get("event_type") or "billing.updated"),
            "status": str(event_payload.get("status") or "pending"),
            "reference_id": str(event_payload.get("reference_id") or ""),
            "payload_json": _json_dumps(dict(event_payload.get("payload") or {})),
            "created_at": float(event_payload.get("created_at") or _now()),
        }
        with self._db.local_engine.begin() as conn:
            existing = conn.execute(
                select(billing_events_table.c.event_id).where(billing_events_table.c.event_id == event_id)
            ).first()
            if existing:
                conn.execute(
                    billing_events_table.update()
                    .where(billing_events_table.c.event_id == event_id)
                    .values(**row)
                )
            else:
                conn.execute(billing_events_table.insert().values(**row))
            self._db.outbox.enqueue(
                conn,
                workspace_id=workspace_id,
                aggregate_type="billing_event",
                aggregate_id=event_id,
                event_type=row["event_type"],
                payload={"workspace_id": workspace_id, "provider": row["provider"], "status": row["status"], "reference_id": row["reference_id"]},
            )
        return self._db._decode_billing_event_row(row)

    def list_billing_events(self, workspace_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        with self._db.local_engine.begin() as conn:
            rows = conn.execute(
                select(billing_events_table)
                .where(billing_events_table.c.workspace_id == str(workspace_id or "local-workspace"))
                .order_by(billing_events_table.c.created_at.desc())
                .limit(max(1, int(limit or 100)))
            ).mappings().all()
        return [self._db._decode_billing_event_row(row) for row in rows]

    def list_billing_events_for_reference(
        self,
        workspace_id: str,
        *,
        reference_id: str,
        event_type: str = "",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        normalized_workspace = str(workspace_id or "local-workspace").strip() or "local-workspace"
        normalized_reference = str(reference_id or "").strip()
        if not normalized_reference:
            return []
        with self._db.local_engine.begin() as conn:
            stmt = (
                select(billing_events_table)
                .where(billing_events_table.c.workspace_id == normalized_workspace)
                .where(billing_events_table.c.reference_id == normalized_reference)
            )
            if event_type:
                stmt = stmt.where(billing_events_table.c.event_type == str(event_type or "").strip())
            rows = conn.execute(
                stmt.order_by(billing_events_table.c.created_at.desc()).limit(max(1, int(limit or 50)))
            ).mappings().all()
        return [self._db._decode_billing_event_row(row) for row in rows]

    def upsert_checkout_session(self, session_payload: dict[str, Any]) -> dict[str, Any]:
        reference_id = str(session_payload.get("reference_id") or "").strip()
        if not reference_id:
            raise RuntimeError("billing_checkout_reference_required")
        workspace_id = str(session_payload.get("workspace_id") or "local-workspace").strip() or "local-workspace"
        self.upsert_workspace({"workspace_id": workspace_id})
        values = {
            "reference_id": reference_id,
            "workspace_id": workspace_id,
            "mode": str(session_payload.get("mode") or "subscription").strip() or "subscription",
            "catalog_id": str(session_payload.get("catalog_id") or "").strip(),
            "provider": str(session_payload.get("provider") or "iyzico").strip() or "iyzico",
            "provider_token": str(session_payload.get("provider_token") or "").strip(),
            "provider_payment_id": str(session_payload.get("provider_payment_id") or "").strip(),
            "subscription_reference_code": str(session_payload.get("subscription_reference_code") or "").strip(),
            "status": str(session_payload.get("status") or "pending").strip() or "pending",
            "payment_page_url": str(session_payload.get("payment_page_url") or session_payload.get("launch_url") or "").strip(),
            "callback_url": str(session_payload.get("callback_url") or "").strip(),
            "raw_last_payload_encrypted": self._db.codec.dumps(
                dict(session_payload.get("raw_last_payload") or {}),
                context=f"billing_checkout:{reference_id}:raw",
                classification="sensitive",
            ),
            "created_at": float(session_payload.get("created_at") or _now()),
            "updated_at": float(session_payload.get("updated_at") or _now()),
            "completed_at": float(session_payload.get("completed_at") or 0.0),
        }
        with self._db.local_engine.begin() as conn:
            existing = conn.execute(
                select(billing_checkout_sessions_table.c.reference_id).where(billing_checkout_sessions_table.c.reference_id == reference_id)
            ).first()
            if existing:
                current = conn.execute(
                    select(billing_checkout_sessions_table).where(billing_checkout_sessions_table.c.reference_id == reference_id)
                ).mappings().first()
                if current:
                    current_values = dict(current)
                    values["created_at"] = float(current_values.get("created_at") or values["created_at"])
                conn.execute(
                    billing_checkout_sessions_table.update()
                    .where(billing_checkout_sessions_table.c.reference_id == reference_id)
                    .values(**values)
                )
            else:
                conn.execute(billing_checkout_sessions_table.insert().values(**values))
        return self._db._decode_billing_checkout_session_row(values)

    def get_checkout_session(self, reference_id: str) -> dict[str, Any] | None:
        normalized = str(reference_id or "").strip()
        if not normalized:
            return None
        with self._db.local_engine.begin() as conn:
            row = conn.execute(
                select(billing_checkout_sessions_table).where(billing_checkout_sessions_table.c.reference_id == normalized)
            ).mappings().first()
        return self._db._decode_billing_checkout_session_row(row) if row else None

    def get_checkout_session_by_provider_token(self, provider_token: str) -> dict[str, Any] | None:
        normalized = str(provider_token or "").strip()
        if not normalized:
            return None
        with self._db.local_engine.begin() as conn:
            row = conn.execute(
                select(billing_checkout_sessions_table).where(billing_checkout_sessions_table.c.provider_token == normalized)
            ).mappings().first()
        return self._db._decode_billing_checkout_session_row(row) if row else None

    def get_checkout_session_by_subscription_reference(self, subscription_reference_code: str) -> dict[str, Any] | None:
        normalized = str(subscription_reference_code or "").strip()
        if not normalized:
            return None
        with self._db.local_engine.begin() as conn:
            row = conn.execute(
                select(billing_checkout_sessions_table).where(
                    billing_checkout_sessions_table.c.subscription_reference_code == normalized
                )
            ).mappings().first()
        return self._db._decode_billing_checkout_session_row(row) if row else None

    def upsert_billing_profile(self, workspace_id: str, profile_payload: dict[str, Any]) -> dict[str, Any]:
        workspace_key = str(workspace_id or "local-workspace").strip() or "local-workspace"
        values = {
            "workspace_id": workspace_key,
            "profile_encrypted": self._db.codec.dumps(
                dict(profile_payload or {}),
                context=f"billing_profile:{workspace_key}",
                classification="sensitive",
            ),
            "created_at": float(profile_payload.get("created_at") or _now()),
            "updated_at": float(profile_payload.get("updated_at") or _now()),
        }
        with self._db.local_engine.begin() as conn:
            existing = conn.execute(
                select(workspace_billing_profiles_table.c.workspace_id).where(workspace_billing_profiles_table.c.workspace_id == workspace_key)
            ).first()
            if existing:
                current = conn.execute(
                    select(workspace_billing_profiles_table).where(workspace_billing_profiles_table.c.workspace_id == workspace_key)
                ).mappings().first()
                if current:
                    values["created_at"] = float(current.get("created_at") or values["created_at"])
                conn.execute(
                    workspace_billing_profiles_table.update()
                    .where(workspace_billing_profiles_table.c.workspace_id == workspace_key)
                    .values(**values)
                )
            else:
                conn.execute(workspace_billing_profiles_table.insert().values(**values))
        return self._db._decode_billing_profile_row(values)

    def get_billing_profile(self, workspace_id: str) -> dict[str, Any] | None:
        workspace_key = str(workspace_id or "local-workspace").strip() or "local-workspace"
        with self._db.local_engine.begin() as conn:
            row = conn.execute(
                select(workspace_billing_profiles_table).where(workspace_billing_profiles_table.c.workspace_id == workspace_key)
            ).mappings().first()
        return self._db._decode_billing_profile_row(row) if row else None

    def record_credit_entry(self, credit_payload: dict[str, Any]) -> dict[str, Any]:
        entry_id = str(credit_payload.get("entry_id") or f"cred_{uuid.uuid4().hex[:12]}")
        workspace_id = str(credit_payload.get("workspace_id") or "local-workspace")
        bucket = str(credit_payload.get("bucket") or "purchased").strip().lower() or "purchased"
        delta = int(credit_payload.get("delta_credits") or 0)
        reference_id = str(credit_payload.get("reference_id") or "")
        created_at = float(credit_payload.get("created_at") or _now())
        with self._db.local_engine.begin() as conn:
            existing = conn.execute(
                select(credit_ledger_table.c.entry_id).where(credit_ledger_table.c.entry_id == entry_id)
            ).first()
            if existing:
                row = conn.execute(
                    select(credit_ledger_table).where(credit_ledger_table.c.entry_id == entry_id)
                ).mappings().first()
                return self._db._decode_credit_ledger_row(dict(row or {})) if row else {}
            balance_before = self._current_credit_balance(conn, workspace_id, bucket=bucket)
            balance_after = balance_before + delta
            values = {
                "entry_id": entry_id,
                "workspace_id": workspace_id,
                "bucket": bucket,
                "entry_type": str(credit_payload.get("entry_type") or "adjustment"),
                "delta_credits": delta,
                "balance_after": balance_after,
                "reference_id": reference_id,
                "metadata_json": _json_dumps(dict(credit_payload.get("metadata") or {})),
                "created_at": created_at,
            }
            conn.execute(credit_ledger_table.insert().values(**values))
            self._db.outbox.enqueue(
                conn,
                workspace_id=workspace_id,
                aggregate_type="credit_ledger",
                aggregate_id=entry_id,
                event_type=f"billing.credit.{values['entry_type']}",
                payload={"workspace_id": workspace_id, "bucket": bucket, "delta_credits": delta, "reference_id": reference_id},
            )
        return self._db._decode_credit_ledger_row(values)

    def get_credit_balance(self, workspace_id: str) -> dict[str, Any]:
        wid = str(workspace_id or "local-workspace")
        with self._db.local_engine.begin() as conn:
            rows = conn.execute(
                select(credit_ledger_table)
                .where(credit_ledger_table.c.workspace_id == wid)
                .order_by(credit_ledger_table.c.created_at.asc())
            ).mappings().all()
        included = 0
        purchased = 0
        for row in rows:
            bucket = str(row.get("bucket") or "purchased")
            delta = int(row.get("delta_credits") or 0)
            if bucket == "included":
                included += delta
            else:
                purchased += delta
        return {
            "workspace_id": wid,
            "included": max(0, included),
            "purchased": max(0, purchased),
            "total": max(0, included) + max(0, purchased),
        }

    def list_credit_ledger(self, workspace_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        with self._db.local_engine.begin() as conn:
            rows = conn.execute(
                select(credit_ledger_table)
                .where(credit_ledger_table.c.workspace_id == str(workspace_id or "local-workspace"))
                .order_by(credit_ledger_table.c.created_at.desc())
                .limit(max(1, int(limit or 100)))
            ).mappings().all()
        return [self._db._decode_credit_ledger_row(row) for row in rows]

    def list_credit_entries_for_reference(
        self,
        workspace_id: str,
        *,
        reference_id: str,
        entry_type: str = "",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        normalized_workspace = str(workspace_id or "local-workspace").strip() or "local-workspace"
        normalized_reference = str(reference_id or "").strip()
        if not normalized_reference:
            return []
        with self._db.local_engine.begin() as conn:
            stmt = (
                select(credit_ledger_table)
                .where(credit_ledger_table.c.workspace_id == normalized_workspace)
                .where(credit_ledger_table.c.reference_id == normalized_reference)
            )
            if entry_type:
                stmt = stmt.where(credit_ledger_table.c.entry_type == str(entry_type or "").strip())
            rows = conn.execute(
                stmt.order_by(credit_ledger_table.c.created_at.asc()).limit(max(1, int(limit or 50)))
            ).mappings().all()
        return [self._db._decode_credit_ledger_row(row) for row in rows]

    def record_entitlement_snapshot(self, snapshot_payload: dict[str, Any]) -> dict[str, Any]:
        snapshot_id = str(snapshot_payload.get("snapshot_id") or f"entsnap_{uuid.uuid4().hex[:12]}")
        values = {
            "snapshot_id": snapshot_id,
            "workspace_id": str(snapshot_payload.get("workspace_id") or "local-workspace"),
            "scope": str(snapshot_payload.get("scope") or "workspace"),
            "payload_json": _json_dumps(dict(snapshot_payload.get("payload") or {})),
            "created_at": float(snapshot_payload.get("created_at") or _now()),
        }
        with self._db.local_engine.begin() as conn:
            conn.execute(entitlement_snapshots_table.insert().values(**values))
            self._db.outbox.enqueue(
                conn,
                workspace_id=values["workspace_id"],
                aggregate_type="entitlement_snapshot",
                aggregate_id=snapshot_id,
                event_type="billing.entitlements.snapshotted",
                payload={"workspace_id": values["workspace_id"], "scope": values["scope"]},
            )
        return self._db._decode_entitlement_snapshot_row(values)

    def list_entitlement_snapshots(self, workspace_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        with self._db.local_engine.begin() as conn:
            rows = conn.execute(
                select(entitlement_snapshots_table)
                .where(entitlement_snapshots_table.c.workspace_id == str(workspace_id or "local-workspace"))
                .order_by(entitlement_snapshots_table.c.created_at.desc())
                .limit(max(1, int(limit or 50)))
            ).mappings().all()
        return [self._db._decode_entitlement_snapshot_row(row) for row in rows]

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

    @staticmethod
    def _current_credit_balance(conn: Connection, workspace_id: str, *, bucket: str) -> int:
        rows = conn.execute(
            select(credit_ledger_table.c.delta_credits)
            .where(credit_ledger_table.c.workspace_id == str(workspace_id or "local-workspace"))
            .where(credit_ledger_table.c.bucket == str(bucket or "purchased"))
        ).all()
        return int(sum(int(row[0] or 0) for row in rows))


class ConnectorRepository:
    def __init__(self, db: "RuntimeDatabase") -> None:
        self._db = db

    @staticmethod
    def _account_id(provider: str, account_alias: str) -> str:
        return f"{str(provider or '').strip().lower()}::{str(account_alias or 'default').strip() or 'default'}"

    def backfill_account(self, account_payload: dict[str, Any]) -> None:
        with self._db.local_engine.begin() as conn:
            self._upsert_account(conn, account_payload, enqueue=False)

    def upsert_account(self, account_payload: dict[str, Any]) -> None:
        with self._db.local_engine.begin() as conn:
            self._upsert_account(conn, account_payload, enqueue=True)

    def _upsert_account(self, conn: Connection, account_payload: dict[str, Any], *, enqueue: bool) -> None:
        provider = str(account_payload.get("provider") or "").strip().lower()
        account_alias = str(account_payload.get("account_alias") or "default").strip() or "default"
        if not provider:
            return
        workspace_id = str(
            account_payload.get("workspace_id")
            or account_payload.get("metadata", {}).get("workspace_id")
            or "local-workspace"
        )
        account_id = str(account_payload.get("account_id") or self._account_id(provider, account_alias))
        connector_name = str(account_payload.get("connector_name") or account_payload.get("metadata", {}).get("connector") or provider).strip().lower()
        values = {
            "account_id": account_id,
            "workspace_id": workspace_id,
            "provider": provider,
            "connector_name": connector_name,
            "account_alias": account_alias,
            "display_name": str(account_payload.get("display_name") or provider.title()),
            "email": str(account_payload.get("email") or ""),
            "status": str(account_payload.get("status") or "needs_input"),
            "auth_strategy": str(account_payload.get("auth_strategy") or "oauth"),
            "auth_url": str(account_payload.get("auth_url") or ""),
            "redirect_uri": str(account_payload.get("redirect_uri") or ""),
            "scopes_json": _json_dumps(list(account_payload.get("granted_scopes") or account_payload.get("scopes") or [])),
            "metadata_json": _json_dumps(dict(account_payload.get("metadata") or {})),
            "updated_at": float(account_payload.get("updated_at") or _now()),
        }
        existing = conn.execute(
            select(local_connector_accounts_table.c.account_id).where(local_connector_accounts_table.c.account_id == account_id)
        ).first()
        if existing:
            conn.execute(
                local_connector_accounts_table.update()
                .where(local_connector_accounts_table.c.account_id == account_id)
                .values(**values)
            )
        else:
            conn.execute(local_connector_accounts_table.insert().values(**values))

        health_payload = {
            "auth_state": values["status"],
            "scopes": _json_loads(values["scopes_json"], []),
            "connector_name": connector_name,
        }
        self._upsert_health(conn, account_id=account_id, workspace_id=workspace_id, status=values["status"], payload=health_payload)

        if enqueue:
            self._db.outbox.enqueue(
                conn,
                workspace_id=workspace_id,
                aggregate_type="connector_account",
                aggregate_id=account_id,
                event_type="connector.account.updated",
                payload={
                    "workspace_id": workspace_id,
                    "account_id": account_id,
                    "provider": provider,
                    "connector_name": connector_name,
                    "account_alias": account_alias,
                    "status": values["status"],
                    "display_name": values["display_name"],
                    "email": values["email"],
                    "scopes": _json_loads(values["scopes_json"], []),
                    "auth_strategy": values["auth_strategy"],
                    "metadata": _json_loads(values["metadata_json"], {}),
                },
            )

    def _upsert_health(self, conn: Connection, *, account_id: str, workspace_id: str, status: str, payload: dict[str, Any]) -> None:
        health_id = f"health::{account_id}"
        values = {
            "health_id": health_id,
            "account_id": account_id,
            "workspace_id": workspace_id,
            "status": str(status or "healthy"),
            "payload_json": _json_dumps(dict(payload or {})),
            "updated_at": _now(),
        }
        existing = conn.execute(
            select(local_connector_health_table.c.health_id).where(local_connector_health_table.c.health_id == health_id)
        ).first()
        if existing:
            conn.execute(
                local_connector_health_table.update()
                .where(local_connector_health_table.c.health_id == health_id)
                .values(**values)
            )
        else:
            conn.execute(local_connector_health_table.insert().values(**values))

    def list_accounts(self, *, workspace_id: str = "local-workspace", provider: str = "", include_revoked: bool = False) -> list[dict[str, Any]]:
        with self._db.local_engine.begin() as conn:
            stmt = select(local_connector_accounts_table).where(local_connector_accounts_table.c.workspace_id == str(workspace_id or "local-workspace"))
            if provider:
                stmt = stmt.where(local_connector_accounts_table.c.provider == str(provider).strip().lower())
            if not include_revoked:
                stmt = stmt.where(local_connector_accounts_table.c.status != "revoked")
            rows = conn.execute(stmt.order_by(local_connector_accounts_table.c.updated_at.desc())).mappings().all()
        return [self._db._decode_connector_account_row(row) for row in rows]

    def get_account(self, provider: str, account_alias: str = "default", workspace_id: str = "local-workspace") -> dict[str, Any] | None:
        account_id = self._account_id(provider, account_alias)
        with self._db.local_engine.begin() as conn:
            row = conn.execute(
                select(local_connector_accounts_table)
                .where(local_connector_accounts_table.c.account_id == account_id)
                .where(local_connector_accounts_table.c.workspace_id == str(workspace_id or "local-workspace"))
            ).mappings().first()
        return self._db._decode_connector_account_row(row) if row else None

    def delete_account(self, provider: str, account_alias: str = "default", workspace_id: str = "local-workspace") -> bool:
        account_id = self._account_id(provider, account_alias)
        with self._db.local_engine.begin() as conn:
            row = conn.execute(
                select(local_connector_accounts_table).where(local_connector_accounts_table.c.account_id == account_id)
            ).mappings().first()
            if row is None:
                return False
            conn.execute(
                local_connector_accounts_table.update()
                .where(local_connector_accounts_table.c.account_id == account_id)
                .values(status="revoked", updated_at=_now())
            )
            self._upsert_health(
                conn,
                account_id=account_id,
                workspace_id=str(workspace_id or row.get("workspace_id") or "local-workspace"),
                status="revoked",
                payload={"auth_state": "revoked"},
            )
            self._db.outbox.enqueue(
                conn,
                workspace_id=str(workspace_id or row.get("workspace_id") or "local-workspace"),
                aggregate_type="connector_account",
                aggregate_id=account_id,
                event_type="connector.account.revoked",
                payload={
                    "workspace_id": str(workspace_id or row.get("workspace_id") or "local-workspace"),
                    "account_id": account_id,
                    "provider": str(provider or "").strip().lower(),
                    "account_alias": str(account_alias or "default"),
                    "status": "revoked",
                },
            )
        return True

    def record_trace(self, trace_payload: dict[str, Any]) -> dict[str, Any]:
        trace_id = str(trace_payload.get("trace_id") or f"itr_{uuid.uuid4().hex[:12]}")
        workspace_id = str(
            trace_payload.get("workspace_id")
            or trace_payload.get("metadata", {}).get("workspace_id")
            or "local-workspace"
        )
        provider = str(trace_payload.get("provider") or "").strip().lower()
        connector_name = str(trace_payload.get("connector_name") or provider or "").strip().lower()
        account_alias = str(trace_payload.get("account_alias") or "default").strip() or "default"
        account_id = str(trace_payload.get("connector_account_id") or self._account_id(provider, account_alias))
        values = {
            "trace_id": trace_id,
            "workspace_id": workspace_id,
            "connector_account_id": account_id,
            "provider": provider,
            "connector_name": connector_name,
            "integration_type": str(trace_payload.get("integration_type") or ""),
            "event_type": str(trace_payload.get("operation") or trace_payload.get("event_type") or "connector"),
            "status": str(trace_payload.get("status") or ""),
            "success": bool(trace_payload.get("success")),
            "latency_ms": float(trace_payload.get("latency_ms") or 0.0),
            "payload_json": _json_dumps(
                {
                    "request_id": str(trace_payload.get("request_id") or ""),
                    "user_id": str(trace_payload.get("user_id") or ""),
                    "session_id": str(trace_payload.get("session_id") or ""),
                    "channel": str(trace_payload.get("channel") or ""),
                    "auth_state": str(trace_payload.get("auth_state") or ""),
                    "auth_strategy": str(trace_payload.get("auth_strategy") or ""),
                    "fallback_used": bool(trace_payload.get("fallback_used")),
                    "fallback_reason": str(trace_payload.get("fallback_reason") or ""),
                    "install_state": str(trace_payload.get("install_state") or ""),
                    "retry_count": int(trace_payload.get("retry_count") or 0),
                    "evidence": list(trace_payload.get("evidence") or []),
                    "artifacts": list(trace_payload.get("artifacts") or []),
                    "verification": dict(trace_payload.get("verification") or {}),
                    "metadata": dict(trace_payload.get("metadata") or {}),
                }
            ),
            "created_at": float(trace_payload.get("created_at") or _now()),
        }
        with self._db.local_engine.begin() as conn:
            conn.execute(local_connector_action_traces_table.insert().values(**values))
            self._upsert_health(
                conn,
                account_id=account_id,
                workspace_id=workspace_id,
                status=str(values["status"] or ("healthy" if values["success"] else "degraded")),
                payload={
                    "latest_trace_id": trace_id,
                    "connector_name": connector_name,
                    "provider": provider,
                    "status": values["status"],
                    "success": values["success"],
                },
            )
            self._db.outbox.enqueue(
                conn,
                workspace_id=workspace_id,
                aggregate_type="connector_trace",
                aggregate_id=trace_id,
                event_type="connector.trace.recorded",
                payload={
                    "workspace_id": workspace_id,
                    "trace_id": trace_id,
                    "connector_account_id": account_id,
                    "provider": provider,
                    "connector_name": connector_name,
                    "integration_type": values["integration_type"],
                    "event_type": values["event_type"],
                    "status": values["status"],
                    "success": values["success"],
                    "latency_ms": values["latency_ms"],
                    "payload": _json_loads(values["payload_json"], {}),
                },
            )
        out = dict(trace_payload)
        out["trace_id"] = trace_id
        out["workspace_id"] = workspace_id
        out["connector_account_id"] = account_id
        return out

    def list_traces(
        self,
        *,
        limit: int = 100,
        workspace_id: str = "local-workspace",
        provider: str = "",
        user_id: str = "",
        operation: str = "",
        connector_name: str = "",
        integration_type: str = "",
    ) -> list[dict[str, Any]]:
        with self._db.local_engine.begin() as conn:
            stmt = select(local_connector_action_traces_table).where(
                local_connector_action_traces_table.c.workspace_id == str(workspace_id or "local-workspace")
            )
            if provider:
                stmt = stmt.where(local_connector_action_traces_table.c.provider == str(provider).strip().lower())
            if connector_name:
                stmt = stmt.where(local_connector_action_traces_table.c.connector_name == str(connector_name).strip().lower())
            if operation:
                stmt = stmt.where(local_connector_action_traces_table.c.event_type == str(operation).strip().lower())
            if integration_type:
                stmt = stmt.where(local_connector_action_traces_table.c.integration_type == str(integration_type).strip().lower())
            rows = conn.execute(
                stmt.order_by(local_connector_action_traces_table.c.created_at.desc()).limit(max(1, int(limit or 100)))
            ).mappings().all()
        decoded = [self._db._decode_connector_trace_row(row) for row in rows]
        if user_id:
            low_user = str(user_id or "").strip().lower()
            decoded = [item for item in decoded if str(item.get("user_id") or "").strip().lower() == low_user]
        return decoded

    def summary(self, *, workspace_id: str = "local-workspace", limit: int = 200) -> dict[str, Any]:
        rows = self.list_traces(workspace_id=workspace_id, limit=limit)
        by_provider: dict[str, int] = {}
        by_operation: dict[str, int] = {}
        by_status: dict[str, int] = {}
        fallback_count = 0
        for row in rows:
            provider = str(row.get("provider") or "unknown")
            operation = str(row.get("operation") or "connector")
            status = str(row.get("status") or "unknown")
            by_provider[provider] = int(by_provider.get(provider, 0)) + 1
            by_operation[operation] = int(by_operation.get(operation, 0)) + 1
            by_status[status] = int(by_status.get(status, 0)) + 1
            if bool(row.get("fallback_used")):
                fallback_count += 1
        avg_latency = sum(float(row.get("latency_ms") or 0.0) for row in rows) / len(rows) if rows else 0.0
        return {
            "total": len(rows),
            "avg_latency_ms": round(avg_latency, 2),
            "fallback_count": fallback_count,
            "by_provider": by_provider,
            "by_operation": by_operation,
            "by_status": by_status,
            "recent": rows[:20],
            "trace_path": str(self._db.db_path),
        }


class LearningRepository:
    def __init__(self, db: "RuntimeDatabase") -> None:
        self._db = db

    @staticmethod
    def _profile_id(workspace_id: str, user_id: str) -> str:
        return f"profile::{str(workspace_id or 'local-workspace')}::{str(user_id or 'local-user')}"

    @staticmethod
    def _stat_id(scope: str, tool_name: str) -> str:
        return f"{str(scope or 'global')}::{str(tool_name or 'unknown')}"

    def enqueue_preference_update(
        self,
        *,
        workspace_id: str = "local-workspace",
        user_id: str = "local-user",
        conversation_session_id: str = "",
        preference_key: str,
        proposed_value: dict[str, Any] | None = None,
        rationale: str = "",
        confidence: float = 0.0,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        wid = str(workspace_id or "local-workspace").strip() or "local-workspace"
        uid = str(user_id or "local-user").strip() or "local-user"
        pref_key = str(preference_key or "").strip().lower()
        if not pref_key:
            raise ValueError("preference_key required")
        proposed_payload = dict(proposed_value or {})
        rationale_text = str(rationale or "").strip()
        status = "draft"
        now = _now()
        with self._db.local_engine.begin() as conn:
            existing = conn.execute(
                select(preference_update_queue_table)
                .where(preference_update_queue_table.c.workspace_id == wid)
                .where(preference_update_queue_table.c.user_id == uid)
                .where(preference_update_queue_table.c.preference_key == pref_key)
                .where(preference_update_queue_table.c.status == status)
                .where(preference_update_queue_table.c.proposed_value_json == _json_dumps(proposed_payload))
                .order_by(preference_update_queue_table.c.updated_at.desc())
                .limit(1)
            ).mappings().first()
            if existing:
                update_values = {
                    "rationale": rationale_text or str(existing.get("rationale") or ""),
                    "confidence": max(float(existing.get("confidence") or 0.0), float(confidence or 0.0)),
                    "metadata_json": _json_dumps({**_json_loads(existing.get("metadata_json"), {}), **dict(metadata or {})}),
                    "updated_at": now,
                }
                conn.execute(
                    preference_update_queue_table.update()
                    .where(preference_update_queue_table.c.queue_id == str(existing["queue_id"]))
                    .values(**update_values)
                )
                row = dict(existing)
                row.update(update_values)
                return self._db._decode_preference_update_queue_row(row)

            queue_id = f"prefdraft_{uuid.uuid4().hex[:12]}"
            values = {
                "queue_id": queue_id,
                "workspace_id": wid,
                "user_id": uid,
                "conversation_session_id": str(conversation_session_id or "").strip(),
                "preference_key": pref_key,
                "proposed_value_json": _json_dumps(proposed_payload),
                "rationale": rationale_text,
                "confidence": max(0.0, min(1.0, float(confidence or 0.0))),
                "status": status,
                "metadata_json": _json_dumps(dict(metadata or {})),
                "created_at": now,
                "updated_at": now,
                "reviewed_at": 0.0,
                "applied_at": 0.0,
            }
            conn.execute(preference_update_queue_table.insert().values(**values))
            self._db._insert_audit_event(
                conn,
                workspace_id=wid,
                event_type="learning.preference_draft.created",
                payload={
                    "queue_id": queue_id,
                    "user_id": uid,
                    "preference_key": pref_key,
                    "confidence": values["confidence"],
                },
            )
            self._db.outbox.enqueue(
                conn,
                workspace_id=wid,
                aggregate_type="learning_feedback",
                aggregate_id=queue_id,
                event_type="learning.preference_draft.created",
                payload={
                    "queue_id": queue_id,
                    "workspace_id": wid,
                    "user_id": uid,
                    "preference_key": pref_key,
                    "proposed_value": proposed_payload,
                    "confidence": values["confidence"],
                },
            )
        return self._db._decode_preference_update_queue_row(values)

    def list_preference_updates(
        self,
        *,
        workspace_id: str = "local-workspace",
        user_id: str = "local-user",
        status: str = "draft",
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        wid = str(workspace_id or "local-workspace").strip() or "local-workspace"
        uid = str(user_id or "local-user").strip() or "local-user"
        row_limit = max(1, int(limit or 20))
        with self._db.local_engine.begin() as conn:
            stmt = (
                select(preference_update_queue_table)
                .where(preference_update_queue_table.c.workspace_id == wid)
                .where(preference_update_queue_table.c.user_id == uid)
                .order_by(preference_update_queue_table.c.updated_at.desc())
                .limit(row_limit)
            )
            if status:
                stmt = stmt.where(preference_update_queue_table.c.status == str(status).strip().lower())
            rows = conn.execute(stmt).mappings().all()
        return [self._db._decode_preference_update_queue_row(dict(row)) for row in rows]

    def enqueue_skill_draft(
        self,
        *,
        workspace_id: str = "local-workspace",
        user_id: str = "local-user",
        conversation_session_id: str = "",
        name_hint: str,
        description: str = "",
        trigger_text: str = "",
        source_action: str = "",
        tool_names: list[str] | None = None,
        confidence: float = 0.0,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        wid = str(workspace_id or "local-workspace").strip() or "local-workspace"
        uid = str(user_id or "local-user").strip() or "local-user"
        normalized_name = str(name_hint or "").strip().lower() or "workflow_draft"
        description_text = str(description or "").strip()
        trigger = str(trigger_text or "").strip()
        status = "draft"
        tools_json = _json_dumps([str(item).strip() for item in list(tool_names or []) if str(item).strip()][:12])
        now = _now()
        with self._db.local_engine.begin() as conn:
            existing = conn.execute(
                select(skill_draft_queue_table)
                .where(skill_draft_queue_table.c.workspace_id == wid)
                .where(skill_draft_queue_table.c.user_id == uid)
                .where(skill_draft_queue_table.c.name_hint == normalized_name)
                .where(skill_draft_queue_table.c.status == status)
                .where(skill_draft_queue_table.c.trigger_text == trigger)
                .order_by(skill_draft_queue_table.c.updated_at.desc())
                .limit(1)
            ).mappings().first()
            if existing:
                update_values = {
                    "description": description_text or str(existing.get("description") or ""),
                    "tool_names_json": tools_json if tools_json != "[]" else str(existing.get("tool_names_json") or "[]"),
                    "confidence": max(float(existing.get("confidence") or 0.0), float(confidence or 0.0)),
                    "metadata_json": _json_dumps({**_json_loads(existing.get("metadata_json"), {}), **dict(metadata or {})}),
                    "updated_at": now,
                }
                conn.execute(
                    skill_draft_queue_table.update()
                    .where(skill_draft_queue_table.c.draft_id == str(existing["draft_id"]))
                    .values(**update_values)
                )
                row = dict(existing)
                row.update(update_values)
                return self._db._decode_skill_draft_queue_row(row)

            draft_id = f"skilldraft_{uuid.uuid4().hex[:12]}"
            values = {
                "draft_id": draft_id,
                "workspace_id": wid,
                "user_id": uid,
                "conversation_session_id": str(conversation_session_id or "").strip(),
                "name_hint": normalized_name,
                "description": description_text,
                "trigger_text": trigger,
                "source_action": str(source_action or "").strip(),
                "tool_names_json": tools_json,
                "confidence": max(0.0, min(1.0, float(confidence or 0.0))),
                "status": status,
                "metadata_json": _json_dumps(dict(metadata or {})),
                "created_at": now,
                "updated_at": now,
                "reviewed_at": 0.0,
            }
            conn.execute(skill_draft_queue_table.insert().values(**values))
            self._db._insert_audit_event(
                conn,
                workspace_id=wid,
                event_type="learning.skill_draft.created",
                payload={
                    "draft_id": draft_id,
                    "user_id": uid,
                    "name_hint": normalized_name,
                    "confidence": values["confidence"],
                },
            )
            self._db.outbox.enqueue(
                conn,
                workspace_id=wid,
                aggregate_type="learning_feedback",
                aggregate_id=draft_id,
                event_type="learning.skill_draft.created",
                payload={
                    "draft_id": draft_id,
                    "workspace_id": wid,
                    "user_id": uid,
                    "name_hint": normalized_name,
                    "tool_names": _json_loads(tools_json, []),
                    "confidence": values["confidence"],
                },
            )
        return self._db._decode_skill_draft_queue_row(values)

    def list_skill_drafts(
        self,
        *,
        workspace_id: str = "local-workspace",
        user_id: str = "local-user",
        status: str = "draft",
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        wid = str(workspace_id or "local-workspace").strip() or "local-workspace"
        uid = str(user_id or "local-user").strip() or "local-user"
        row_limit = max(1, int(limit or 20))
        with self._db.local_engine.begin() as conn:
            stmt = (
                select(skill_draft_queue_table)
                .where(skill_draft_queue_table.c.workspace_id == wid)
                .where(skill_draft_queue_table.c.user_id == uid)
                .order_by(skill_draft_queue_table.c.updated_at.desc())
                .limit(row_limit)
            )
            if status:
                stmt = stmt.where(skill_draft_queue_table.c.status == str(status).strip().lower())
            rows = conn.execute(stmt).mappings().all()
        return [self._db._decode_skill_draft_queue_row(dict(row)) for row in rows]

    def get_skill_draft(
        self,
        *,
        workspace_id: str = "local-workspace",
        user_id: str = "local-user",
        draft_id: str,
    ) -> dict[str, Any] | None:
        wid = str(workspace_id or "local-workspace").strip() or "local-workspace"
        uid = str(user_id or "local-user").strip() or "local-user"
        needle = str(draft_id or "").strip()
        if not needle:
            return None
        with self._db.local_engine.begin() as conn:
            row = conn.execute(
                select(skill_draft_queue_table)
                .where(skill_draft_queue_table.c.workspace_id == wid)
                .where(skill_draft_queue_table.c.user_id == uid)
                .where(skill_draft_queue_table.c.draft_id == needle)
                .limit(1)
            ).mappings().first()
            if not row:
                matches = conn.execute(
                    select(skill_draft_queue_table)
                    .where(skill_draft_queue_table.c.workspace_id == wid)
                    .where(skill_draft_queue_table.c.user_id == uid)
                    .where(skill_draft_queue_table.c.draft_id.like(f"{needle}%"))
                    .order_by(skill_draft_queue_table.c.updated_at.desc())
                    .limit(3)
                ).mappings().all()
                if len(matches) == 1:
                    row = matches[0]
        return self._db._decode_skill_draft_queue_row(dict(row)) if row else None

    def update_skill_draft_status(
        self,
        *,
        workspace_id: str = "local-workspace",
        user_id: str = "local-user",
        draft_id: str,
        status: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        wid = str(workspace_id or "local-workspace").strip() or "local-workspace"
        uid = str(user_id or "local-user").strip() or "local-user"
        target = self.get_skill_draft(workspace_id=wid, user_id=uid, draft_id=draft_id)
        if not target:
            return None
        now = _now()
        updated = {
            **target,
            "status": str(status or "draft").strip().lower() or "draft",
            "metadata": {
                **dict(target.get("metadata") or {}),
                **dict(metadata or {}),
            },
            "updated_at": now,
            "reviewed_at": now,
        }
        with self._db.local_engine.begin() as conn:
            conn.execute(
                skill_draft_queue_table.update()
                .where(skill_draft_queue_table.c.draft_id == str(target["draft_id"]))
                .values(
                    status=updated["status"],
                    metadata_json=_json_dumps(updated["metadata"]),
                    updated_at=now,
                    reviewed_at=now,
                )
            )
            self._db._insert_audit_event(
                conn,
                workspace_id=wid,
                event_type="learning.skill_draft.status_updated",
                payload={
                    "draft_id": str(target["draft_id"]),
                    "user_id": uid,
                    "status": updated["status"],
                },
            )
        return updated

    def enqueue_routine_draft(
        self,
        *,
        workspace_id: str = "local-workspace",
        user_id: str = "local-user",
        conversation_session_id: str = "",
        name_hint: str,
        description: str = "",
        trigger_text: str = "",
        schedule_expression: str = "",
        delivery_channel: str = "",
        source_action: str = "",
        confidence: float = 0.0,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        wid = str(workspace_id or "local-workspace").strip() or "local-workspace"
        uid = str(user_id or "local-user").strip() or "local-user"
        normalized_name = str(name_hint or "").strip().lower() or "routine_draft"
        description_text = str(description or "").strip()
        trigger = str(trigger_text or "").strip()
        schedule = str(schedule_expression or "").strip()
        channel = str(delivery_channel or "").strip().lower()
        status = "draft"
        now = _now()
        with self._db.local_engine.begin() as conn:
            existing = conn.execute(
                select(routine_draft_queue_table)
                .where(routine_draft_queue_table.c.workspace_id == wid)
                .where(routine_draft_queue_table.c.user_id == uid)
                .where(routine_draft_queue_table.c.name_hint == normalized_name)
                .where(routine_draft_queue_table.c.status == status)
                .where(routine_draft_queue_table.c.trigger_text == trigger)
                .order_by(routine_draft_queue_table.c.updated_at.desc())
                .limit(1)
            ).mappings().first()
            if existing:
                update_values = {
                    "description": description_text or str(existing.get("description") or ""),
                    "schedule_expression": schedule or str(existing.get("schedule_expression") or ""),
                    "delivery_channel": channel or str(existing.get("delivery_channel") or ""),
                    "confidence": max(float(existing.get("confidence") or 0.0), float(confidence or 0.0)),
                    "metadata_json": _json_dumps({**_json_loads(existing.get("metadata_json"), {}), **dict(metadata or {})}),
                    "updated_at": now,
                }
                conn.execute(
                    routine_draft_queue_table.update()
                    .where(routine_draft_queue_table.c.draft_id == str(existing["draft_id"]))
                    .values(**update_values)
                )
                row = dict(existing)
                row.update(update_values)
                return self._db._decode_routine_draft_queue_row(row)

            draft_id = f"routinedraft_{uuid.uuid4().hex[:12]}"
            values = {
                "draft_id": draft_id,
                "workspace_id": wid,
                "user_id": uid,
                "conversation_session_id": str(conversation_session_id or "").strip(),
                "name_hint": normalized_name,
                "description": description_text,
                "trigger_text": trigger,
                "schedule_expression": schedule,
                "delivery_channel": channel,
                "source_action": str(source_action or "").strip(),
                "confidence": max(0.0, min(1.0, float(confidence or 0.0))),
                "status": status,
                "metadata_json": _json_dumps(dict(metadata or {})),
                "created_at": now,
                "updated_at": now,
                "reviewed_at": 0.0,
            }
            conn.execute(routine_draft_queue_table.insert().values(**values))
            self._db._insert_audit_event(
                conn,
                workspace_id=wid,
                event_type="learning.routine_draft.created",
                payload={
                    "draft_id": draft_id,
                    "user_id": uid,
                    "name_hint": normalized_name,
                    "schedule_expression": schedule,
                    "delivery_channel": channel,
                    "confidence": values["confidence"],
                },
            )
            self._db.outbox.enqueue(
                conn,
                workspace_id=wid,
                aggregate_type="learning_feedback",
                aggregate_id=draft_id,
                event_type="learning.routine_draft.created",
                payload={
                    "draft_id": draft_id,
                    "workspace_id": wid,
                    "user_id": uid,
                    "name_hint": normalized_name,
                    "schedule_expression": schedule,
                    "delivery_channel": channel,
                    "confidence": values["confidence"],
                },
            )
        return self._db._decode_routine_draft_queue_row(values)

    def list_routine_drafts(
        self,
        *,
        workspace_id: str = "local-workspace",
        user_id: str = "local-user",
        status: str = "draft",
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        wid = str(workspace_id or "local-workspace").strip() or "local-workspace"
        uid = str(user_id or "local-user").strip() or "local-user"
        row_limit = max(1, int(limit or 20))
        with self._db.local_engine.begin() as conn:
            stmt = (
                select(routine_draft_queue_table)
                .where(routine_draft_queue_table.c.workspace_id == wid)
                .where(routine_draft_queue_table.c.user_id == uid)
                .order_by(routine_draft_queue_table.c.updated_at.desc())
                .limit(row_limit)
            )
            if status:
                stmt = stmt.where(routine_draft_queue_table.c.status == str(status).strip().lower())
            rows = conn.execute(stmt).mappings().all()
        return [self._db._decode_routine_draft_queue_row(dict(row)) for row in rows]

    def get_routine_draft(
        self,
        *,
        workspace_id: str = "local-workspace",
        user_id: str = "local-user",
        draft_id: str,
    ) -> dict[str, Any] | None:
        wid = str(workspace_id or "local-workspace").strip() or "local-workspace"
        uid = str(user_id or "local-user").strip() or "local-user"
        needle = str(draft_id or "").strip()
        if not needle:
            return None
        with self._db.local_engine.begin() as conn:
            row = conn.execute(
                select(routine_draft_queue_table)
                .where(routine_draft_queue_table.c.workspace_id == wid)
                .where(routine_draft_queue_table.c.user_id == uid)
                .where(routine_draft_queue_table.c.draft_id == needle)
                .limit(1)
            ).mappings().first()
            if not row:
                matches = conn.execute(
                    select(routine_draft_queue_table)
                    .where(routine_draft_queue_table.c.workspace_id == wid)
                    .where(routine_draft_queue_table.c.user_id == uid)
                    .where(routine_draft_queue_table.c.draft_id.like(f"{needle}%"))
                    .order_by(routine_draft_queue_table.c.updated_at.desc())
                    .limit(3)
                ).mappings().all()
                if len(matches) == 1:
                    row = matches[0]
        return self._db._decode_routine_draft_queue_row(dict(row)) if row else None

    def update_routine_draft_status(
        self,
        *,
        workspace_id: str = "local-workspace",
        user_id: str = "local-user",
        draft_id: str,
        status: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        wid = str(workspace_id or "local-workspace").strip() or "local-workspace"
        uid = str(user_id or "local-user").strip() or "local-user"
        target = self.get_routine_draft(workspace_id=wid, user_id=uid, draft_id=draft_id)
        if not target:
            return None
        now = _now()
        updated = {
            **target,
            "status": str(status or "draft").strip().lower() or "draft",
            "metadata": {
                **dict(target.get("metadata") or {}),
                **dict(metadata or {}),
            },
            "updated_at": now,
            "reviewed_at": now,
        }
        with self._db.local_engine.begin() as conn:
            conn.execute(
                routine_draft_queue_table.update()
                .where(routine_draft_queue_table.c.draft_id == str(target["draft_id"]))
                .values(
                    status=updated["status"],
                    metadata_json=_json_dumps(updated["metadata"]),
                    updated_at=now,
                    reviewed_at=now,
                )
            )
            self._db._insert_audit_event(
                conn,
                workspace_id=wid,
                event_type="learning.routine_draft.status_updated",
                payload={
                    "draft_id": str(target["draft_id"]),
                    "user_id": uid,
                    "status": updated["status"],
                },
            )
        return updated

    def upsert_user_preference_profile(
        self,
        *,
        workspace_id: str = "local-workspace",
        user_id: str = "local-user",
        explanation_style: str = "",
        approval_sensitivity_hint: str = "",
        preferred_route: str = "",
        preferred_model: str = "",
        task_templates: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        profile_id = self._profile_id(workspace_id, user_id)
        values = {
            "profile_id": profile_id,
            "workspace_id": str(workspace_id or "local-workspace"),
            "user_id": str(user_id or "local-user"),
            "explanation_style": str(explanation_style or "concise"),
            "approval_sensitivity_hint": str(approval_sensitivity_hint or "balanced"),
            "preferred_route": str(preferred_route or "balanced"),
            "preferred_model": str(preferred_model or ""),
            "task_templates_json": _json_dumps(list(task_templates or [])),
            "metadata_json": _json_dumps(dict(metadata or {})),
            "updated_at": _now(),
        }
        with self._db.local_engine.begin() as conn:
            existing = conn.execute(
                select(user_preference_profiles_table.c.profile_id).where(user_preference_profiles_table.c.profile_id == profile_id)
            ).first()
            if existing:
                conn.execute(
                    user_preference_profiles_table.update()
                    .where(user_preference_profiles_table.c.profile_id == profile_id)
                    .values(**values)
                )
            else:
                conn.execute(user_preference_profiles_table.insert().values(**values))
            self._db._insert_audit_event(
                conn,
                workspace_id=str(workspace_id or "local-workspace"),
                event_type="learning.user_profile.updated",
                payload={
                    "profile_id": profile_id,
                    "user_id": str(user_id or "local-user"),
                    "explanation_style": values["explanation_style"],
                    "approval_sensitivity_hint": values["approval_sensitivity_hint"],
                    "preferred_route": values["preferred_route"],
                },
            )
            self._db.outbox.enqueue(
                conn,
                workspace_id=str(workspace_id or "local-workspace"),
                aggregate_type="user_preference_profile",
                aggregate_id=profile_id,
                event_type="learning.user_profile.updated",
                payload={
                    "profile_id": profile_id,
                    "workspace_id": str(workspace_id or "local-workspace"),
                    "user_id": str(user_id or "local-user"),
                    "explanation_style": values["explanation_style"],
                    "approval_sensitivity_hint": values["approval_sensitivity_hint"],
                    "preferred_route": values["preferred_route"],
                    "preferred_model": values["preferred_model"],
                    "task_templates": list(task_templates or []),
                },
            )
        return self.get_user_preference_profile(workspace_id=workspace_id, user_id=user_id) or {}

    def get_user_preference_profile(self, *, workspace_id: str = "local-workspace", user_id: str = "local-user") -> dict[str, Any] | None:
        profile_id = self._profile_id(workspace_id, user_id)
        with self._db.local_engine.begin() as conn:
            row = conn.execute(
                select(user_preference_profiles_table)
                .where(user_preference_profiles_table.c.profile_id == profile_id)
            ).mappings().first()
        return self._db._decode_user_preference_profile_row(row) if row else None

    def record_operational_feedback(
        self,
        *,
        workspace_id: str = "local-workspace",
        user_id: str = "local-user",
        category: str,
        entity_id: str,
        outcome: str,
        reward: float = 0.0,
        latency_ms: float = 0.0,
        recovery_count: int = 0,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        feedback_id = f"feedback_{uuid.uuid4().hex[:12]}"
        row_payload = {
            "feedback_id": feedback_id,
            "workspace_id": str(workspace_id or "local-workspace"),
            "user_id": str(user_id or "local-user"),
            "category": str(category or "runtime"),
            "entity_id": str(entity_id or "unknown"),
            "outcome": str(outcome or "neutral"),
            "reward": float(reward or 0.0),
            "latency_ms": float(latency_ms or 0.0),
            "recovery_count": max(0, int(recovery_count or 0)),
            "payload": dict(payload or {}),
            "created_at": _now(),
        }
        with self._db.local_engine.begin() as conn:
            conn.execute(
                operational_feedback_table.insert().values(
                    feedback_id=feedback_id,
                    workspace_id=row_payload["workspace_id"],
                    user_id=row_payload["user_id"],
                    category=row_payload["category"],
                    entity_id=row_payload["entity_id"],
                    outcome=row_payload["outcome"],
                    reward=row_payload["reward"],
                    latency_ms=row_payload["latency_ms"],
                    recovery_count=row_payload["recovery_count"],
                    payload_json=_json_dumps(row_payload["payload"]),
                    created_at=row_payload["created_at"],
                )
            )
            self._merge_global_tool_reliability(
                conn,
                scope="global",
                tool_name=f"{row_payload['category']}:{row_payload['entity_id']}",
                success=row_payload["reward"] >= 0.0 and row_payload["outcome"] not in {"failed", "error", "rejected"},
                reward=row_payload["reward"],
                latency_ms=row_payload["latency_ms"],
                metadata={"workspace_id": row_payload["workspace_id"]},
            )
            self._db._insert_audit_event(
                conn,
                workspace_id=row_payload["workspace_id"],
                event_type="learning.feedback.recorded",
                payload={
                    "feedback_id": feedback_id,
                    "user_id": row_payload["user_id"],
                    "category": row_payload["category"],
                    "entity_id": row_payload["entity_id"],
                    "outcome": row_payload["outcome"],
                },
            )
            self._db.outbox.enqueue(
                conn,
                workspace_id=row_payload["workspace_id"],
                aggregate_type="learning_feedback",
                aggregate_id=feedback_id,
                event_type="learning.feedback.recorded",
                payload={
                    "feedback_id": feedback_id,
                    "workspace_id": row_payload["workspace_id"],
                    "user_id": row_payload["user_id"],
                    "category": row_payload["category"],
                    "entity_id": row_payload["entity_id"],
                    "outcome": row_payload["outcome"],
                    "reward": row_payload["reward"],
                },
            )
        return row_payload

    def list_operational_feedback(
        self,
        *,
        workspace_id: str = "",
        user_id: str = "",
        category: str = "",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        with self._db.local_engine.begin() as conn:
            stmt = select(operational_feedback_table)
            if workspace_id:
                stmt = stmt.where(operational_feedback_table.c.workspace_id == str(workspace_id))
            if user_id:
                stmt = stmt.where(operational_feedback_table.c.user_id == str(user_id))
            if category:
                stmt = stmt.where(operational_feedback_table.c.category == str(category))
            rows = conn.execute(
                stmt.order_by(operational_feedback_table.c.created_at.desc()).limit(max(1, int(limit or 50)))
            ).mappings().all()
        return [self._db._decode_operational_feedback_row(row) for row in rows]

    def get_global_tool_reliability(self, *, tool_name: str, scope: str = "global") -> dict[str, Any] | None:
        stat_id = self._stat_id(scope, tool_name)
        with self._db.local_engine.begin() as conn:
            row = conn.execute(
                select(global_tool_reliability_table)
                .where(global_tool_reliability_table.c.stat_id == stat_id)
            ).mappings().first()
        return self._db._decode_global_tool_reliability_row(row) if row else None

    def list_global_tool_reliability(self, *, scope: str = "global", limit: int = 50) -> list[dict[str, Any]]:
        with self._db.local_engine.begin() as conn:
            rows = conn.execute(
                select(global_tool_reliability_table)
                .where(global_tool_reliability_table.c.scope == str(scope or "global"))
                .order_by(global_tool_reliability_table.c.updated_at.desc())
                .limit(max(1, int(limit or 50)))
            ).mappings().all()
        return [self._db._decode_global_tool_reliability_row(row) for row in rows]

    def _merge_global_tool_reliability(
        self,
        conn: Connection,
        *,
        scope: str,
        tool_name: str,
        success: bool,
        reward: float,
        latency_ms: float,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        stat_id = self._stat_id(scope, tool_name)
        row = conn.execute(
            select(global_tool_reliability_table).where(global_tool_reliability_table.c.stat_id == stat_id)
        ).mappings().first()
        success_count = int(row["success_count"] or 0) if row else 0
        failure_count = int(row["failure_count"] or 0) if row else 0
        sample_count = int(row["sample_count"] or 0) if row else 0
        avg_reward = float(row["avg_reward"] or 0.0) if row else 0.0
        avg_latency = float(row["avg_latency_ms"] or 0.0) if row else 0.0
        if success:
            success_count += 1
        else:
            failure_count += 1
        sample_count += 1
        avg_reward = ((avg_reward * (sample_count - 1)) + float(reward or 0.0)) / max(sample_count, 1)
        avg_latency = ((avg_latency * (sample_count - 1)) + float(latency_ms or 0.0)) / max(sample_count, 1)
        values = {
            "stat_id": stat_id,
            "scope": str(scope or "global"),
            "tool_name": str(tool_name or "unknown"),
            "success_count": success_count,
            "failure_count": failure_count,
            "sample_count": sample_count,
            "avg_reward": avg_reward,
            "avg_latency_ms": avg_latency,
            "metadata_json": _json_dumps(dict(metadata or {})),
            "updated_at": _now(),
        }
        if row:
            conn.execute(
                global_tool_reliability_table.update()
                .where(global_tool_reliability_table.c.stat_id == stat_id)
                .values(**values)
            )
        else:
                conn.execute(global_tool_reliability_table.insert().values(**values))
class PrivacyRepository:
    def __init__(self, db: "RuntimeDatabase") -> None:
        self._db = db

    @staticmethod
    def _workspace_id(workspace_id: str) -> str:
        return str(workspace_id or "local-workspace").strip() or "local-workspace"

    @staticmethod
    def _user_id(user_id: str) -> str:
        return str(user_id or "local-user").strip() or "local-user"

    @staticmethod
    def _policy_row(row: dict[str, Any] | None) -> dict[str, Any]:
        if not row:
            return build_workspace_data_policy().to_dict()
        return {
            "workspace_id": str(row.get("workspace_id") or "local-workspace"),
            "allow_personal_data_learning": bool(row.get("allow_personal_data_learning", False)),
            "allow_workspace_data_learning": bool(row.get("allow_workspace_data_learning", True)),
            "allow_operational_data_learning": bool(row.get("allow_operational_data_learning", True)),
            "allow_public_data_learning": bool(row.get("allow_public_data_learning", True)),
            "allow_secret_data_learning": bool(row.get("allow_secret_data_learning", False)),
            "allow_global_aggregation": bool(row.get("allow_global_aggregation", True)),
            "redact_personal_data": bool(row.get("redact_personal_data", True)),
            "redact_secret_data": bool(row.get("redact_secret_data", True)),
            "learning_scope": str(row.get("learning_scope") or "workspace"),
            "retention_policy": _json_loads(row.get("retention_policy_json"), {}),
            "metadata": _json_loads(row.get("metadata_json"), {}),
            "updated_at": float(row.get("updated_at") or 0.0),
        }

    @staticmethod
    def _consent_row(row: dict[str, Any] | None) -> dict[str, Any]:
        if not row:
            return {}
        return {
            "consent_id": str(row.get("consent_id") or ""),
            "workspace_id": str(row.get("workspace_id") or "local-workspace"),
            "user_id": str(row.get("user_id") or "local-user"),
            "scope": str(row.get("scope") or "workspace"),
            "granted": bool(row.get("granted", False)),
            "source": str(row.get("source") or "runtime"),
            "expires_at": float(row.get("expires_at") or 0.0),
            "metadata": _json_loads(row.get("metadata_json"), {}),
            "created_at": float(row.get("created_at") or 0.0),
            "updated_at": float(row.get("updated_at") or 0.0),
        }

    @staticmethod
    def _decision_row(row: dict[str, Any] | None) -> dict[str, Any]:
        if not row:
            return {}
        return {
            "decision_id": str(row.get("decision_id") or ""),
            "workspace_id": str(row.get("workspace_id") or "local-workspace"),
            "user_id": str(row.get("user_id") or "local-user"),
            "source_kind": str(row.get("source_kind") or "runtime"),
            "classification": str(row.get("classification") or "operational"),
            "learning_scope": str(row.get("learning_scope") or "workspace"),
            "shared_learning_eligible": bool(row.get("shared_learning_eligible", False)),
            "redacted": bool(row.get("redacted", True)),
            "reason": str(row.get("reason") or ""),
            "payload": _json_loads(row.get("payload_json"), {}),
            "text": str(row.get("text") or ""),
            "retention_policy": _json_loads(row.get("retention_policy_json"), {}),
            "consent_policy": _json_loads(row.get("consent_policy_json"), {}),
            "metadata": _json_loads(row.get("metadata_json"), {}),
            "created_at": float(row.get("created_at") or 0.0),
        }

    @staticmethod
    def _entry_row(row: dict[str, Any] | None) -> dict[str, Any]:
        if not row:
            return {}
        return {
            "entry_id": str(row.get("entry_id") or ""),
            "workspace_id": str(row.get("workspace_id") or "local-workspace"),
            "user_id": str(row.get("user_id") or "local-user"),
            "source_kind": str(row.get("source_kind") or "runtime"),
            "source_id": str(row.get("source_id") or ""),
            "classification": str(row.get("classification") or "operational"),
            "learning_scope": str(row.get("learning_scope") or "workspace"),
            "shared_learning_eligible": bool(row.get("shared_learning_eligible", False)),
            "redacted": bool(row.get("redacted", True)),
            "text": str(row.get("text") or ""),
            "payload": _json_loads(row.get("payload_json"), {}),
            "retention_policy": _json_loads(row.get("retention_policy_json"), {}),
            "consent_policy": _json_loads(row.get("consent_policy_json"), {}),
            "metadata": _json_loads(row.get("metadata_json"), {}),
            "created_at": float(row.get("created_at") or 0.0),
        }

    def get_workspace_policy(self, *, workspace_id: str = "local-workspace") -> dict[str, Any]:
        wid = self._workspace_id(workspace_id)
        with self._db.local_engine.begin() as conn:
            row = conn.execute(
                select(workspace_data_policies_table).where(workspace_data_policies_table.c.workspace_id == wid)
            ).mappings().first()
        return self._policy_row(dict(row)) if row else build_workspace_data_policy(wid).to_dict()

    def set_workspace_policy(
        self,
        *,
        workspace_id: str = "local-workspace",
        policy: WorkspaceDataPolicy | dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        **overrides: Any,
    ) -> dict[str, Any]:
        wid = self._workspace_id(workspace_id)
        payload = policy.to_dict() if hasattr(policy, "to_dict") else dict(policy or {})
        payload.update({key: value for key, value in overrides.items() if value is not None})
        retention_payload = payload.get("retention_policy") if isinstance(payload.get("retention_policy"), dict) else {}
        retention = RetentionPolicy(
            retention_class=str(retention_payload.get("retention_class") or "standard"),
            ttl_days=int(retention_payload.get("ttl_days") or 365),
            redact_personal_data=bool(retention_payload.get("redact_personal_data", True)),
            redact_secret_data=bool(retention_payload.get("redact_secret_data", True)),
            workspace_only=bool(retention_payload.get("workspace_only", True)),
            legal_hold=bool(retention_payload.get("legal_hold", False)),
            metadata=dict(retention_payload.get("metadata") or {}),
        )
        row = {
            "workspace_id": wid,
            "allow_personal_data_learning": bool(payload.get("allow_personal_data_learning", False)),
            "allow_workspace_data_learning": bool(payload.get("allow_workspace_data_learning", True)),
            "allow_operational_data_learning": bool(payload.get("allow_operational_data_learning", True)),
            "allow_public_data_learning": bool(payload.get("allow_public_data_learning", True)),
            "allow_secret_data_learning": bool(payload.get("allow_secret_data_learning", False)),
            "allow_global_aggregation": bool(payload.get("allow_global_aggregation", True)),
            "redact_personal_data": bool(payload.get("redact_personal_data", True)),
            "redact_secret_data": bool(payload.get("redact_secret_data", True)),
            "learning_scope": str(payload.get("learning_scope") or "workspace"),
            "retention_policy_json": _json_dumps(retention.to_dict()),
            "metadata_json": _json_dumps(dict(metadata or payload.get("metadata") or {})),
            "updated_at": _now(),
        }
        with self._db.local_engine.begin() as conn:
            existing = conn.execute(
                select(workspace_data_policies_table.c.workspace_id).where(workspace_data_policies_table.c.workspace_id == wid)
            ).first()
            if existing:
                conn.execute(
                    workspace_data_policies_table.update()
                    .where(workspace_data_policies_table.c.workspace_id == wid)
                    .values(**row)
                )
            else:
                conn.execute(workspace_data_policies_table.insert().values(**row))
            self._db._insert_audit_event(
                conn,
                workspace_id=wid,
                event_type="privacy.workspace_policy.updated",
                payload={"workspace_id": wid, "learning_scope": row["learning_scope"]},
            )
        return self.get_workspace_policy(workspace_id=wid)

    def record_consent(
        self,
        *,
        workspace_id: str = "local-workspace",
        user_id: str = "local-user",
        scope: str = "workspace",
        granted: bool = False,
        source: str = "runtime",
        expires_at: float = 0.0,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        wid = self._workspace_id(workspace_id)
        uid = self._user_id(user_id)
        consent_id = f"consent_{uuid.uuid4().hex[:12]}"
        row = {
            "consent_id": consent_id,
            "workspace_id": wid,
            "user_id": uid,
            "scope": str(scope or "workspace"),
            "granted": bool(granted),
            "source": str(source or "runtime"),
            "expires_at": float(expires_at or 0.0),
            "metadata_json": _json_dumps(dict(metadata or {})),
            "created_at": _now(),
            "updated_at": _now(),
        }
        with self._db.local_engine.begin() as conn:
            conn.execute(consent_records_table.insert().values(**row))
            self._db._insert_audit_event(
                conn,
                workspace_id=wid,
                event_type="privacy.consent.recorded",
                payload={"consent_id": consent_id, "user_id": uid, "scope": row["scope"], "granted": row["granted"]},
            )
        return self._consent_row(row)

    def record_privacy_decision(
        self,
        *,
        workspace_id: str = "local-workspace",
        user_id: str = "local-user",
        source_kind: str = "runtime",
        text: str = "",
        payload: Any = None,
        metadata: dict[str, Any] | None = None,
        consent_policy: ConsentPolicy | dict[str, Any] | None = None,
        workspace_policy: WorkspaceDataPolicy | dict[str, Any] | None = None,
        classification: DataClassification | str | None = None,
    ) -> dict[str, Any]:
        policy_obj = workspace_policy if isinstance(workspace_policy, WorkspaceDataPolicy) else (
            WorkspaceDataPolicy(**dict(workspace_policy or {}, workspace_id=self._workspace_id(workspace_id))) if isinstance(workspace_policy, dict) else None
        )
        consent_obj = consent_policy if isinstance(consent_policy, ConsentPolicy) else (
            ConsentPolicy(**dict(consent_policy or {})) if isinstance(consent_policy, dict) else None
        )
        decision = build_privacy_decision(
            workspace_id=self._workspace_id(workspace_id),
            user_id=self._user_id(user_id),
            source_kind=source_kind,
            text=text,
            payload=payload,
            metadata=metadata,
            consent_policy=consent_obj,
            workspace_policy=policy_obj,
            classification=classification,
        )
        row = {
            "decision_id": decision.decision_id,
            "workspace_id": decision.workspace_id,
            "user_id": decision.user_id,
            "source_kind": decision.source_kind,
            "classification": decision.classification.value,
            "learning_scope": decision.learning_scope,
            "shared_learning_eligible": bool(decision.shared_learning_eligible),
            "redacted": bool(decision.redacted),
            "reason": decision.reason,
            "payload_json": _json_dumps(decision.payload),
            "text": decision.text,
            "retention_policy_json": _json_dumps(decision.retention_policy.to_dict()),
            "consent_policy_json": _json_dumps(decision.consent_policy.to_dict()),
            "metadata_json": _json_dumps(dict(decision.metadata or {})),
            "created_at": decision.created_at,
        }
        with self._db.local_engine.begin() as conn:
            conn.execute(privacy_decisions_table.insert().values(**row))
            self._db._insert_audit_event(
                conn,
                workspace_id=decision.workspace_id,
                event_type="privacy.decision.recorded",
                payload={"decision_id": decision.decision_id, "classification": decision.classification.value, "scope": decision.learning_scope},
            )
        return self._decision_row(row)

    def record_dataset_entry(
        self,
        *,
        workspace_id: str = "local-workspace",
        user_id: str = "local-user",
        source_kind: str = "runtime",
        source_id: str = "",
        text: str = "",
        payload: Any = None,
        metadata: dict[str, Any] | None = None,
        consent_policy: ConsentPolicy | dict[str, Any] | None = None,
        workspace_policy: WorkspaceDataPolicy | dict[str, Any] | None = None,
        classification: DataClassification | str | None = None,
    ) -> dict[str, Any]:
        policy_obj = workspace_policy if isinstance(workspace_policy, WorkspaceDataPolicy) else (
            WorkspaceDataPolicy(**dict(workspace_policy or {}, workspace_id=self._workspace_id(workspace_id))) if isinstance(workspace_policy, dict) else None
        )
        consent_obj = consent_policy if isinstance(consent_policy, ConsentPolicy) else (
            ConsentPolicy(**dict(consent_policy or {})) if isinstance(consent_policy, dict) else None
        )
        entry = build_dataset_entry(
            workspace_id=self._workspace_id(workspace_id),
            user_id=self._user_id(user_id),
            source_kind=source_kind,
            source_id=source_id,
            text=text,
            payload=payload,
            metadata=metadata,
            consent_policy=consent_obj,
            workspace_policy=policy_obj,
            classification=classification,
        )
        row = {
            "entry_id": entry.entry_id,
            "workspace_id": entry.workspace_id,
            "user_id": entry.user_id,
            "source_kind": entry.source_kind,
            "source_id": entry.source_id,
            "classification": entry.classification.value,
            "learning_scope": entry.learning_scope,
            "shared_learning_eligible": bool(entry.shared_learning_eligible),
            "redacted": bool(entry.redacted),
            "text": entry.text,
            "payload_json": _json_dumps(entry.payload),
            "retention_policy_json": _json_dumps(entry.retention_policy.to_dict()),
            "consent_policy_json": _json_dumps(entry.consent_policy.to_dict()),
            "metadata_json": _json_dumps(dict(entry.metadata or {})),
            "created_at": entry.created_at,
        }
        with self._db.local_engine.begin() as conn:
            conn.execute(dataset_entries_table.insert().values(**row))
            self._db._insert_audit_event(
                conn,
                workspace_id=entry.workspace_id,
                event_type="privacy.dataset_entry.recorded",
                payload={"entry_id": entry.entry_id, "classification": entry.classification.value, "scope": entry.learning_scope},
            )
        return self._entry_row(row)

    def list_dataset_entries(
        self,
        *,
        workspace_id: str = "",
        user_id: str = "",
        classification: str = "",
        learning_scope: str = "",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        with self._db.local_engine.begin() as conn:
            stmt = select(dataset_entries_table)
            if workspace_id:
                stmt = stmt.where(dataset_entries_table.c.workspace_id == self._workspace_id(workspace_id))
            if user_id:
                stmt = stmt.where(dataset_entries_table.c.user_id == self._user_id(user_id))
            if classification:
                stmt = stmt.where(dataset_entries_table.c.classification == str(classification).strip().lower())
            if learning_scope:
                stmt = stmt.where(dataset_entries_table.c.learning_scope == str(learning_scope).strip().lower())
            rows = conn.execute(
                stmt.order_by(dataset_entries_table.c.created_at.desc()).limit(max(1, int(limit or 100)))
            ).mappings().all()
        return [self._entry_row(dict(row)) for row in rows]

    def list_privacy_decisions(
        self,
        *,
        workspace_id: str = "",
        user_id: str = "",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        with self._db.local_engine.begin() as conn:
            stmt = select(privacy_decisions_table)
            if workspace_id:
                stmt = stmt.where(privacy_decisions_table.c.workspace_id == self._workspace_id(workspace_id))
            if user_id:
                stmt = stmt.where(privacy_decisions_table.c.user_id == self._user_id(user_id))
            rows = conn.execute(
                stmt.order_by(privacy_decisions_table.c.created_at.desc()).limit(max(1, int(limit or 100)))
            ).mappings().all()
        return [self._decision_row(dict(row)) for row in rows]

    def summary(self, *, workspace_id: str = "local-workspace", user_id: str = "local-user", limit: int = 20) -> dict[str, Any]:
        wid = self._workspace_id(workspace_id)
        uid = self._user_id(user_id)
        policy = self.get_workspace_policy(workspace_id=wid)
        with self._db.local_engine.begin() as conn:
            entry_total_row = conn.execute(
                select(func.count(dataset_entries_table.c.entry_id))
                .where(dataset_entries_table.c.workspace_id == wid)
                .where(dataset_entries_table.c.user_id == uid)
            ).first()
            decision_total_row = conn.execute(
                select(func.count(privacy_decisions_table.c.decision_id))
                .where(privacy_decisions_table.c.workspace_id == wid)
                .where(privacy_decisions_table.c.user_id == uid)
            ).first()
            counts = conn.execute(
                select(
                    dataset_entries_table.c.classification,
                    func.count(dataset_entries_table.c.entry_id),
                )
                .where(dataset_entries_table.c.workspace_id == wid)
                .where(dataset_entries_table.c.user_id == uid)
                .group_by(dataset_entries_table.c.classification)
            ).all()
            scope_counts = conn.execute(
                select(
                    dataset_entries_table.c.learning_scope,
                    func.count(dataset_entries_table.c.entry_id),
                )
                .where(dataset_entries_table.c.workspace_id == wid)
                .where(dataset_entries_table.c.user_id == uid)
                .group_by(dataset_entries_table.c.learning_scope)
            ).all()
            decision_counts = conn.execute(
                select(
                    privacy_decisions_table.c.classification,
                    func.count(privacy_decisions_table.c.decision_id),
                )
                .where(privacy_decisions_table.c.workspace_id == wid)
                .where(privacy_decisions_table.c.user_id == uid)
                .group_by(privacy_decisions_table.c.classification)
            ).all()
            decision_scope_counts = conn.execute(
                select(
                    privacy_decisions_table.c.learning_scope,
                    func.count(privacy_decisions_table.c.decision_id),
                )
                .where(privacy_decisions_table.c.workspace_id == wid)
                .where(privacy_decisions_table.c.user_id == uid)
                .group_by(privacy_decisions_table.c.learning_scope)
            ).all()
            recent = conn.execute(
                select(dataset_entries_table)
                .where(dataset_entries_table.c.workspace_id == wid)
                .where(dataset_entries_table.c.user_id == uid)
                .order_by(dataset_entries_table.c.created_at.desc())
                .limit(max(1, int(limit or 20)))
            ).mappings().all()
            recent_decisions = conn.execute(
                select(privacy_decisions_table)
                .where(privacy_decisions_table.c.workspace_id == wid)
                .where(privacy_decisions_table.c.user_id == uid)
                .order_by(privacy_decisions_table.c.created_at.desc())
                .limit(max(1, int(limit or 20)))
            ).mappings().all()
            consent_row = conn.execute(
                select(consent_records_table)
                .where(consent_records_table.c.workspace_id == wid)
                .where(consent_records_table.c.user_id == uid)
                .order_by(consent_records_table.c.updated_at.desc())
                ).mappings().first()
        classification_counts: dict[str, int] = {}
        for source_rows in (counts, decision_counts):
            for row in source_rows:
                key = str(row[0])
                classification_counts[key] = classification_counts.get(key, 0) + int(row[1] or 0)
        learning_scope_counts: dict[str, int] = {}
        for source_rows in (scope_counts, decision_scope_counts):
            for row in source_rows:
                key = str(row[0])
                learning_scope_counts[key] = learning_scope_counts.get(key, 0) + int(row[1] or 0)
        recent_entries = [self._entry_row(dict(row)) for row in recent]
        recent_entries.extend(
            {
                "entry_id": str(row.get("decision_id") or ""),
                "workspace_id": str(row.get("workspace_id") or wid),
                "user_id": str(row.get("user_id") or uid),
                "source_kind": str(row.get("source_kind") or "runtime"),
                "source_id": str(row.get("decision_id") or ""),
                "classification": str(row.get("classification") or "operational"),
                "learning_scope": str(row.get("learning_scope") or "workspace"),
                "shared_learning_eligible": bool(row.get("shared_learning_eligible", False)),
                "redacted": bool(row.get("redacted", True)),
                "text": str(row.get("text") or ""),
                "payload": _json_loads(row.get("payload_json"), {}),
                "retention_policy": _json_loads(row.get("retention_policy_json"), {}),
                "consent_policy": _json_loads(row.get("consent_policy_json"), {}),
                "metadata": _json_loads(row.get("metadata_json"), {}),
                "created_at": float(row.get("created_at") or 0.0),
            }
            for row in recent_decisions
        )
        recent_entries.sort(key=lambda row: float(row.get("created_at") or 0.0), reverse=True)
        recent_entries = recent_entries[: max(1, int(limit or 20))]
        learned_from = []
        if classification_counts.get("workspace"):
            learned_from.append("workspace artifacts")
        if classification_counts.get("operational"):
            learned_from.append("operational signals")
        if classification_counts.get("public"):
            learned_from.append("public references")
        excluded = ["personal data", "secret material"]
        if not policy.get("allow_global_aggregation", True):
            excluded.append("global aggregation")
        return {
            "workspace_id": wid,
            "user_id": uid,
            "policy": policy,
            "consent": self._consent_row(dict(consent_row) if consent_row else None),
            "classification_counts": classification_counts,
            "learning_scope_counts": learning_scope_counts,
            "shared_learning_eligible": int(sum(1 for row in recent_entries if bool(row.get("shared_learning_eligible")))),
            "redacted_entries": int(sum(1 for row in recent_entries if bool(row.get("redacted")))),
            "total_entries": int((entry_total_row[0] if entry_total_row else 0) + (decision_total_row[0] if decision_total_row else 0)),
            "recent_entries": recent_entries,
            "what_is_learned": learned_from,
            "what_is_excluded": excluded,
            "retention_policy": policy.get("retention_policy", {}),
        }

    def export_bundle(
        self,
        *,
        workspace_id: str = "local-workspace",
        user_id: str = "local-user",
        limit: int = 100,
    ) -> dict[str, Any]:
        wid = self._workspace_id(workspace_id)
        uid = self._user_id(user_id)
        summary = self.summary(workspace_id=wid, user_id=uid, limit=min(max(20, int(limit or 100)), 500))
        return {
            "workspace_id": wid,
            "user_id": uid,
            "summary": summary,
            "privacy_decisions": self.list_privacy_decisions(workspace_id=wid, user_id=uid, limit=limit),
            "dataset_entries": self.list_dataset_entries(workspace_id=wid, user_id=uid, limit=limit),
        }

    def delete_user_data(self, user_id: str, *, workspace_id: str = "") -> dict[str, Any]:
        uid = self._user_id(user_id)
        wid = self._workspace_id(workspace_id or "")
        deleted: dict[str, int] = {}
        with self._db.local_engine.begin() as conn:
            for table in (
                dataset_entries_table,
                privacy_decisions_table,
                consent_records_table,
                operational_feedback_table,
                user_preference_profiles_table,
                local_user_sessions_table,
                local_users_table,
            ):
                cursor = conn.execute(table.delete().where(table.c.user_id == uid))
                deleted[table.name] = int(cursor.rowcount or 0)
            self._db._insert_audit_event(
                conn,
                workspace_id=wid,
                event_type="privacy.user_data.deleted",
                payload={"user_id": uid, "workspace_id": wid, "deleted": deleted},
            )
        return {"user_id": uid, "workspace_id": wid, "deleted": deleted}


class LocalAuthRepository:
    _ITERATIONS = 200_000

    def __init__(self, db: "RuntimeDatabase") -> None:
        self._db = db

    @staticmethod
    def _normalize_email(email: str) -> str:
        return str(email or "").strip().lower()

    @staticmethod
    def _default_workspace_id(email: str) -> str:
        normalized_email = str(email or "").strip().lower()
        digest = hashlib.sha256(normalized_email.encode("utf-8")).hexdigest()[:16]
        return f"ws_{digest}"

    @classmethod
    def _hash_password(cls, password: str, salt: str) -> str:
        return hashlib.pbkdf2_hmac(
            "sha256",
            str(password or "").encode("utf-8"),
            bytes.fromhex(salt),
            cls._ITERATIONS,
        ).hex()

    def upsert_user(
        self,
        *,
        email: str,
        password: str,
        display_name: str = "",
        workspace_id: str = "",
        status: str = "active",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_email = self._normalize_email(email)
        if not normalized_email:
            raise ValueError("email required")
        if not str(password or ""):
            raise ValueError("password required")
        salt = os.urandom(16).hex()
        password_hash = self._hash_password(password, salt)
        now = _now()
        with self._db.local_engine.begin() as conn:
            explicit_workspace = str(workspace_id or "").strip()
            stmt = select(local_users_table).where(local_users_table.c.email == normalized_email)
            if explicit_workspace:
                stmt = stmt.where(local_users_table.c.workspace_id == explicit_workspace)
            else:
                stmt = stmt.order_by(local_users_table.c.updated_at.desc())
            existing = conn.execute(stmt).mappings().first()
            resolved_workspace = (
                explicit_workspace
                or str(existing["workspace_id"] if existing else "")
                or self._default_workspace_id(normalized_email)
            )
            row_values = {
                "workspace_id": resolved_workspace,
                "email": normalized_email,
                "display_name": str(display_name or normalized_email.split("@")[0]),
                "password_hash": password_hash,
                "password_salt": salt,
                "status": str(status or "active"),
                "metadata_json": _json_dumps(dict(metadata or {})),
                "updated_at": now,
            }
            if existing:
                user_id = str(existing["user_id"])
                conn.execute(
                    local_users_table.update()
                    .where(local_users_table.c.user_id == user_id)
                    .values(**row_values)
                )
            else:
                user_id = f"user_{uuid.uuid4().hex[:12]}"
                conn.execute(
                    local_users_table.insert().values(
                        user_id=user_id,
                        created_at=now,
                        **row_values,
                    )
                )
            self._db._insert_audit_event(
                conn,
                workspace_id=resolved_workspace,
                event_type="auth.local_user.upserted",
                payload={"user_id": user_id, "email": normalized_email},
            )
            row = conn.execute(
                select(local_users_table).where(local_users_table.c.user_id == user_id)
            ).mappings().first()
        decoded = self._db._decode_local_user_row(dict(row or {})) if row else {}
        if decoded:
            role_hint = str((metadata or {}).get("workspace_role") or "member")
            try:
                self._db.access.ensure_membership(
                    workspace_id=decoded["workspace_id"],
                    actor_id=decoded["user_id"],
                    role=role_hint,
                    status="active",
                )
            except Exception:
                pass
        return decoded

    def bootstrap_owner(
        self,
        *,
        email: str,
        password: str,
        display_name: str = "",
        workspace_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = self.upsert_user(
            email=email,
            password=password,
            display_name=display_name,
            workspace_id=workspace_id,
            status="active",
            metadata={**dict(metadata or {}), "workspace_role": "owner", "bootstrap_source": "explicit_setup"},
        )
        if payload:
            self._db.access.ensure_workspace(
                payload["workspace_id"],
                display_name=str(display_name or email.split("@")[0] or payload["workspace_id"]),
            )
            self._db.access.ensure_membership(
                workspace_id=payload["workspace_id"],
                actor_id=payload["user_id"],
                role="owner",
                status="active",
            )
            self._db.access.assign_seat(
                workspace_id=payload["workspace_id"],
                actor_id=payload["user_id"],
                assigned_by=payload["user_id"],
            )
        return payload

    def authenticate_user(
        self,
        *,
        email: str,
        password: str,
        workspace_id: str = "",
    ) -> dict[str, Any] | None:
        normalized_email = self._normalize_email(email)
        with self._db.local_engine.begin() as conn:
            stmt = select(local_users_table).where(
                local_users_table.c.email == normalized_email,
                local_users_table.c.status == "active",
            )
            if str(workspace_id or "").strip():
                stmt = stmt.where(local_users_table.c.workspace_id == str(workspace_id or "").strip())
            else:
                stmt = stmt.order_by(local_users_table.c.updated_at.desc())
            row = conn.execute(stmt).mappings().first()
            if not row:
                self._db._insert_audit_event(
                    conn,
                    workspace_id=str(workspace_id or self._default_workspace_id(normalized_email)),
                    event_type="auth.local_user.failed",
                    payload={"email": normalized_email, "reason": "not_found"},
                )
                return None
            expected = self._hash_password(password, str(row["password_salt"] or ""))
            if not hmac.compare_digest(expected, str(row["password_hash"] or "")):
                self._db._insert_audit_event(
                    conn,
                    workspace_id=str(row["workspace_id"] or self._default_workspace_id(normalized_email)),
                    event_type="auth.local_user.failed",
                    payload={"email": normalized_email, "reason": "invalid_password"},
                )
                return None
            self._db._insert_audit_event(
                conn,
                workspace_id=str(row["workspace_id"] or self._default_workspace_id(normalized_email)),
                event_type="auth.local_user.authenticated",
                payload={"user_id": str(row["user_id"]), "email": normalized_email},
            )
        return self._db._decode_local_user_row(dict(row))


class LocalAuthSessionRepository:
    _DEFAULT_TTL_SECONDS = 60 * 60 * 24 * 30

    def __init__(self, db: "RuntimeDatabase") -> None:
        self._db = db

    @staticmethod
    def _hash_token(session_token: str) -> str:
        return hashlib.sha256(str(session_token or "").encode("utf-8")).hexdigest()

    def create_session(
        self,
        *,
        user: dict[str, Any],
        ttl_seconds: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], str]:
        user_id = str(user.get("user_id") or "").strip()
        workspace_id = str(user.get("workspace_id") or "").strip() or "local-workspace"
        if not user_id:
            raise ValueError("user_id required")
        now = _now()
        ttl = max(300, int(ttl_seconds or self._DEFAULT_TTL_SECONDS))
        session_token = f"elys_{secrets.token_urlsafe(32)}"
        token_hash = self._hash_token(session_token)
        session_id = f"session_{uuid.uuid4().hex[:12]}"
        values = {
            "session_id": session_id,
            "workspace_id": workspace_id,
            "user_id": user_id,
            "session_token_hash": token_hash,
            "status": "active",
            "expires_at": now + ttl,
            "last_seen_at": now,
            "metadata_json": _json_dumps(dict(metadata or {})),
            "created_at": now,
            "updated_at": now,
        }
        with self._db.local_engine.begin() as conn:
            conn.execute(local_user_sessions_table.insert().values(**values))
            self._db._insert_audit_event(
                conn,
                workspace_id=workspace_id,
                event_type="auth.session.created",
                payload={"session_id": session_id, "user_id": user_id},
            )
        return self._db._decode_local_session_row(values), session_token

    def resolve_session(self, session_token: str, *, touch: bool = True) -> dict[str, Any] | None:
        token_hash = self._hash_token(session_token)
        now = _now()
        with self._db.local_engine.begin() as conn:
            row = conn.execute(
                select(local_user_sessions_table, local_users_table)
                .join(local_users_table, local_users_table.c.user_id == local_user_sessions_table.c.user_id)
                .where(
                    local_user_sessions_table.c.session_token_hash == token_hash,
                    local_user_sessions_table.c.status == "active",
                    local_user_sessions_table.c.expires_at > now,
                    local_users_table.c.status == "active",
                )
            ).mappings().first()
            if not row:
                return None
            if touch:
                conn.execute(
                    local_user_sessions_table.update()
                    .where(local_user_sessions_table.c.session_id == str(row["session_id"]))
                    .values(last_seen_at=now, updated_at=now)
                )
            merged = dict(row)
            self._db._insert_audit_event(
                conn,
                workspace_id=str(row["workspace_id"] or "local-workspace"),
                event_type="auth.session.resolved",
                payload={"session_id": str(row["session_id"]), "user_id": str(row["user_id"])},
            )
            role = conn.execute(
                select(workspace_memberships_table.c.role)
                .where(workspace_memberships_table.c.workspace_id == str(row["workspace_id"] or "local-workspace"))
                .where(workspace_memberships_table.c.actor_id == str(row["user_id"] or ""))
                .where(workspace_memberships_table.c.status == "active")
            ).scalar()
            if role:
                merged["role"] = str(role)
        return self._db._decode_local_session_row(merged)

    def get_latest_session(
        self,
        *,
        user_ref: str = "",
        workspace_id: str = "",
    ) -> dict[str, Any] | None:
        now = _now()
        ref = str(user_ref or "").strip()
        workspace = str(workspace_id or "").strip()
        with self._db.local_engine.begin() as conn:
            stmt = (
                select(local_user_sessions_table, local_users_table)
                .join(local_users_table, local_users_table.c.user_id == local_user_sessions_table.c.user_id)
                .where(
                    local_user_sessions_table.c.status == "active",
                    local_user_sessions_table.c.expires_at > now,
                    local_users_table.c.status == "active",
                )
            )
            if workspace:
                stmt = stmt.where(local_user_sessions_table.c.workspace_id == workspace)
            if ref:
                stmt = stmt.where(
                    or_(
                        local_user_sessions_table.c.user_id == ref,
                        func.lower(local_users_table.c.email) == ref.lower(),
                    )
                )
            row = conn.execute(
                stmt.order_by(
                    local_user_sessions_table.c.last_seen_at.desc(),
                    local_user_sessions_table.c.updated_at.desc(),
                ).limit(1)
            ).mappings().first()
            if not row:
                return None
            merged = dict(row)
            role = conn.execute(
                select(workspace_memberships_table.c.role)
                .where(workspace_memberships_table.c.workspace_id == str(row["workspace_id"] or "local-workspace"))
                .where(workspace_memberships_table.c.actor_id == str(row["user_id"] or ""))
                .where(workspace_memberships_table.c.status == "active")
            ).scalar()
            if role:
                merged["role"] = str(role)
        return self._db._decode_local_session_row(merged)

    def revoke_session(self, session_token: str) -> bool:
        token_hash = self._hash_token(session_token)
        now = _now()
        with self._db.local_engine.begin() as conn:
            row = conn.execute(
                select(local_user_sessions_table).where(local_user_sessions_table.c.session_token_hash == token_hash)
            ).mappings().first()
            if not row:
                return False
            conn.execute(
                local_user_sessions_table.update()
                .where(local_user_sessions_table.c.session_id == str(row["session_id"]))
                .values(status="revoked", updated_at=now)
            )
            self._db._insert_audit_event(
                conn,
                workspace_id=str(row["workspace_id"] or "local-workspace"),
                event_type="auth.session.revoked",
                payload={"session_id": str(row["session_id"]), "user_id": str(row["user_id"])},
            )
        return True

    def update_metadata(self, session_id: str, metadata: dict[str, Any] | None = None) -> dict[str, Any] | None:
        sid = str(session_id or "").strip()
        if not sid:
            return None
        now = _now()
        with self._db.local_engine.begin() as conn:
            row = conn.execute(
                select(local_user_sessions_table, local_users_table)
                .join(local_users_table, local_users_table.c.user_id == local_user_sessions_table.c.user_id)
                .where(local_user_sessions_table.c.session_id == sid)
            ).mappings().first()
            if not row:
                return None
            current_metadata = _json_loads(row.get("metadata_json"), {})
            merged_metadata = {
                **dict(current_metadata or {}),
                **dict(metadata or {}),
            }
            conn.execute(
                local_user_sessions_table.update()
                .where(local_user_sessions_table.c.session_id == sid)
                .values(
                    metadata_json=_json_dumps(merged_metadata),
                    updated_at=now,
                )
            )
            self._db._insert_audit_event(
                conn,
                workspace_id=str(row["workspace_id"] or "local-workspace"),
                event_type="auth.session.updated",
                payload={
                    "session_id": sid,
                    "user_id": str(row["user_id"] or ""),
                    "metadata_keys": sorted(str(key) for key in dict(metadata or {}).keys())[:16],
                },
            )
            merged = dict(row)
            merged["metadata_json"] = _json_dumps(merged_metadata)
            merged["updated_at"] = now
        return self._db._decode_local_session_row(merged)


class ConversationRepository:
    def __init__(self, db: "RuntimeDatabase") -> None:
        self._db = db

    @staticmethod
    def _normalize_search_terms(query: str) -> list[str]:
        return ConversationRepository._extract_terms(query, limit=6)

    @staticmethod
    def _extract_terms(text: str, *, limit: int = 48) -> list[str]:
        matches = re.findall(r"[0-9a-zçğıöşü_]{2,}", str(text or "").strip().lower(), flags=re.IGNORECASE)
        out: list[str] = []
        seen: set[str] = set()
        for raw in matches:
            token = str(raw or "").strip().lower()
            if not token or token in seen:
                continue
            seen.add(token)
            out.append(token)
            if len(out) >= max(1, int(limit or 48)):
                break
        return out


    def _load_turn_context(
        self,
        conn: Connection,
        *,
        conversation_session_id: str,
        match_index: int,
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        user_row = conn.execute(
            select(conversation_messages_table)
            .where(conversation_messages_table.c.conversation_session_id == conversation_session_id)
            .where(conversation_messages_table.c.role == "user")
            .where(conversation_messages_table.c.message_index <= int(match_index))
            .order_by(conversation_messages_table.c.message_index.desc())
            .limit(1)
        ).mappings().first()
        assistant_row = conn.execute(
            select(conversation_messages_table)
            .where(conversation_messages_table.c.conversation_session_id == conversation_session_id)
            .where(conversation_messages_table.c.role == "assistant")
            .where(conversation_messages_table.c.message_index >= int(match_index))
            .order_by(conversation_messages_table.c.message_index.asc())
            .limit(1)
        ).mappings().first()
        return (
            self._db._decode_conversation_message_row(dict(user_row)) if user_row else None,
            self._db._decode_conversation_message_row(dict(assistant_row)) if assistant_row else None,
        )

    def ensure_session(
        self,
        *,
        workspace_id: str,
        actor_id: str,
        device_id: str = "local-device",
        channel: str = "cli",
        auth_session_id: str = "",
        client_session_id: str = "",
        conversation_session_id: str = "",
        parent_session_id: str = "",
        title: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        wid = str(workspace_id or "local-workspace").strip() or "local-workspace"
        aid = str(actor_id or "local-user").strip() or "local-user"
        device = str(device_id or "local-device").strip() or "local-device"
        channel_name = str(channel or "cli").strip() or "cli"
        auth_ref = str(auth_session_id or "").strip()
        client_ref = str(client_session_id or "").strip()
        requested_id = str(conversation_session_id or "").strip()
        now = _now()
        metadata_payload = dict(metadata or {})
        with self._db.local_engine.begin() as conn:
            row = None
            if requested_id:
                row = conn.execute(
                    select(conversation_sessions_table).where(
                        conversation_sessions_table.c.conversation_session_id == requested_id
                    )
                ).mappings().first()
            if row is None and auth_ref:
                row = conn.execute(
                    select(conversation_sessions_table)
                    .where(conversation_sessions_table.c.auth_session_id == auth_ref)
                    .order_by(conversation_sessions_table.c.updated_at.desc())
                    .limit(1)
                ).mappings().first()
            if row is None and client_ref:
                row = conn.execute(
                    select(conversation_sessions_table)
                    .where(conversation_sessions_table.c.client_session_id == client_ref)
                    .where(conversation_sessions_table.c.workspace_id == wid)
                    .where(conversation_sessions_table.c.actor_id == aid)
                    .order_by(conversation_sessions_table.c.updated_at.desc())
                    .limit(1)
                ).mappings().first()
            if row is None:
                row = conn.execute(
                    select(conversation_sessions_table)
                    .where(conversation_sessions_table.c.workspace_id == wid)
                    .where(conversation_sessions_table.c.actor_id == aid)
                    .where(conversation_sessions_table.c.device_id == device)
                    .where(conversation_sessions_table.c.channel == channel_name)
                    .where(conversation_sessions_table.c.status == "active")
                    .order_by(conversation_sessions_table.c.updated_at.desc())
                    .limit(1)
                ).mappings().first()

            if row:
                current_metadata = _json_loads(row.get("metadata_json"), {})
                merged_metadata = {
                    **dict(current_metadata or {}),
                    **metadata_payload,
                }
                updates = {
                    "workspace_id": wid,
                    "actor_id": aid,
                    "device_id": device,
                    "channel": channel_name,
                    "auth_session_id": auth_ref or str(row.get("auth_session_id") or ""),
                    "client_session_id": client_ref or str(row.get("client_session_id") or ""),
                    "parent_session_id": str(parent_session_id or row.get("parent_session_id") or ""),
                    "title": str(title or row.get("title") or ""),
                    "metadata_json": _json_dumps(merged_metadata),
                    "updated_at": now,
                }
                conn.execute(
                    conversation_sessions_table.update()
                    .where(conversation_sessions_table.c.conversation_session_id == str(row["conversation_session_id"]))
                    .values(**updates)
                )
                merged = dict(row)
                merged.update(updates)
                return self._db._decode_conversation_session_row(merged)

            values = {
                "conversation_session_id": requested_id or f"conv_{uuid.uuid4().hex[:16]}",
                "workspace_id": wid,
                "actor_id": aid,
                "device_id": device,
                "channel": channel_name,
                "auth_session_id": auth_ref,
                "client_session_id": client_ref,
                "parent_session_id": str(parent_session_id or "").strip(),
                "status": "active",
                "title": str(title or "").strip(),
                "summary_text": "",
                "message_count": 0,
                "token_input_total": 0,
                "token_output_total": 0,
                "metadata_json": _json_dumps(metadata_payload),
                "created_at": now,
                "updated_at": now,
                "closed_at": 0.0,
            }
            conn.execute(conversation_sessions_table.insert().values(**values))
            self._db._insert_audit_event(
                conn,
                workspace_id=wid,
                event_type="conversation.session.created",
                payload={
                    "conversation_session_id": values["conversation_session_id"],
                    "actor_id": aid,
                    "auth_session_id": auth_ref,
                    "channel": channel_name,
                },
            )
        return self._db._decode_conversation_session_row(values)

    def get_session(self, conversation_session_id: str) -> dict[str, Any] | None:
        session_id = str(conversation_session_id or "").strip()
        if not session_id:
            return None
        with self._db.local_engine.begin() as conn:
            row = conn.execute(
                select(conversation_sessions_table).where(
                    conversation_sessions_table.c.conversation_session_id == session_id
                )
            ).mappings().first()
        return self._db._decode_conversation_session_row(row) if row else None

    def list_recent_messages(self, conversation_session_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
        session_id = str(conversation_session_id or "").strip()
        if not session_id:
            return []
        query_limit = max(1, int(limit or 20))
        with self._db.local_engine.begin() as conn:
            rows = conn.execute(
                select(conversation_messages_table)
                .where(conversation_messages_table.c.conversation_session_id == session_id)
                .order_by(conversation_messages_table.c.message_index.desc())
                .limit(query_limit)
            ).mappings().all()
        decoded = [self._db._decode_conversation_message_row(dict(row)) for row in rows]
        decoded.reverse()
        return decoded

    def list_recent_turns(
        self,
        *,
        workspace_id: str,
        actor_id: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        wid = str(workspace_id or "local-workspace").strip() or "local-workspace"
        aid = str(actor_id or "local-user").strip() or "local-user"
        query_limit = max(1, int(limit or 10))
        with self._db.local_engine.begin() as conn:
            rows = conn.execute(
                select(
                    conversation_messages_table,
                    conversation_sessions_table.c.channel.label("session_channel"),
                    conversation_sessions_table.c.title.label("session_title"),
                )
                .join(
                    conversation_sessions_table,
                    conversation_sessions_table.c.conversation_session_id == conversation_messages_table.c.conversation_session_id,
                )
                .where(conversation_messages_table.c.workspace_id == wid)
                .where(conversation_messages_table.c.actor_id == aid)
                .where(conversation_messages_table.c.role == "assistant")
                .order_by(conversation_messages_table.c.created_at.desc())
                .limit(query_limit)
            ).mappings().all()

            out: list[dict[str, Any]] = []
            for row in rows:
                decoded = self._db._decode_conversation_message_row(dict(row))
                user_message, assistant_message = self._load_turn_context(
                    conn,
                    conversation_session_id=str(decoded.get("conversation_session_id") or ""),
                    match_index=int(decoded.get("message_index") or 0),
                )
                out.append(
                    {
                        "conversation_session_id": str(decoded.get("conversation_session_id") or ""),
                        "workspace_id": wid,
                        "channel": str(row.get("session_channel") or "cli"),
                        "title": str(row.get("session_title") or ""),
                        "user_message": str((user_message or {}).get("content") or ""),
                        "bot_response": str((assistant_message or {}).get("content") or decoded.get("content") or ""),
                        "action": str((assistant_message or {}).get("action") or decoded.get("action") or ""),
                        "success": bool((assistant_message or {}).get("success") if assistant_message else decoded.get("success")),
                        "timestamp": float((assistant_message or {}).get("created_at") or decoded.get("created_at") or 0.0),
                    }
                )
        return out

    def search_turns(
        self,
        *,
        workspace_id: str,
        actor_id: str,
        query: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        wid = str(workspace_id or "local-workspace").strip() or "local-workspace"
        aid = str(actor_id or "local-user").strip() or "local-user"
        terms = self._normalize_search_terms(query)
        if not terms:
            return []
        query_limit = max(1, int(limit or 10))
        fetch_limit = max(query_limit * 4, query_limit)
        with self._db.local_engine.begin() as conn:
            matched_ids_subquery = (
                select(conversation_message_terms_table.c.message_id)
                .where(conversation_message_terms_table.c.workspace_id == wid)
                .where(conversation_message_terms_table.c.actor_id == aid)
                .where(conversation_message_terms_table.c.term.in_(terms))
                .group_by(conversation_message_terms_table.c.message_id)
                .having(func.count(func.distinct(conversation_message_terms_table.c.term)) >= len(terms))
            )
            stmt = (
                select(
                    conversation_messages_table,
                    conversation_sessions_table.c.channel.label("session_channel"),
                    conversation_sessions_table.c.title.label("session_title"),
                )
                .join(
                    conversation_sessions_table,
                    conversation_sessions_table.c.conversation_session_id == conversation_messages_table.c.conversation_session_id,
                )
                .where(conversation_messages_table.c.workspace_id == wid)
                .where(conversation_messages_table.c.actor_id == aid)
                .where(conversation_messages_table.c.role.in_(("user", "assistant")))
                .where(conversation_messages_table.c.message_id.in_(matched_ids_subquery))
            )
            rows = conn.execute(
                stmt.order_by(conversation_messages_table.c.created_at.desc()).limit(fetch_limit)
            ).mappings().all()

            out: list[dict[str, Any]] = []
            seen: set[tuple[str, str, str]] = set()
            for row in rows:
                decoded = self._db._decode_conversation_message_row(dict(row))
                session_id = str(decoded.get("conversation_session_id") or "")
                user_message, assistant_message = self._load_turn_context(
                    conn,
                    conversation_session_id=session_id,
                    match_index=int(decoded.get("message_index") or 0),
                )
                dedupe_key = (
                    session_id,
                    str((user_message or {}).get("message_id") or ""),
                    str((assistant_message or {}).get("message_id") or ""),
                )
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                out.append(
                    {
                        "conversation_session_id": session_id,
                        "workspace_id": wid,
                        "channel": str(row.get("session_channel") or "cli"),
                        "title": str(row.get("session_title") or ""),
                        "matched_role": str(decoded.get("role") or ""),
                        "matched_content": str(decoded.get("content") or ""),
                        "user_message": str((user_message or {}).get("content") or ""),
                        "bot_response": str((assistant_message or {}).get("content") or ""),
                        "action": str((assistant_message or {}).get("action") or ""),
                        "success": bool((assistant_message or {}).get("success")) if assistant_message else False,
                        "timestamp": float(decoded.get("created_at") or 0.0),
                    }
                )
                if len(out) >= query_limit:
                    break
        return out

    def append_message(
        self,
        *,
        conversation_session_id: str,
        role: str,
        content: str,
        workspace_id: str = "",
        actor_id: str = "",
        run_id: str = "",
        action: str = "",
        success: bool | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        session_id = str(conversation_session_id or "").strip()
        if not session_id:
            raise ValueError("conversation_session_id required")
        role_name = str(role or "user").strip().lower() or "user"
        if role_name not in {"user", "assistant", "system", "tool"}:
            role_name = "user"
        now = _now()
        metadata_payload = dict(metadata or {})
        with self._db.local_engine.begin() as conn:
            session_row = conn.execute(
                select(conversation_sessions_table).where(
                    conversation_sessions_table.c.conversation_session_id == session_id
                )
            ).mappings().first()
            if not session_row:
                raise ValueError(f"conversation session not found: {session_id}")
            next_index = int(
                conn.execute(
                    select(func.max(conversation_messages_table.c.message_index)).where(
                        conversation_messages_table.c.conversation_session_id == session_id
                    )
                ).scalar()
                or 0
            ) + 1
            wid = str(workspace_id or session_row.get("workspace_id") or "local-workspace")
            aid = str(actor_id or session_row.get("actor_id") or "local-user")
            message_values = {
                "message_id": f"msg_{uuid.uuid4().hex[:16]}",
                "conversation_session_id": session_id,
                "workspace_id": wid,
                "actor_id": aid,
                "role": role_name,
                "content": str(content or ""),
                "message_index": next_index,
                "run_id": str(run_id or ""),
                "action": str(action or ""),
                "success": bool(success) if success is not None else False,
                "metadata_json": _json_dumps(metadata_payload),
                "created_at": now,
            }
            conn.execute(conversation_messages_table.insert().values(**message_values))
            term_rows = [
                {
                    "term_entry_id": f"term_{uuid.uuid4().hex[:16]}",
                    "message_id": message_values["message_id"],
                    "conversation_session_id": session_id,
                    "workspace_id": wid,
                    "actor_id": aid,
                    "role": role_name,
                    "term": term,
                    "created_at": now,
                }
                for term in self._extract_terms(message_values["content"])
            ]
            if term_rows:
                conn.execute(conversation_message_terms_table.insert(), term_rows)
            input_tokens = int(metadata_payload.get("input_tokens") or metadata_payload.get("prompt_tokens") or 0)
            output_tokens = int(metadata_payload.get("output_tokens") or metadata_payload.get("completion_tokens") or 0)
            conn.execute(
                conversation_sessions_table.update()
                .where(conversation_sessions_table.c.conversation_session_id == session_id)
                .values(
                    message_count=int(session_row.get("message_count") or 0) + 1,
                    token_input_total=int(session_row.get("token_input_total") or 0) + input_tokens,
                    token_output_total=int(session_row.get("token_output_total") or 0) + output_tokens,
                    updated_at=now,
                )
            )
            self._db._insert_audit_event(
                conn,
                workspace_id=wid,
                event_type="conversation.message.appended",
                payload={
                    "conversation_session_id": session_id,
                    "message_id": message_values["message_id"],
                    "role": role_name,
                    "actor_id": aid,
                },
            )
            updated_session = dict(session_row)
            updated_session["message_count"] = int(session_row.get("message_count") or 0) + 1
            updated_session["token_input_total"] = int(session_row.get("token_input_total") or 0) + input_tokens
            updated_session["token_output_total"] = int(session_row.get("token_output_total") or 0) + output_tokens
            updated_session["updated_at"] = now
        return self._db._decode_conversation_message_row(message_values)


class ChannelIdentityRepository:
    def __init__(self, db: "RuntimeDatabase") -> None:
        self._db = db

    @staticmethod
    def _link_id(workspace_id: str, channel: str, external_user_id: str) -> str:
        return f"channel::{str(workspace_id or 'local-workspace').strip()}::{str(channel or 'cli').strip().lower()}::{str(external_user_id or '').strip()}"

    def bind_identity(
        self,
        *,
        workspace_id: str = "local-workspace",
        channel: str,
        external_user_id: str,
        actor_id: str,
        display_name: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        wid = str(workspace_id or "local-workspace").strip() or "local-workspace"
        channel_name = str(channel or "cli").strip().lower() or "cli"
        external_id = str(external_user_id or "").strip()
        actor = str(actor_id or "").strip()
        if not external_id:
            raise ValueError("external_user_id required")
        if not actor:
            raise ValueError("actor_id required")
        link_id = self._link_id(wid, channel_name, external_id)
        now = _now()
        values = {
            "link_id": link_id,
            "workspace_id": wid,
            "channel": channel_name,
            "external_user_id": external_id,
            "actor_id": actor,
            "display_name": str(display_name or "").strip(),
            "metadata_json": _json_dumps(dict(metadata or {})),
            "created_at": now,
            "updated_at": now,
            "last_seen_at": now,
        }
        with self._db.local_engine.begin() as conn:
            existing = conn.execute(
                select(channel_identity_links_table).where(channel_identity_links_table.c.link_id == link_id)
            ).mappings().first()
            if existing:
                values["created_at"] = float(existing.get("created_at") or now)
                values["metadata_json"] = _json_dumps({**_json_loads(existing.get("metadata_json"), {}), **dict(metadata or {})})
                conn.execute(
                    channel_identity_links_table.update()
                    .where(channel_identity_links_table.c.link_id == link_id)
                    .values(**values)
                )
            else:
                conn.execute(channel_identity_links_table.insert().values(**values))
        return self._db._decode_channel_identity_link_row(values)

    def resolve_actor(
        self,
        *,
        workspace_id: str = "local-workspace",
        channel: str,
        external_user_id: str,
    ) -> dict[str, Any] | None:
        wid = str(workspace_id or "local-workspace").strip() or "local-workspace"
        channel_name = str(channel or "cli").strip().lower() or "cli"
        external_id = str(external_user_id or "").strip()
        if not external_id:
            return None
        with self._db.local_engine.begin() as conn:
            row = conn.execute(
                select(channel_identity_links_table)
                .where(channel_identity_links_table.c.workspace_id == wid)
                .where(channel_identity_links_table.c.channel == channel_name)
                .where(channel_identity_links_table.c.external_user_id == external_id)
                .limit(1)
            ).mappings().first()
            if row:
                conn.execute(
                    channel_identity_links_table.update()
                    .where(channel_identity_links_table.c.link_id == str(row["link_id"]))
                    .values(last_seen_at=_now(), updated_at=_now())
                )
        return self._db._decode_channel_identity_link_row(dict(row)) if row else None


class WorkspaceAccessRepository:
    _ALLOWED_ROLES = {"owner", "billing_admin", "security_admin", "operator", "viewer", "member"}

    def __init__(self, db: "RuntimeDatabase") -> None:
        self._db = db

    @staticmethod
    def _normalize_role(role: str) -> str:
        normalized = str(role or "member").strip().lower() or "member"
        return normalized if normalized in WorkspaceAccessRepository._ALLOWED_ROLES else "member"

    def ensure_workspace(self, workspace_id: str, *, display_name: str = "", metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        wid = str(workspace_id or "local-workspace").strip() or "local-workspace"
        values = {
            "workspace_id": wid,
            "display_name": str(display_name or wid),
            "status": "active",
            "metadata_json": _json_dumps(dict(metadata or {})),
            "updated_at": _now(),
        }
        with self._db.local_engine.begin() as conn:
            existing = conn.execute(
                select(workspaces_table.c.workspace_id).where(workspaces_table.c.workspace_id == wid)
            ).first()
            if existing:
                conn.execute(
                    workspaces_table.update()
                    .where(workspaces_table.c.workspace_id == wid)
                    .values(**values)
                )
            else:
                conn.execute(workspaces_table.insert().values(**values))
            self._db._insert_audit_event(
                conn,
                workspace_id=wid,
                event_type="workspace.updated",
                payload={"workspace_id": wid, "display_name": values["display_name"], "status": values["status"]},
            )
            self._db.outbox.enqueue(
                conn,
                workspace_id=wid,
                aggregate_type="workspace",
                aggregate_id=wid,
                event_type="workspace.updated",
                payload={"workspace_id": wid, "display_name": values["display_name"], "status": values["status"], "metadata": _json_loads(values["metadata_json"], {})},
            )
        return self._db._decode_workspace_row(values)

    def get_workspace(self, workspace_id: str) -> dict[str, Any] | None:
        wid = str(workspace_id or "local-workspace").strip() or "local-workspace"
        with self._db.local_engine.begin() as conn:
            row = conn.execute(
                select(workspaces_table).where(workspaces_table.c.workspace_id == wid)
            ).mappings().first()
        return self._db._decode_workspace_row(row) if row else None

    def list_workspaces(self, *, actor_id: str = "", include_inactive: bool = False) -> list[dict[str, Any]]:
        actor = str(actor_id or "").strip()
        with self._db.local_engine.begin() as conn:
            rows = conn.execute(select(workspaces_table).order_by(workspaces_table.c.updated_at.desc())).mappings().all()
            memberships: dict[str, dict[str, Any]] = {}
            if actor:
                membership_rows = conn.execute(
                    select(workspace_memberships_table)
                    .where(workspace_memberships_table.c.actor_id == actor)
                    .order_by(workspace_memberships_table.c.updated_at.desc())
                ).mappings().all()
                memberships = {
                    str(row["workspace_id"]): self._db._decode_workspace_membership_row(row)
                    for row in membership_rows
                    if include_inactive or str(row.get("status") or "active") == "active"
                }
        workspaces = [self._db._decode_workspace_row(row) for row in rows]
        if actor:
            workspaces = [item for item in workspaces if item["workspace_id"] in memberships]
        if not include_inactive:
            workspaces = [item for item in workspaces if item["status"] == "active"]
        out: list[dict[str, Any]] = []
        for item in workspaces:
            membership = memberships.get(item["workspace_id"])
            payload = dict(item)
            if membership:
                payload["membership"] = membership
            out.append(payload)
        return out

    def ensure_membership(
        self,
        *,
        workspace_id: str,
        actor_id: str,
        role: str = "member",
        status: str = "active",
    ) -> dict[str, Any]:
        wid = str(workspace_id or "local-workspace").strip() or "local-workspace"
        aid = str(actor_id or "").strip()
        if not aid:
            raise ValueError("actor_id required")
        self.ensure_workspace(wid)
        values = {
            "membership_id": f"mbr::{wid}::{aid}",
            "workspace_id": wid,
            "actor_id": aid,
            "role": self._normalize_role(role),
            "status": str(status or "active"),
            "updated_at": _now(),
        }
        with self._db.local_engine.begin() as conn:
            existing = conn.execute(
                select(workspace_memberships_table.c.membership_id).where(workspace_memberships_table.c.membership_id == values["membership_id"])
            ).first()
            if existing:
                conn.execute(
                    workspace_memberships_table.update()
                    .where(workspace_memberships_table.c.membership_id == values["membership_id"])
                    .values(**values)
                )
            else:
                conn.execute(workspace_memberships_table.insert().values(**values))
            self._db._insert_audit_event(
                conn,
                workspace_id=wid,
                event_type="workspace.membership.upserted",
                payload={"actor_id": aid, "role": values["role"], "status": values["status"]},
            )
            self._db.outbox.enqueue(
                conn,
                workspace_id=wid,
                aggregate_type="workspace_membership",
                aggregate_id=values["membership_id"],
                event_type="workspace.membership.upserted",
                payload={"workspace_id": wid, "actor_id": aid, "role": values["role"], "status": values["status"]},
            )
        return self._db._decode_workspace_membership_row(values)

    def get_membership(self, *, workspace_id: str, actor_id: str) -> dict[str, Any] | None:
        wid = str(workspace_id or "local-workspace").strip() or "local-workspace"
        aid = str(actor_id or "").strip()
        if not aid:
            return None
        with self._db.local_engine.begin() as conn:
            row = conn.execute(
                select(workspace_memberships_table)
                .where(workspace_memberships_table.c.workspace_id == wid)
                .where(workspace_memberships_table.c.actor_id == aid)
            ).mappings().first()
        return self._db._decode_workspace_membership_row(row) if row else None

    def list_memberships(self, workspace_id: str, *, include_users: bool = False) -> list[dict[str, Any]]:
        wid = str(workspace_id or "local-workspace").strip() or "local-workspace"
        with self._db.local_engine.begin() as conn:
            rows = conn.execute(
                select(workspace_memberships_table)
                .where(workspace_memberships_table.c.workspace_id == wid)
                .order_by(workspace_memberships_table.c.updated_at.desc())
            ).mappings().all()
            if not include_users:
                return [self._db._decode_workspace_membership_row(row) for row in rows]
            actor_ids = [str(row["actor_id"]) for row in rows if str(row.get("actor_id") or "").strip()]
            users = {}
            if actor_ids:
                user_rows = conn.execute(
                    select(local_users_table).where(local_users_table.c.user_id.in_(actor_ids))
                ).mappings().all()
                users = {str(row["user_id"]): self._db._decode_local_user_row(row) for row in user_rows}
            seat_rows = conn.execute(
                select(workspace_seat_assignments_table)
                .where(workspace_seat_assignments_table.c.workspace_id == wid)
                .where(workspace_seat_assignments_table.c.status == "active")
            ).mappings().all()
            seat_map = {
                str(row["actor_id"]): self._db._decode_workspace_seat_assignment_row(row)
                for row in seat_rows
            }
        enriched: list[dict[str, Any]] = []
        for row in rows:
            item = self._db._decode_workspace_membership_row(row)
            item["user"] = users.get(item["actor_id"])
            item["seat_assignment"] = seat_map.get(item["actor_id"])
            item["seat_assigned"] = item["seat_assignment"] is not None
            enriched.append(item)
        return enriched

    def get_actor_role(self, *, workspace_id: str, actor_id: str) -> str:
        wid = str(workspace_id or "local-workspace").strip() or "local-workspace"
        aid = str(actor_id or "").strip()
        if not aid:
            return "member"
        with self._db.local_engine.begin() as conn:
            row = conn.execute(
                select(workspace_memberships_table.c.role, workspace_memberships_table.c.status)
                .where(workspace_memberships_table.c.workspace_id == wid)
                .where(workspace_memberships_table.c.actor_id == aid)
            ).first()
        if not row or str(row[1] or "inactive") != "active":
            return "member"
        return self._normalize_role(str(row[0] or "member"))

    def update_membership_role(
        self,
        *,
        workspace_id: str,
        actor_id: str,
        role: str,
        updated_by: str,
    ) -> dict[str, Any]:
        wid = str(workspace_id or "local-workspace").strip() or "local-workspace"
        aid = str(actor_id or "").strip()
        if not aid:
            raise ValueError("actor_id required")
        normalized_role = self._normalize_role(role)
        membership_id = f"mbr::{wid}::{aid}"
        with self._db.local_engine.begin() as conn:
            row = conn.execute(
                select(workspace_memberships_table).where(workspace_memberships_table.c.membership_id == membership_id)
            ).mappings().first()
            if row is None:
                raise KeyError("membership_not_found")
            previous_role = str(row.get("role") or "member")
            if previous_role == "owner" and normalized_role != "owner":
                owner_count = conn.execute(
                    select(func.count()).select_from(workspace_memberships_table)
                    .where(workspace_memberships_table.c.workspace_id == wid)
                    .where(workspace_memberships_table.c.role == "owner")
                    .where(workspace_memberships_table.c.status == "active")
                ).scalar_one()
                if int(owner_count or 0) <= 1:
                    raise RuntimeError("workspace_requires_owner")
            values = {
                "role": normalized_role,
                "updated_at": _now(),
            }
            conn.execute(
                workspace_memberships_table.update()
                .where(workspace_memberships_table.c.membership_id == membership_id)
                .values(**values)
            )
            self._db._insert_audit_event(
                conn,
                workspace_id=wid,
                event_type="workspace.membership.role_updated",
                payload={"actor_id": aid, "previous_role": previous_role, "role": normalized_role, "updated_by": str(updated_by or "")},
            )
            self._db.outbox.enqueue(
                conn,
                workspace_id=wid,
                aggregate_type="workspace_membership",
                aggregate_id=membership_id,
                event_type="workspace.membership.role_updated",
                payload={"workspace_id": wid, "actor_id": aid, "previous_role": previous_role, "role": normalized_role, "updated_by": str(updated_by or "")},
            )
            updated = conn.execute(
                select(workspace_memberships_table).where(workspace_memberships_table.c.membership_id == membership_id)
            ).mappings().first()
        return self._db._decode_workspace_membership_row(updated or {})

    def create_invite(
        self,
        *,
        workspace_id: str,
        email: str,
        role: str,
        invited_by: str,
        ttl_seconds: int = 60 * 60 * 24 * 7,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        invite_id = f"inv_{uuid.uuid4().hex[:12]}"
        values = {
            "invite_id": invite_id,
            "workspace_id": str(workspace_id or "local-workspace").strip() or "local-workspace",
            "email": str(email or "").strip().lower(),
            "role": self._normalize_role(role),
            "status": "pending",
            "invited_by": str(invited_by or ""),
            "metadata_json": _json_dumps(dict(metadata or {})),
            "expires_at": _now() + max(300, int(ttl_seconds or 0)),
            "updated_at": _now(),
        }
        if not values["email"]:
            raise ValueError("email required")
        self.ensure_workspace(values["workspace_id"])
        with self._db.local_engine.begin() as conn:
            conn.execute(workspace_invites_table.insert().values(**values))
            self._db._insert_audit_event(
                conn,
                workspace_id=values["workspace_id"],
                event_type="workspace.invite.created",
                payload={"invite_id": invite_id, "email": values["email"], "role": values["role"]},
            )
            self._db.outbox.enqueue(
                conn,
                workspace_id=values["workspace_id"],
                aggregate_type="workspace_invite",
                aggregate_id=invite_id,
                event_type="workspace.invite.created",
                payload={"workspace_id": values["workspace_id"], "invite_id": invite_id, "email": values["email"], "role": values["role"], "status": values["status"], "invited_by": values["invited_by"], "expires_at": values["expires_at"]},
            )
        return self._db._decode_workspace_invite_row(values)

    def list_invites(self, workspace_id: str, *, status: str = "") -> list[dict[str, Any]]:
        with self._db.local_engine.begin() as conn:
            stmt = select(workspace_invites_table).where(workspace_invites_table.c.workspace_id == str(workspace_id or "local-workspace"))
            if str(status or "").strip():
                stmt = stmt.where(workspace_invites_table.c.status == str(status or "").strip())
            rows = conn.execute(stmt.order_by(workspace_invites_table.c.updated_at.desc())).mappings().all()
        return [self._db._decode_workspace_invite_row(row) for row in rows]

    def get_invite(self, invite_id: str) -> dict[str, Any] | None:
        iid = str(invite_id or "").strip()
        if not iid:
            return None
        with self._db.local_engine.begin() as conn:
            row = conn.execute(
                select(workspace_invites_table).where(workspace_invites_table.c.invite_id == iid)
            ).mappings().first()
        return self._db._decode_workspace_invite_row(row) if row else None

    def accept_invite(self, *, invite_id: str, actor_id: str, email: str = "") -> dict[str, Any] | None:
        iid = str(invite_id or "").strip()
        if not iid:
            return None
        normalized_email = str(email or "").strip().lower()
        with self._db.local_engine.begin() as conn:
            row = conn.execute(
                select(workspace_invites_table).where(workspace_invites_table.c.invite_id == iid)
            ).mappings().first()
            if not row:
                return None
            if normalized_email and str(row.get("email") or "").strip().lower() != normalized_email:
                raise PermissionError("invite_email_mismatch")
            if float(row.get("expires_at") or 0.0) and float(row.get("expires_at") or 0.0) < _now():
                conn.execute(
                    workspace_invites_table.update()
                    .where(workspace_invites_table.c.invite_id == iid)
                    .values(status="expired", updated_at=_now())
                )
                return None
            conn.execute(
                workspace_invites_table.update()
                .where(workspace_invites_table.c.invite_id == iid)
                .values(status="accepted", updated_at=_now())
            )
            self._db._insert_audit_event(
                conn,
                workspace_id=str(row.get("workspace_id") or "local-workspace"),
                event_type="workspace.invite.accepted",
                payload={"invite_id": iid, "actor_id": str(actor_id or ""), "email": str(row.get("email") or "")},
            )
            self._db.outbox.enqueue(
                conn,
                workspace_id=str(row.get("workspace_id") or "local-workspace"),
                aggregate_type="workspace_invite",
                aggregate_id=iid,
                event_type="workspace.invite.accepted",
                payload={"workspace_id": str(row.get("workspace_id") or "local-workspace"), "invite_id": iid, "actor_id": str(actor_id or ""), "email": str(row.get("email") or ""), "status": "accepted"},
            )
        membership = self.ensure_membership(
            workspace_id=str(row.get("workspace_id") or "local-workspace"),
            actor_id=str(actor_id or ""),
            role=str(row.get("role") or "member"),
            status="active",
        )
        return {
            "invite": self._db._decode_workspace_invite_row(dict(row, status="accepted", updated_at=_now())),
            "membership": membership,
        }

    @staticmethod
    def _seat_assignment_id(workspace_id: str, actor_id: str) -> str:
        return f"seat::{str(workspace_id or 'local-workspace').strip() or 'local-workspace'}::{str(actor_id or '').strip()}"

    @staticmethod
    def _seat_limit_from_row(row: Any) -> int:
        try:
            return max(1, int((row[0] if row else 1) or 1))
        except Exception:
            return 1

    def _seat_limit(self, conn: Connection, workspace_id: str) -> int:
        row = conn.execute(
            select(billing_workspaces_table.c.seats).where(billing_workspaces_table.c.workspace_id == str(workspace_id or "local-workspace"))
        ).first()
        return self._seat_limit_from_row(row)

    def list_seat_assignments(self, workspace_id: str, *, status: str = "active") -> list[dict[str, Any]]:
        wid = str(workspace_id or "local-workspace").strip() or "local-workspace"
        with self._db.local_engine.begin() as conn:
            stmt = select(workspace_seat_assignments_table).where(workspace_seat_assignments_table.c.workspace_id == wid)
            if str(status or "").strip():
                stmt = stmt.where(workspace_seat_assignments_table.c.status == str(status or "").strip())
            rows = conn.execute(stmt.order_by(workspace_seat_assignments_table.c.updated_at.desc())).mappings().all()
        return [self._db._decode_workspace_seat_assignment_row(row) for row in rows]

    def has_active_seat(self, *, workspace_id: str, actor_id: str) -> bool:
        wid = str(workspace_id or "local-workspace").strip() or "local-workspace"
        aid = str(actor_id or "").strip()
        if not aid:
            return False
        with self._db.local_engine.begin() as conn:
            row = conn.execute(
                select(workspace_seat_assignments_table.c.assignment_id)
                .where(workspace_seat_assignments_table.c.workspace_id == wid)
                .where(workspace_seat_assignments_table.c.actor_id == aid)
                .where(workspace_seat_assignments_table.c.status == "active")
            ).first()
        return row is not None

    def assign_seat(self, *, workspace_id: str, actor_id: str, assigned_by: str) -> dict[str, Any]:
        wid = str(workspace_id or "local-workspace").strip() or "local-workspace"
        aid = str(actor_id or "").strip()
        if not aid:
            raise ValueError("actor_id required")
        assignment_id = self._seat_assignment_id(wid, aid)
        with self._db.local_engine.begin() as conn:
            membership = conn.execute(
                select(workspace_memberships_table)
                .where(workspace_memberships_table.c.workspace_id == wid)
                .where(workspace_memberships_table.c.actor_id == aid)
                .where(workspace_memberships_table.c.status == "active")
            ).mappings().first()
            if membership is None:
                raise KeyError("membership_not_found")
            existing = conn.execute(
                select(workspace_seat_assignments_table)
                .where(workspace_seat_assignments_table.c.assignment_id == assignment_id)
            ).mappings().first()
            if existing and str(existing.get("status") or "") == "active":
                return self._db._decode_workspace_seat_assignment_row(existing)
            seats_used = conn.execute(
                select(func.count()).select_from(workspace_seat_assignments_table)
                .where(workspace_seat_assignments_table.c.workspace_id == wid)
                .where(workspace_seat_assignments_table.c.status == "active")
            ).scalar_one()
            seat_limit = self._seat_limit(conn, wid)
            if int(seats_used or 0) >= int(seat_limit or 1):
                raise RuntimeError("seat_limit_reached")
            now = _now()
            values = {
                "assignment_id": assignment_id,
                "workspace_id": wid,
                "actor_id": aid,
                "assigned_by": str(assigned_by or ""),
                "status": "active",
                "created_at": float(existing.get("created_at") or now) if existing else now,
                "updated_at": now,
            }
            if existing:
                conn.execute(
                    workspace_seat_assignments_table.update()
                    .where(workspace_seat_assignments_table.c.assignment_id == assignment_id)
                    .values(**values)
                )
            else:
                conn.execute(workspace_seat_assignments_table.insert().values(**values))
            self._db._insert_audit_event(
                conn,
                workspace_id=wid,
                event_type="workspace.seat.assigned",
                payload={"assignment_id": assignment_id, "actor_id": aid, "assigned_by": str(assigned_by or "")},
            )
            self._db.outbox.enqueue(
                conn,
                workspace_id=wid,
                aggregate_type="workspace_seat_assignment",
                aggregate_id=assignment_id,
                event_type="workspace.seat.assigned",
                payload={"workspace_id": wid, "assignment_id": assignment_id, "actor_id": aid, "assigned_by": str(assigned_by or ""), "status": "active"},
            )
        return self._db._decode_workspace_seat_assignment_row(values)

    def release_seat(self, *, workspace_id: str, actor_id: str, released_by: str) -> bool:
        wid = str(workspace_id or "local-workspace").strip() or "local-workspace"
        aid = str(actor_id or "").strip()
        if not aid:
            return False
        assignment_id = self._seat_assignment_id(wid, aid)
        with self._db.local_engine.begin() as conn:
            row = conn.execute(
                select(workspace_seat_assignments_table).where(workspace_seat_assignments_table.c.assignment_id == assignment_id)
            ).mappings().first()
            if row is None or str(row.get("status") or "") != "active":
                return False
            conn.execute(
                workspace_seat_assignments_table.update()
                .where(workspace_seat_assignments_table.c.assignment_id == assignment_id)
                .values(status="released", updated_at=_now())
            )
            self._db._insert_audit_event(
                conn,
                workspace_id=wid,
                event_type="workspace.seat.released",
                payload={"assignment_id": assignment_id, "actor_id": aid, "released_by": str(released_by or "")},
            )
            self._db.outbox.enqueue(
                conn,
                workspace_id=wid,
                aggregate_type="workspace_seat_assignment",
                aggregate_id=assignment_id,
                event_type="workspace.seat.released",
                payload={"workspace_id": wid, "assignment_id": assignment_id, "actor_id": aid, "released_by": str(released_by or ""), "status": "released"},
            )
        return True

    def seat_summary(self, workspace_id: str) -> dict[str, Any]:
        wid = str(workspace_id or "local-workspace").strip() or "local-workspace"
        assignments = self.list_seat_assignments(wid, status="active")
        with self._db.local_engine.begin() as conn:
            seat_limit = self._seat_limit(conn, wid)
        seats_used = len(assignments)
        return {
            "workspace_id": wid,
            "seat_limit": int(seat_limit),
            "seats_used": int(seats_used),
            "seats_available": max(0, int(seat_limit) - int(seats_used)),
            "assignments": assignments,
        }


class ExecutionRepository:
    def __init__(self, db: "RuntimeDatabase") -> None:
        self._db = db

    def persist_plan(self, *, run_id: str, steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
        with self._db.local_engine.begin() as conn:
            conn.execute(planned_steps_table.delete().where(planned_steps_table.c.run_id == str(run_id)))
            rows: list[dict[str, Any]] = []
            for index, step in enumerate(list(steps or []), start=1):
                planned_step_id = str(step.get("planned_step_id") or f"plan_{run_id}_{index}")
                values = {
                    "planned_step_id": planned_step_id,
                    "run_id": str(run_id),
                    "sequence_number": max(1, int(step.get("sequence_number") or index)),
                    "step_type": str(step.get("step_type") or "workflow_stage"),
                    "objective": str(step.get("objective") or step.get("title") or planned_step_id),
                    "expected_artifacts_json": _json_dumps(list(step.get("expected_artifacts") or [])),
                    "verification_method": str(step.get("verification_method") or ""),
                    "rollback_strategy": str(step.get("rollback_strategy") or ""),
                    "created_at": float(step.get("created_at") or _now()),
                }
                conn.execute(planned_steps_table.insert().values(**values))
                rows.append({**step, "planned_step_id": planned_step_id})
        return rows

    def start_execution_step(
        self,
        *,
        run_id: str,
        planned_step_id: str,
        step_name: str,
        workflow_state: str,
        payload: dict[str, Any] | None = None,
    ) -> str:
        execution_step_id = f"exec_{uuid.uuid4().hex[:12]}"
        with self._db.local_engine.begin() as conn:
            conn.execute(
                execution_steps_table.insert().values(
                    execution_step_id=execution_step_id,
                    run_id=str(run_id),
                    planned_step_id=str(planned_step_id or ""),
                    status="running",
                    tool_name=str(step_name or "workflow_stage"),
                    payload_json=_json_dumps({"workflow_state": str(workflow_state or ""), "payload": dict(payload or {})}),
                    result_json="{}",
                    started_at=_now(),
                    completed_at=0.0,
                )
            )
        return execution_step_id

    def complete_execution_step(
        self,
        execution_step_id: str,
        *,
        status: str,
        result: dict[str, Any] | None = None,
        completed_at: float | None = None,
    ) -> None:
        with self._db.local_engine.begin() as conn:
            conn.execute(
                execution_steps_table.update()
                .where(execution_steps_table.c.execution_step_id == str(execution_step_id))
                .values(
                    status=str(status or "completed"),
                    result_json=_json_dumps(dict(result or {})),
                    completed_at=float(completed_at or _now()),
                )
            )

    def record_verification(
        self,
        *,
        run_id: str,
        execution_step_id: str,
        method: str,
        status: str,
        payload: dict[str, Any] | None = None,
    ) -> str:
        verification_id = f"verify_{uuid.uuid4().hex[:12]}"
        with self._db.local_engine.begin() as conn:
            conn.execute(
                verification_results_table.insert().values(
                    verification_id=verification_id,
                    run_id=str(run_id),
                    execution_step_id=str(execution_step_id or ""),
                    status=str(status or "pending"),
                    method=str(method or ""),
                    payload_json=_json_dumps(dict(payload or {})),
                    created_at=_now(),
                )
            )
            workspace_row = conn.execute(
                select(task_runs_table.c.workspace_id).where(task_runs_table.c.run_id == str(run_id))
            ).first()
            self._db.outbox.enqueue(
                conn,
                workspace_id=str(workspace_row[0] if workspace_row else "local-workspace"),
                aggregate_type="verification",
                aggregate_id=verification_id,
                event_type="verification.recorded",
                payload={"run_id": str(run_id), "verification_id": verification_id, "status": str(status or "pending"), "method": str(method or ""), "payload": dict(payload or {})},
            )
        return verification_id

    def record_recovery(self, *, run_id: str, verification_id: str, decision: str, payload: dict[str, Any] | None = None) -> str:
        recovery_id = f"recovery_{uuid.uuid4().hex[:12]}"
        with self._db.local_engine.begin() as conn:
            conn.execute(
                recovery_actions_table.insert().values(
                    recovery_id=recovery_id,
                    run_id=str(run_id),
                    verification_id=str(verification_id or ""),
                    decision=str(decision or "retry"),
                    payload_json=_json_dumps(dict(payload or {})),
                    created_at=_now(),
                )
            )
            workspace_row = conn.execute(
                select(task_runs_table.c.workspace_id).where(task_runs_table.c.run_id == str(run_id))
            ).first()
            self._db.outbox.enqueue(
                conn,
                workspace_id=str(workspace_row[0] if workspace_row else "local-workspace"),
                aggregate_type="recovery",
                aggregate_id=recovery_id,
                event_type="recovery.recorded",
                payload={"run_id": str(run_id), "verification_id": str(verification_id or ""), "decision": str(decision or "retry"), "payload": dict(payload or {})},
            )
        return recovery_id

    def record_checkpoint(self, *, run_id: str, step_id: str, workflow_state: str, summary: dict[str, Any] | None = None, created_at: float | None = None) -> str:
        with self._db.local_engine.begin() as conn:
            existing = conn.execute(
                select(func.max(replay_checkpoints_table.c.sequence_number)).where(replay_checkpoints_table.c.run_id == str(run_id))
            ).scalar_one()
            sequence_number = int(existing or 0) + 1
            checkpoint_id = f"chk_{run_id}_{sequence_number}"
            conn.execute(
                replay_checkpoints_table.insert().values(
                    checkpoint_id=checkpoint_id,
                    run_id=str(run_id),
                    step_id=str(step_id or ""),
                    sequence_number=sequence_number,
                    workflow_state=str(workflow_state or ""),
                    summary_json=_json_dumps(dict(summary or {})),
                    created_at=float(created_at or _now()),
                )
            )
            workspace_row = conn.execute(
                select(task_runs_table.c.workspace_id).where(task_runs_table.c.run_id == str(run_id))
            ).first()
            self._db.outbox.enqueue(
                conn,
                workspace_id=str(workspace_row[0] if workspace_row else "local-workspace"),
                aggregate_type="replay_checkpoint",
                aggregate_id=checkpoint_id,
                event_type="replay.checkpoint.recorded",
                payload={"run_id": str(run_id), "checkpoint_id": checkpoint_id, "step_id": str(step_id or ""), "workflow_state": str(workflow_state or ""), "summary": dict(summary or {})},
            )
        return checkpoint_id

    def record_artifact_diff(
        self,
        *,
        run_id: str,
        artifact_id: str,
        before_hash: str = "",
        after_hash: str = "",
        summary: dict[str, Any] | None = None,
        created_at: float | None = None,
    ) -> str:
        artifact_diff_id = f"diff_{uuid.uuid4().hex[:12]}"
        with self._db.local_engine.begin() as conn:
            conn.execute(
                artifact_diffs_table.insert().values(
                    artifact_diff_id=artifact_diff_id,
                    run_id=str(run_id),
                    artifact_id=str(artifact_id or ""),
                    before_hash=str(before_hash or ""),
                    after_hash=str(after_hash or ""),
                    summary_json=_json_dumps(dict(summary or {})),
                    created_at=float(created_at or _now()),
                )
            )
            workspace_row = conn.execute(
                select(task_runs_table.c.workspace_id).where(task_runs_table.c.run_id == str(run_id))
            ).first()
            self._db.outbox.enqueue(
                conn,
                workspace_id=str(workspace_row[0] if workspace_row else "local-workspace"),
                aggregate_type="artifact_diff",
                aggregate_id=artifact_diff_id,
                event_type="artifact.diff.recorded",
                payload={
                    "run_id": str(run_id),
                    "artifact_diff_id": artifact_diff_id,
                    "artifact_id": str(artifact_id or ""),
                    "summary": dict(summary or {}),
                },
            )
        return artifact_diff_id

    def record_file_mutation(
        self,
        *,
        run_id: str,
        path: str,
        before_hash: str = "",
        after_hash: str = "",
        rollback_available: bool = False,
        summary: dict[str, Any] | None = None,
        created_at: float | None = None,
    ) -> str:
        mutation_id = f"mut_{uuid.uuid4().hex[:12]}"
        with self._db.local_engine.begin() as conn:
            conn.execute(
                file_mutations_table.insert().values(
                    mutation_id=mutation_id,
                    run_id=str(run_id),
                    path=str(path or ""),
                    before_hash=str(before_hash or ""),
                    after_hash=str(after_hash or ""),
                    rollback_available=bool(rollback_available),
                    summary_json=_json_dumps(dict(summary or {})),
                    created_at=float(created_at or _now()),
                )
            )
            workspace_row = conn.execute(
                select(task_runs_table.c.workspace_id).where(task_runs_table.c.run_id == str(run_id))
            ).first()
            self._db.outbox.enqueue(
                conn,
                workspace_id=str(workspace_row[0] if workspace_row else "local-workspace"),
                aggregate_type="file_mutation",
                aggregate_id=mutation_id,
                event_type="file.mutation.recorded",
                payload={
                    "run_id": str(run_id),
                    "mutation_id": mutation_id,
                    "path": str(path or ""),
                    "rollback_available": bool(rollback_available),
                    "summary": dict(summary or {}),
                },
            )
        return mutation_id

    def list_execution_steps(self, run_id: str) -> list[dict[str, Any]]:
        with self._db.local_engine.begin() as conn:
            rows = conn.execute(
                select(execution_steps_table)
                .where(execution_steps_table.c.run_id == str(run_id))
                .order_by(execution_steps_table.c.started_at.asc())
            ).mappings().all()
        return [self._db._decode_execution_step_row(row) for row in rows]

    def list_verifications(self, run_id: str) -> list[dict[str, Any]]:
        with self._db.local_engine.begin() as conn:
            rows = conn.execute(
                select(verification_results_table)
                .where(verification_results_table.c.run_id == str(run_id))
                .order_by(verification_results_table.c.created_at.asc())
            ).mappings().all()
        return [self._db._decode_verification_row(row) for row in rows]

    def list_recovery_actions(self, run_id: str) -> list[dict[str, Any]]:
        with self._db.local_engine.begin() as conn:
            rows = conn.execute(
                select(recovery_actions_table)
                .where(recovery_actions_table.c.run_id == str(run_id))
                .order_by(recovery_actions_table.c.created_at.asc())
            ).mappings().all()
        return [self._db._decode_recovery_row(row) for row in rows]

    def list_checkpoints(self, run_id: str) -> list[dict[str, Any]]:
        with self._db.local_engine.begin() as conn:
            rows = conn.execute(
                select(replay_checkpoints_table)
                .where(replay_checkpoints_table.c.run_id == str(run_id))
                .order_by(replay_checkpoints_table.c.sequence_number.asc())
            ).mappings().all()
        return [self._db._decode_checkpoint_row(row) for row in rows]

    def list_artifact_diffs(self, run_id: str) -> list[dict[str, Any]]:
        with self._db.local_engine.begin() as conn:
            rows = conn.execute(
                select(artifact_diffs_table)
                .where(artifact_diffs_table.c.run_id == str(run_id))
                .order_by(artifact_diffs_table.c.created_at.asc())
            ).mappings().all()
        return [self._db._decode_artifact_diff_row(row) for row in rows]

    def list_file_mutations(self, run_id: str) -> list[dict[str, Any]]:
        with self._db.local_engine.begin() as conn:
            rows = conn.execute(
                select(file_mutations_table)
                .where(file_mutations_table.c.run_id == str(run_id))
                .order_by(file_mutations_table.c.created_at.asc())
            ).mappings().all()
        return [self._db._decode_file_mutation_row(row) for row in rows]


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

            existing_checkpoints = conn.execute(
                select(func.count()).select_from(replay_checkpoints_table).where(replay_checkpoints_table.c.run_id == run_id)
            ).scalar_one()
            if not int(existing_checkpoints or 0):
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
            elif aggregate_type == "workspace":
                workspace_values = {
                    "workspace_id": str(payload.get("workspace_id") or event_payload.get("aggregate_id") or workspace_id),
                    "display_name": str(payload.get("display_name") or workspace_id),
                    "status": str(payload.get("status") or "active"),
                    "metadata_json": _json_dumps(dict(payload.get("metadata") or {})),
                    "updated_at": _now(),
                }
                existing_workspace = conn.execute(
                    select(workspaces_table.c.workspace_id).where(workspaces_table.c.workspace_id == workspace_values["workspace_id"])
                ).first()
                if existing_workspace:
                    conn.execute(
                        workspaces_table.update()
                        .where(workspaces_table.c.workspace_id == workspace_values["workspace_id"])
                        .values(**workspace_values)
                    )
                else:
                    conn.execute(workspaces_table.insert().values(**workspace_values))
            elif aggregate_type == "workspace_membership":
                membership_values = {
                    "membership_id": str(event_payload.get("aggregate_id") or payload.get("membership_id") or ""),
                    "workspace_id": workspace_id,
                    "actor_id": str(payload.get("actor_id") or ""),
                    "role": str(payload.get("role") or "member"),
                    "status": str(payload.get("status") or "active"),
                    "updated_at": _now(),
                }
                existing_membership = conn.execute(
                    select(workspace_memberships_table.c.membership_id).where(workspace_memberships_table.c.membership_id == membership_values["membership_id"])
                ).first()
                if existing_membership:
                    conn.execute(
                        workspace_memberships_table.update()
                        .where(workspace_memberships_table.c.membership_id == membership_values["membership_id"])
                        .values(**membership_values)
                    )
                else:
                    conn.execute(workspace_memberships_table.insert().values(**membership_values))
            elif aggregate_type == "workspace_invite":
                invite_values = {
                    "invite_id": str(payload.get("invite_id") or event_payload.get("aggregate_id") or ""),
                    "workspace_id": workspace_id,
                    "email": str(payload.get("email") or ""),
                    "role": str(payload.get("role") or "member"),
                    "status": str(payload.get("status") or "pending"),
                    "invited_by": str(payload.get("invited_by") or ""),
                    "metadata_json": _json_dumps(dict(payload.get("metadata") or {})),
                    "expires_at": float(payload.get("expires_at") or 0.0),
                    "updated_at": _now(),
                }
                existing_invite = conn.execute(
                    select(workspace_invites_table.c.invite_id).where(workspace_invites_table.c.invite_id == invite_values["invite_id"])
                ).first()
                if existing_invite:
                    conn.execute(
                        workspace_invites_table.update()
                        .where(workspace_invites_table.c.invite_id == invite_values["invite_id"])
                        .values(**invite_values)
                    )
                else:
                    conn.execute(workspace_invites_table.insert().values(**invite_values))
            elif aggregate_type == "workspace_seat_assignment":
                assignment_values = {
                    "assignment_id": str(payload.get("assignment_id") or event_payload.get("aggregate_id") or ""),
                    "workspace_id": workspace_id,
                    "actor_id": str(payload.get("actor_id") or ""),
                    "assigned_by": str(payload.get("assigned_by") or payload.get("released_by") or ""),
                    "status": str(payload.get("status") or "active"),
                    "created_at": float(event_payload.get("created_at") or _now()),
                    "updated_at": _now(),
                }
                existing_assignment = conn.execute(
                    select(workspace_seat_assignments_table.c.assignment_id).where(workspace_seat_assignments_table.c.assignment_id == assignment_values["assignment_id"])
                ).first()
                if existing_assignment:
                    conn.execute(
                        workspace_seat_assignments_table.update()
                        .where(workspace_seat_assignments_table.c.assignment_id == assignment_values["assignment_id"])
                        .values(**assignment_values)
                    )
                else:
                    conn.execute(workspace_seat_assignments_table.insert().values(**assignment_values))
            elif aggregate_type == "workspace_inbox_event":
                inbox_values = {
                    "event_id": str(payload.get("event_id") or event_payload.get("aggregate_id") or ""),
                    "workspace_id": workspace_id,
                    "source_type": str(payload.get("source_type") or "manual"),
                    "source_id": str(payload.get("source_id") or ""),
                    "title": str(payload.get("title") or ""),
                    "content_encrypted": str(payload.get("content_encrypted") or ""),
                    "status": str(payload.get("status") or "received"),
                    "summary_json": _json_dumps(dict(payload.get("summary") or {})),
                    "metadata_json": _json_dumps(dict(payload.get("metadata") or {})),
                    "created_at": float(payload.get("created_at") or event_payload.get("created_at") or _now()),
                    "updated_at": _now(),
                }
                existing_inbox = conn.execute(
                    select(workspace_inbox_events_table.c.event_id).where(workspace_inbox_events_table.c.event_id == inbox_values["event_id"])
                ).first()
                if existing_inbox:
                    conn.execute(
                        workspace_inbox_events_table.update()
                        .where(workspace_inbox_events_table.c.event_id == inbox_values["event_id"])
                        .values(**inbox_values)
                    )
                else:
                    conn.execute(workspace_inbox_events_table.insert().values(**inbox_values))
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
            elif aggregate_type == "usage":
                usage_id = str(event_payload.get("aggregate_id") or event_id)
                usage_values = {
                    "usage_id": usage_id,
                    "workspace_id": workspace_id,
                    "metric": str(payload.get("metric") or "unknown"),
                    "amount": max(0, int(payload.get("amount") or 0)),
                    "payload_json": _json_dumps(payload),
                    "created_at": float(event_payload.get("created_at") or _now()),
                }
                existing_usage = conn.execute(
                    select(workspace_usage_ledger_table.c.usage_id).where(workspace_usage_ledger_table.c.usage_id == usage_id)
                ).first()
                if existing_usage:
                    conn.execute(
                        workspace_usage_ledger_table.update()
                        .where(workspace_usage_ledger_table.c.usage_id == usage_id)
                        .values(**usage_values)
                    )
                else:
                    conn.execute(workspace_usage_ledger_table.insert().values(**usage_values))
            elif aggregate_type == "connector_account":
                account_values = {
                    "account_id": str(payload.get("account_id") or event_payload.get("aggregate_id") or ""),
                    "workspace_id": workspace_id,
                    "connector_name": str(payload.get("connector_name") or payload.get("provider") or ""),
                    "provider": str(payload.get("provider") or ""),
                    "display_name": str(payload.get("display_name") or ""),
                    "status": str(payload.get("status") or "connected"),
                    "scopes_json": _json_dumps(list(payload.get("scopes") or [])),
                    "metadata_json": _json_dumps(dict(payload.get("metadata") or {})),
                    "updated_at": _now(),
                }
                existing_account = conn.execute(
                    select(connector_accounts_table.c.account_id).where(connector_accounts_table.c.account_id == account_values["account_id"])
                ).first()
                if existing_account:
                    conn.execute(
                        connector_accounts_table.update()
                        .where(connector_accounts_table.c.account_id == account_values["account_id"])
                        .values(**account_values)
                    )
                else:
                    conn.execute(connector_accounts_table.insert().values(**account_values))
                health_values = {
                    "health_id": f"health::{account_values['account_id']}",
                    "account_id": account_values["account_id"],
                    "workspace_id": workspace_id,
                    "status": str(payload.get("status") or "healthy"),
                    "payload_json": _json_dumps(payload),
                    "updated_at": _now(),
                }
                existing_health = conn.execute(
                    select(connector_health_table.c.health_id).where(connector_health_table.c.health_id == health_values["health_id"])
                ).first()
                if existing_health:
                    conn.execute(
                        connector_health_table.update()
                        .where(connector_health_table.c.health_id == health_values["health_id"])
                        .values(**health_values)
                    )
                else:
                    conn.execute(connector_health_table.insert().values(**health_values))
            elif aggregate_type == "connector_trace":
                trace_values = {
                    "trace_id": str(payload.get("trace_id") or event_payload.get("aggregate_id") or event_id),
                    "workspace_id": workspace_id,
                    "connector_account_id": str(payload.get("connector_account_id") or ""),
                    "connector_name": str(payload.get("connector_name") or ""),
                    "event_type": str(payload.get("event_type") or "connector"),
                    "payload_json": _json_dumps(dict(payload.get("payload") or {})),
                    "created_at": float(event_payload.get("created_at") or _now()),
                }
                existing_trace = conn.execute(
                    select(connector_action_traces_table.c.trace_id).where(connector_action_traces_table.c.trace_id == trace_values["trace_id"])
                ).first()
                if existing_trace:
                    conn.execute(
                        connector_action_traces_table.update()
                        .where(connector_action_traces_table.c.trace_id == trace_values["trace_id"])
                        .values(**trace_values)
                    )
                else:
                    conn.execute(connector_action_traces_table.insert().values(**trace_values))
            elif aggregate_type in {"verification", "recovery", "replay_checkpoint", "task_run"}:
                audit_values = {
                    "event_id": event_id,
                    "workspace_id": workspace_id,
                    "event_type": event_type,
                    "payload_json": _json_dumps(payload),
                    "created_at": float(event_payload.get("created_at") or _now()),
                }
                existing_audit = conn.execute(
                    select(workspace_audit_index_table.c.event_id).where(workspace_audit_index_table.c.event_id == event_id)
                ).first()
                if existing_audit:
                    conn.execute(
                        workspace_audit_index_table.update()
                        .where(workspace_audit_index_table.c.event_id == event_id)
                        .values(**audit_values)
                    )
                else:
                    conn.execute(workspace_audit_index_table.insert().values(**audit_values))
            elif aggregate_type in {"permission_grant", "user_preference_profile", "learning_feedback"}:
                audit_values = {
                    "event_id": event_id,
                    "workspace_id": workspace_id,
                    "event_type": event_type,
                    "payload_json": _json_dumps(payload),
                    "created_at": float(event_payload.get("created_at") or _now()),
                }
                existing_audit = conn.execute(
                    select(workspace_audit_index_table.c.event_id).where(workspace_audit_index_table.c.event_id == event_id)
                ).first()
                if existing_audit:
                    conn.execute(
                        workspace_audit_index_table.update()
                        .where(workspace_audit_index_table.c.event_id == event_id)
                        .values(**audit_values)
                    )
                else:
                    conn.execute(workspace_audit_index_table.insert().values(**audit_values))
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
        WORKSPACE_METADATA.create_all(self.local_engine)
        self._stamp_schema()
        self.outbox = OutboxRepository(self)
        self.threads = ThreadRepository(self)
        self.approvals = ApprovalRepository(self)
        self.inbox = InboxRepository(self)
        self.permission_grants = PermissionGrantRepository(self)
        self.billing = BillingRepository(self)
        self.connectors = ConnectorRepository(self)
        self.learning = LearningRepository(self)
        self.identities = ChannelIdentityRepository(self)
        self.privacy = PrivacyRepository(self)
        self.auth = LocalAuthRepository(self)
        self.auth_sessions = LocalAuthSessionRepository(self)
        self.conversations = ConversationRepository(self)
        self.access = WorkspaceAccessRepository(self)
        self.execution = ExecutionRepository(self)
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
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.execute("PRAGMA temp_store=MEMORY")
            cursor.execute("PRAGMA cache_size=-20000")
            cursor.execute("PRAGMA mmap_size=268435456")
            cursor.execute("PRAGMA wal_autocheckpoint=1000")
            cursor.close()

    def _stamp_schema(self) -> None:
        with self.local_engine.begin() as conn:
            existing = conn.execute(
                select(schema_migrations.c.name).where(schema_migrations.c.name == "runtime_db_v1")
            ).first()
            if existing:
                return
            conn.execute(schema_migrations.insert().values(name="runtime_db_v1", applied_at=_now()))

    @staticmethod
    def _insert_audit_event(conn: Connection, *, workspace_id: str, event_type: str, payload: dict[str, Any]) -> None:
        conn.execute(
            audit_events_table.insert().values(
                event_id=f"audit_{uuid.uuid4().hex[:12]}",
                workspace_id=str(workspace_id or "local-workspace"),
                event_type=str(event_type or "runtime.event"),
                payload_json=_json_dumps(dict(payload or {})),
                created_at=_now(),
            )
        )

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

    def _decode_billing_checkout_session_row(self, row: dict[str, Any]) -> dict[str, Any]:
        reference_id = str(row.get("reference_id") or "")
        raw_last_payload = self.codec.loads(
            str(row.get("raw_last_payload_encrypted") or ""),
            context=f"billing_checkout:{reference_id}:raw",
            default={},
        )
        return {
            "reference_id": reference_id,
            "workspace_id": str(row.get("workspace_id") or "local-workspace"),
            "mode": str(row.get("mode") or "subscription"),
            "catalog_id": str(row.get("catalog_id") or ""),
            "provider": str(row.get("provider") or "iyzico"),
            "provider_token": str(row.get("provider_token") or ""),
            "provider_payment_id": str(row.get("provider_payment_id") or ""),
            "subscription_reference_code": str(row.get("subscription_reference_code") or ""),
            "status": str(row.get("status") or "pending"),
            "payment_page_url": str(row.get("payment_page_url") or ""),
            "callback_url": str(row.get("callback_url") or ""),
            "raw_last_payload": raw_last_payload if isinstance(raw_last_payload, dict) else {},
            "created_at": float(row.get("created_at") or 0.0),
            "updated_at": float(row.get("updated_at") or 0.0),
            "completed_at": float(row.get("completed_at") or 0.0),
        }

    def _decode_billing_profile_row(self, row: dict[str, Any]) -> dict[str, Any]:
        workspace_id = str(row.get("workspace_id") or "local-workspace")
        profile_payload = self.codec.loads(
            str(row.get("profile_encrypted") or ""),
            context=f"billing_profile:{workspace_id}",
            default={},
        )
        return {
            "workspace_id": workspace_id,
            "profile": profile_payload if isinstance(profile_payload, dict) else {},
            "created_at": float(row.get("created_at") or 0.0),
            "updated_at": float(row.get("updated_at") or 0.0),
        }

    @staticmethod
    def _decode_workspace_row(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "workspace_id": str(row.get("workspace_id") or "local-workspace"),
            "display_name": str(row.get("display_name") or ""),
            "status": str(row.get("status") or "active"),
            "metadata": _json_loads(row.get("metadata_json"), {}),
            "updated_at": float(row.get("updated_at") or 0.0),
        }

    @staticmethod
    def _decode_workspace_membership_row(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "membership_id": str(row.get("membership_id") or ""),
            "workspace_id": str(row.get("workspace_id") or "local-workspace"),
            "actor_id": str(row.get("actor_id") or ""),
            "role": str(row.get("role") or "member"),
            "status": str(row.get("status") or "active"),
            "updated_at": float(row.get("updated_at") or 0.0),
        }

    @staticmethod
    def _decode_workspace_invite_row(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "invite_id": str(row.get("invite_id") or ""),
            "workspace_id": str(row.get("workspace_id") or "local-workspace"),
            "email": str(row.get("email") or ""),
            "role": str(row.get("role") or "member"),
            "status": str(row.get("status") or "pending"),
            "invited_by": str(row.get("invited_by") or ""),
            "metadata": _json_loads(row.get("metadata_json"), {}),
            "expires_at": float(row.get("expires_at") or 0.0),
            "updated_at": float(row.get("updated_at") or 0.0),
        }

    @staticmethod
    def _decode_workspace_seat_assignment_row(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "assignment_id": str(row.get("assignment_id") or ""),
            "workspace_id": str(row.get("workspace_id") or "local-workspace"),
            "actor_id": str(row.get("actor_id") or ""),
            "assigned_by": str(row.get("assigned_by") or ""),
            "status": str(row.get("status") or "active"),
            "created_at": float(row.get("created_at") or 0.0),
            "updated_at": float(row.get("updated_at") or 0.0),
        }

    @staticmethod
    def _decode_billing_event_row(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "event_id": str(row.get("event_id") or ""),
            "workspace_id": str(row.get("workspace_id") or "local-workspace"),
            "provider": str(row.get("provider") or "internal"),
            "event_type": str(row.get("event_type") or "billing.updated"),
            "status": str(row.get("status") or "pending"),
            "reference_id": str(row.get("reference_id") or ""),
            "payload": _json_loads(row.get("payload_json"), {}),
            "created_at": float(row.get("created_at") or 0.0),
        }

    @staticmethod
    def _decode_credit_ledger_row(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "entry_id": str(row.get("entry_id") or ""),
            "workspace_id": str(row.get("workspace_id") or "local-workspace"),
            "bucket": str(row.get("bucket") or "purchased"),
            "entry_type": str(row.get("entry_type") or "adjustment"),
            "delta_credits": int(row.get("delta_credits") or 0),
            "balance_after": int(row.get("balance_after") or 0),
            "reference_id": str(row.get("reference_id") or ""),
            "metadata": _json_loads(row.get("metadata_json"), {}),
            "created_at": float(row.get("created_at") or 0.0),
        }

    @staticmethod
    def _decode_usage_event_row(row: dict[str, Any] | None) -> dict[str, Any]:
        if not row:
            return {}
        return {
            "event_id": str(row.get("event_id") or ""),
            "workspace_id": str(row.get("workspace_id") or "local-workspace"),
            "actor_id": str(row.get("actor_id") or ""),
            "session_id": str(row.get("session_id") or ""),
            "run_id": str(row.get("run_id") or ""),
            "usage_id": str(row.get("usage_id") or ""),
            "metric": str(row.get("metric") or "unknown"),
            "event_type": str(row.get("event_type") or "usage"),
            "status": str(row.get("status") or "recorded"),
            "reference_id": str(row.get("reference_id") or ""),
            "provider": str(row.get("provider") or ""),
            "model_name": str(row.get("model_name") or ""),
            "priority": str(row.get("priority") or "normal"),
            "input_tokens": int(row.get("input_tokens") or 0),
            "output_tokens": int(row.get("output_tokens") or 0),
            "reasoning_tokens": int(row.get("reasoning_tokens") or 0),
            "tool_calls": int(row.get("tool_calls") or 0),
            "memory_ops": int(row.get("memory_ops") or 0),
            "prompt_length": int(row.get("prompt_length") or 0),
            "estimated_credits": int(row.get("estimated_credits") or 0),
            "actual_credits": int(row.get("actual_credits") or 0),
            "bucket": str(row.get("bucket") or ""),
            "metadata": _json_loads(row.get("metadata_json"), {}),
            "created_at": float(row.get("created_at") or 0.0),
        }

    @staticmethod
    def _decode_rate_limit_bucket_row(row: dict[str, Any] | None) -> dict[str, Any]:
        if not row:
            return {}
        return {
            "bucket_id": str(row.get("bucket_id") or ""),
            "workspace_id": str(row.get("workspace_id") or "local-workspace"),
            "actor_id": str(row.get("actor_id") or ""),
            "metric": str(row.get("metric") or ""),
            "bucket_type": str(row.get("bucket_type") or "request_minute"),
            "bucket_key": str(row.get("bucket_key") or ""),
            "request_count": int(row.get("request_count") or 0),
            "credit_spend": int(row.get("credit_spend") or 0),
            "hard_cap": int(row.get("hard_cap") or 0),
            "soft_cap": int(row.get("soft_cap") or 0),
            "status": str(row.get("status") or "open"),
            "last_allowed_at": float(row.get("last_allowed_at") or 0.0),
            "last_blocked_at": float(row.get("last_blocked_at") or 0.0),
            "last_reason": str(row.get("last_reason") or ""),
            "metadata": _json_loads(row.get("metadata_json"), {}),
            "created_at": float(row.get("created_at") or 0.0),
            "updated_at": float(row.get("updated_at") or 0.0),
        }

    def _decode_workspace_inbox_event_row(self, row: dict[str, Any]) -> dict[str, Any]:
        event_id = str(row.get("event_id") or "")
        content_payload = self.codec.loads(
            str(row.get("content_encrypted") or ""),
            context=f"inbox:{event_id}:content",
            default={},
        )
        content = ""
        if isinstance(content_payload, dict):
            content = str(content_payload.get("content") or "")
        compact_preview = re.sub(r"\s+", " ", content).strip()
        if len(compact_preview) > 220:
            compact_preview = compact_preview[:217].rstrip() + "..."
        return {
            "event_id": event_id,
            "workspace_id": str(row.get("workspace_id") or "local-workspace"),
            "source_type": str(row.get("source_type") or "manual"),
            "source_id": str(row.get("source_id") or ""),
            "title": str(row.get("title") or ""),
            "content": content,
            "content_preview": compact_preview,
            "status": str(row.get("status") or "received"),
            "summary": _json_loads(row.get("summary_json"), {}),
            "metadata": _json_loads(row.get("metadata_json"), {}),
            "created_at": float(row.get("created_at") or 0.0),
            "updated_at": float(row.get("updated_at") or 0.0),
        }

    @staticmethod
    def _decode_entitlement_snapshot_row(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "snapshot_id": str(row.get("snapshot_id") or ""),
            "workspace_id": str(row.get("workspace_id") or "local-workspace"),
            "scope": str(row.get("scope") or "workspace"),
            "payload": _json_loads(row.get("payload_json"), {}),
            "created_at": float(row.get("created_at") or 0.0),
        }

    @staticmethod
    def _decode_local_session_row(row: dict[str, Any]) -> dict[str, Any]:
        metadata = _json_loads(row["metadata_json"], {})
        return {
            "session_id": str(row["session_id"]),
            "workspace_id": str(row["workspace_id"] or "local-workspace"),
            "user_id": str(row["user_id"] or ""),
            "email": str(row.get("email") or ""),
            "display_name": str(row.get("display_name") or ""),
            "role": str(row.get("role") or "member"),
            "status": str(row["status"] or "active"),
            "expires_at": float(row["expires_at"] or 0.0),
            "last_seen_at": float(row["last_seen_at"] or 0.0),
            "created_at": float(row["created_at"] or 0.0),
            "updated_at": float(row["updated_at"] or 0.0),
            "metadata": metadata,
            "conversation_session_id": str(metadata.get("conversation_session_id") or ""),
        }

    @staticmethod
    def _decode_conversation_session_row(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "conversation_session_id": str(row["conversation_session_id"]),
            "workspace_id": str(row["workspace_id"] or "local-workspace"),
            "actor_id": str(row["actor_id"] or "local-user"),
            "device_id": str(row["device_id"] or "local-device"),
            "channel": str(row["channel"] or "cli"),
            "auth_session_id": str(row["auth_session_id"] or ""),
            "client_session_id": str(row["client_session_id"] or ""),
            "parent_session_id": str(row["parent_session_id"] or ""),
            "status": str(row["status"] or "active"),
            "title": str(row["title"] or ""),
            "summary_text": str(row["summary_text"] or ""),
            "message_count": int(row["message_count"] or 0),
            "token_input_total": int(row["token_input_total"] or 0),
            "token_output_total": int(row["token_output_total"] or 0),
            "metadata": _json_loads(row["metadata_json"], {}),
            "created_at": float(row["created_at"] or 0.0),
            "updated_at": float(row["updated_at"] or 0.0),
            "closed_at": float(row["closed_at"] or 0.0),
        }

    @staticmethod
    def _decode_conversation_message_row(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "message_id": str(row["message_id"]),
            "conversation_session_id": str(row["conversation_session_id"] or ""),
            "workspace_id": str(row["workspace_id"] or "local-workspace"),
            "actor_id": str(row["actor_id"] or "local-user"),
            "role": str(row["role"] or "user"),
            "content": str(row["content"] or ""),
            "message_index": int(row["message_index"] or 0),
            "run_id": str(row["run_id"] or ""),
            "action": str(row["action"] or ""),
            "success": bool(row["success"]),
            "metadata": _json_loads(row["metadata_json"], {}),
            "created_at": float(row["created_at"] or 0.0),
        }

    @staticmethod
    def _decode_permission_grant_row(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "grant_id": str(row["grant_id"]),
            "workspace_id": str(row["workspace_id"] or "local-workspace"),
            "device_id": str(row["device_id"] or "local-device"),
            "scope": str(row["scope"] or ""),
            "resource": str(row["resource"] or ""),
            "allowed_actions": _json_loads(row["allowed_actions_json"], []),
            "ttl_seconds": int(row["ttl_seconds"] or 0),
            "issued_by": str(row["issued_by"] or "runtime"),
            "revocable": bool(row["revocable"]),
            "created_at": float(row["created_at"] or 0.0),
            "expires_at": float(row["expires_at"] or 0.0),
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
    def _decode_artifact_diff_row(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "artifact_diff_id": str(row["artifact_diff_id"]),
            "run_id": str(row["run_id"]),
            "artifact_id": str(row["artifact_id"] or ""),
            "before_hash": str(row["before_hash"] or ""),
            "after_hash": str(row["after_hash"] or ""),
            "summary": _json_loads(row["summary_json"], {}),
            "created_at": float(row["created_at"] or 0.0),
        }

    @staticmethod
    def _decode_file_mutation_row(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "mutation_id": str(row["mutation_id"]),
            "run_id": str(row["run_id"]),
            "path": str(row["path"] or ""),
            "before_hash": str(row["before_hash"] or ""),
            "after_hash": str(row["after_hash"] or ""),
            "rollback_available": bool(row["rollback_available"]),
            "summary": _json_loads(row["summary_json"], {}),
            "created_at": float(row["created_at"] or 0.0),
        }

    @staticmethod
    def _decode_connector_account_row(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "account_id": str(row["account_id"]),
            "workspace_id": str(row["workspace_id"] or "local-workspace"),
            "provider": str(row["provider"] or ""),
            "connector_name": str(row["connector_name"] or ""),
            "account_alias": str(row["account_alias"] or "default"),
            "display_name": str(row["display_name"] or ""),
            "email": str(row["email"] or ""),
            "status": str(row["status"] or "needs_input"),
            "auth_strategy": str(row["auth_strategy"] or "oauth"),
            "auth_url": str(row["auth_url"] or ""),
            "redirect_uri": str(row["redirect_uri"] or ""),
            "granted_scopes": _json_loads(row["scopes_json"], []),
            "metadata": _json_loads(row["metadata_json"], {}),
            "updated_at": float(row["updated_at"] or 0.0),
        }

    @staticmethod
    def _decode_connector_trace_row(row: dict[str, Any]) -> dict[str, Any]:
        payload = _json_loads(row["payload_json"], {})
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        return {
            "trace_id": str(row["trace_id"]),
            "workspace_id": str(row["workspace_id"] or "local-workspace"),
            "connector_account_id": str(row["connector_account_id"] or ""),
            "request_id": str(payload.get("request_id") or ""),
            "user_id": str(payload.get("user_id") or ""),
            "session_id": str(payload.get("session_id") or ""),
            "channel": str(payload.get("channel") or ""),
            "provider": str(row["provider"] or ""),
            "connector_name": str(row["connector_name"] or ""),
            "integration_type": str(row["integration_type"] or ""),
            "operation": str(row["event_type"] or "connector"),
            "status": str(row["status"] or ""),
            "success": bool(row["success"]),
            "auth_state": str(payload.get("auth_state") or ""),
            "auth_strategy": str(payload.get("auth_strategy") or ""),
            "account_alias": str(metadata.get("account_alias") or payload.get("account_alias") or "default"),
            "fallback_used": bool(payload.get("fallback_used")),
            "fallback_reason": str(payload.get("fallback_reason") or ""),
            "install_state": str(payload.get("install_state") or ""),
            "retry_count": int(payload.get("retry_count") or 0),
            "latency_ms": float(row["latency_ms"] or 0.0),
            "evidence": list(payload.get("evidence") or []),
            "artifacts": list(payload.get("artifacts") or []),
            "verification": dict(payload.get("verification") or {}),
            "metadata": metadata,
            "created_at": float(row["created_at"] or 0.0),
        }

    @staticmethod
    def _decode_execution_step_row(row: dict[str, Any]) -> dict[str, Any]:
        payload = _json_loads(row["payload_json"], {})
        return {
            "execution_step_id": str(row["execution_step_id"]),
            "run_id": str(row["run_id"]),
            "planned_step_id": str(row["planned_step_id"] or ""),
            "status": str(row["status"] or "queued"),
            "tool_name": str(row["tool_name"] or ""),
            "payload": dict(payload.get("payload") or {}) if isinstance(payload, dict) else {},
            "workflow_state": str(payload.get("workflow_state") or "") if isinstance(payload, dict) else "",
            "result": _json_loads(row["result_json"], {}),
            "started_at": float(row["started_at"] or 0.0),
            "completed_at": float(row["completed_at"] or 0.0),
        }

    @staticmethod
    def _decode_verification_row(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "verification_id": str(row["verification_id"]),
            "run_id": str(row["run_id"]),
            "execution_step_id": str(row["execution_step_id"] or ""),
            "status": str(row["status"] or "pending"),
            "method": str(row["method"] or ""),
            "payload": _json_loads(row["payload_json"], {}),
            "created_at": float(row["created_at"] or 0.0),
        }

    @staticmethod
    def _decode_recovery_row(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "recovery_id": str(row["recovery_id"]),
            "run_id": str(row["run_id"]),
            "verification_id": str(row["verification_id"] or ""),
            "decision": str(row["decision"] or "retry"),
            "payload": _json_loads(row["payload_json"], {}),
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

    @staticmethod
    def _decode_local_user_row(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "user_id": str(row.get("user_id") or ""),
            "workspace_id": str(row.get("workspace_id") or "local-workspace"),
            "email": str(row.get("email") or ""),
            "display_name": str(row.get("display_name") or ""),
            "status": str(row.get("status") or "inactive"),
            "metadata": _json_loads(row.get("metadata_json"), {}),
            "created_at": float(row.get("created_at") or 0.0),
            "updated_at": float(row.get("updated_at") or 0.0),
        }

    @staticmethod
    def _decode_user_preference_profile_row(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "profile_id": str(row["profile_id"]),
            "workspace_id": str(row["workspace_id"] or "local-workspace"),
            "user_id": str(row["user_id"] or "local-user"),
            "explanation_style": str(row["explanation_style"] or "concise"),
            "approval_sensitivity_hint": str(row["approval_sensitivity_hint"] or "balanced"),
            "preferred_route": str(row["preferred_route"] or "balanced"),
            "preferred_model": str(row["preferred_model"] or ""),
            "task_templates": _json_loads(row["task_templates_json"], []),
            "metadata": _json_loads(row["metadata_json"], {}),
            "updated_at": float(row["updated_at"] or 0.0),
        }

    @staticmethod
    def _decode_preference_update_queue_row(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "queue_id": str(row["queue_id"]),
            "workspace_id": str(row["workspace_id"] or "local-workspace"),
            "user_id": str(row["user_id"] or "local-user"),
            "conversation_session_id": str(row["conversation_session_id"] or ""),
            "preference_key": str(row["preference_key"] or ""),
            "proposed_value": _json_loads(row["proposed_value_json"], {}),
            "rationale": str(row["rationale"] or ""),
            "confidence": float(row["confidence"] or 0.0),
            "status": str(row["status"] or "draft"),
            "metadata": _json_loads(row["metadata_json"], {}),
            "created_at": float(row["created_at"] or 0.0),
            "updated_at": float(row["updated_at"] or 0.0),
            "reviewed_at": float(row["reviewed_at"] or 0.0),
            "applied_at": float(row["applied_at"] or 0.0),
        }

    @staticmethod
    def _decode_skill_draft_queue_row(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "draft_id": str(row["draft_id"]),
            "workspace_id": str(row["workspace_id"] or "local-workspace"),
            "user_id": str(row["user_id"] or "local-user"),
            "conversation_session_id": str(row["conversation_session_id"] or ""),
            "name_hint": str(row["name_hint"] or ""),
            "description": str(row["description"] or ""),
            "trigger_text": str(row["trigger_text"] or ""),
            "source_action": str(row["source_action"] or ""),
            "tool_names": _json_loads(row["tool_names_json"], []),
            "confidence": float(row["confidence"] or 0.0),
            "status": str(row["status"] or "draft"),
            "metadata": _json_loads(row["metadata_json"], {}),
            "created_at": float(row["created_at"] or 0.0),
            "updated_at": float(row["updated_at"] or 0.0),
            "reviewed_at": float(row["reviewed_at"] or 0.0),
        }

    @staticmethod
    def _decode_routine_draft_queue_row(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "draft_id": str(row["draft_id"]),
            "workspace_id": str(row["workspace_id"] or "local-workspace"),
            "user_id": str(row["user_id"] or "local-user"),
            "conversation_session_id": str(row["conversation_session_id"] or ""),
            "name_hint": str(row["name_hint"] or ""),
            "description": str(row["description"] or ""),
            "trigger_text": str(row["trigger_text"] or ""),
            "schedule_expression": str(row.get("schedule_expression") or ""),
            "delivery_channel": str(row.get("delivery_channel") or ""),
            "source_action": str(row["source_action"] or ""),
            "confidence": float(row["confidence"] or 0.0),
            "status": str(row["status"] or "draft"),
            "metadata": _json_loads(row["metadata_json"], {}),
            "created_at": float(row["created_at"] or 0.0),
            "updated_at": float(row["updated_at"] or 0.0),
            "reviewed_at": float(row["reviewed_at"] or 0.0),
        }

    @staticmethod
    def _decode_channel_identity_link_row(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "link_id": str(row["link_id"]),
            "workspace_id": str(row["workspace_id"] or "local-workspace"),
            "channel": str(row["channel"] or "cli"),
            "external_user_id": str(row["external_user_id"] or ""),
            "actor_id": str(row["actor_id"] or "local-user"),
            "display_name": str(row.get("display_name") or ""),
            "metadata": _json_loads(row["metadata_json"], {}),
            "created_at": float(row["created_at"] or 0.0),
            "updated_at": float(row["updated_at"] or 0.0),
            "last_seen_at": float(row.get("last_seen_at") or 0.0),
        }

    @staticmethod
    def _decode_operational_feedback_row(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "feedback_id": str(row["feedback_id"]),
            "workspace_id": str(row["workspace_id"] or "local-workspace"),
            "user_id": str(row["user_id"] or "local-user"),
            "category": str(row["category"] or "runtime"),
            "entity_id": str(row["entity_id"] or ""),
            "outcome": str(row["outcome"] or "neutral"),
            "reward": float(row["reward"] or 0.0),
            "latency_ms": float(row["latency_ms"] or 0.0),
            "recovery_count": int(row["recovery_count"] or 0),
            "payload": _json_loads(row["payload_json"], {}),
            "created_at": float(row["created_at"] or 0.0),
        }

    @staticmethod
    def _decode_global_tool_reliability_row(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "stat_id": str(row["stat_id"]),
            "scope": str(row["scope"] or "global"),
            "tool_name": str(row["tool_name"] or "unknown"),
            "success_count": int(row["success_count"] or 0),
            "failure_count": int(row["failure_count"] or 0),
            "sample_count": int(row["sample_count"] or 0),
            "avg_reward": float(row["avg_reward"] or 0.0),
            "avg_latency_ms": float(row["avg_latency_ms"] or 0.0),
            "metadata": _json_loads(row["metadata_json"], {}),
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
    "ConversationRepository",
    "ConnectorRepository",
    "ChannelIdentityRepository",
    "ExecutionRepository",
    "LearningRepository",
    "LocalAuthRepository",
    "LocalAuthSessionRepository",
    "OutboxRepository",
    "PermissionGrantRepository",
    "PrivacyRepository",
    "RunIndexRepository",
    "RuntimeDatabase",
    "ThreadRepository",
    "WorkspaceSyncAdapter",
    "get_runtime_database",
    "reset_runtime_database",
]
