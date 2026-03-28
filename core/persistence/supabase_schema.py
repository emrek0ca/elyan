from __future__ import annotations

from pathlib import Path

from sqlalchemy.schema import CreateIndex, CreateTable
from sqlalchemy.dialects import postgresql

from .runtime_db import WORKSPACE_METADATA

WORKSPACE_SCOPED_TABLES = (
    "workspace_memberships",
    "workspace_devices",
    "workspace_policies",
    "workspace_threads",
    "workspace_thread_snapshots",
    "workspace_approvals",
    "connector_accounts",
    "connector_scopes",
    "connector_health",
    "connector_action_traces",
    "billing_customers",
    "subscriptions",
    "entitlement_snapshots",
    "usage_ledger",
    "workspace_audit_index",
    "sync_receipts",
    "workspace_users",
    "workspace_user_sessions",
    "workspace_data_policies",
    "workspace_user_preference_profiles",
    "workspace_operational_feedback",
    "workspace_tool_reliability",
)


def render_supabase_schema_sql() -> str:
    dialect = postgresql.dialect()
    statements = [
        "-- Elyan workspace schema for Supabase/Postgres",
        "-- Generated from runtime metadata. Apply with a service role or direct postgres access.",
        "create extension if not exists pgcrypto;",
        "",
    ]
    for table in WORKSPACE_METADATA.sorted_tables:
        statements.append(f"{CreateTable(table).compile(dialect=dialect)};")
        statements.append("")
        for index in table.indexes:
            statements.append(f"{CreateIndex(index).compile(dialect=dialect)};")
        if table.indexes:
            statements.append("")
    return "\n".join(statements).strip() + "\n"


def render_supabase_rls_sql() -> str:
    lines = [
        "-- Elyan workspace row-level security defaults",
        "-- Server code should set request.jwt.claim.workspace_id or run with service role.",
        "",
    ]
    for table_name in WORKSPACE_SCOPED_TABLES:
        lines.extend(
            [
                f"alter table if exists public.{table_name} enable row level security;",
                f"drop policy if exists {table_name}_workspace_isolation on public.{table_name};",
                (
                    f"create policy {table_name}_workspace_isolation on public.{table_name} "
                    "using (workspace_id = current_setting('request.jwt.claim.workspace_id', true)) "
                    "with check (workspace_id = current_setting('request.jwt.claim.workspace_id', true));"
                ),
                "",
            ]
        )
    return "\n".join(lines).strip() + "\n"


def write_supabase_bootstrap_files(root: str | Path) -> tuple[Path, Path]:
    base = Path(root).expanduser().resolve()
    base.mkdir(parents=True, exist_ok=True)
    schema_path = base / "001_workspace_schema.sql"
    rls_path = base / "002_workspace_rls.sql"
    schema_path.write_text(render_supabase_schema_sql(), encoding="utf-8")
    rls_path.write_text(render_supabase_rls_sql(), encoding="utf-8")
    return schema_path, rls_path


__all__ = [
    "render_supabase_rls_sql",
    "render_supabase_schema_sql",
    "write_supabase_bootstrap_files",
]
