"""CLI command handler for workspace billing and credit operations."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from core.billing.workspace_billing import get_workspace_billing_store
from core.persistence import get_runtime_database


def _workspace_id(args: Any) -> str:
    return str(getattr(args, "workspace_id", "") or getattr(args, "workspace", "") or "local-workspace").strip() or "local-workspace"


def _format_timestamp(value: Any) -> str:
    try:
        numeric = float(value or 0.0)
    except Exception:
        numeric = 0.0
    if numeric <= 0:
        return "-"
    return datetime.fromtimestamp(numeric).strftime("%Y-%m-%d %H:%M:%S")


def _print_summary(summary: dict[str, Any]) -> None:
    plan = summary.get("plan") or {}
    balance = summary.get("credit_balance") or {}
    usage = summary.get("usage_summary") or {}
    recent = summary.get("recent_usage_summary") or {}
    usage_period = usage.get("period") if isinstance(usage, dict) else {}
    upgrade_hint = summary.get("upgrade_hint") or (usage.get("upgrade_hint") if isinstance(usage, dict) else None)
    top_sources = list(summary.get("top_cost_sources") or (usage.get("top_cost_sources") if isinstance(usage, dict) else []) or [])
    triggered_limits = list(summary.get("triggered_limits") or (usage.get("triggered_limits") if isinstance(usage, dict) else []) or [])
    reset_at = summary.get("reset_at") or balance.get("reset_at") or (usage_period.get("reset_at") if isinstance(usage_period, dict) else 0)

    print(f"\nWorkspace: {summary.get('workspace_id', '-')}")
    print(f"Plan:       {plan.get('label', '-')}" if isinstance(plan, dict) else f"Plan:       {plan}")
    print(
        "Credits:    "
        f"{int(balance.get('total') or 0):,} "
        f"(included {int(balance.get('included') or 0):,} / purchased {int(balance.get('purchased') or 0):,})"
    )
    print(f"Reset at:   {_format_timestamp(reset_at)}")
    print(f"Usage:      {int(recent.get('requests') or 0):,} request / {int(recent.get('estimated_credits') or 0):,} credit")
    if top_sources:
        first = top_sources[0]
        if isinstance(first, dict):
            print(f"Top source: {first.get('source', '-')}: {int(first.get('credits') or 0):,} credit")
    if triggered_limits:
        first = triggered_limits[0]
        if isinstance(first, dict):
            print(f"Limit:      {first.get('metric', '-')}: {first.get('status', '-')}")
    if upgrade_hint:
        if isinstance(upgrade_hint, dict):
            print(f"Hint:       {upgrade_hint.get('message', '-')}")


def _print_seat_summary(seats: dict[str, Any]) -> None:
    print(f"\nWorkspace: {seats.get('workspace_id', '-')}")
    print(
        "Seats:      "
        f"{int(seats.get('seats_used') or 0):,}/"
        f"{int(seats.get('seat_limit') or 0):,}"
        f" (available {int(seats.get('seats_available') or 0):,})"
    )
    assignments = list(seats.get("assignments") or [])
    if assignments:
        print("Assignments:")
        for item in assignments[:20]:
            if not isinstance(item, dict):
                continue
            actor_id = str(item.get("actor_id") or "").strip() or "-"
            assigned_by = str(item.get("assigned_by") or "").strip() or "-"
            status = str(item.get("status") or "active").strip()
            updated_at = _format_timestamp(item.get("updated_at") or item.get("created_at"))
            print(f"  - {actor_id} | {status} | by {assigned_by} | {updated_at}")


def run(args: Any) -> None:
    subcommand = str(getattr(args, "subcommand", "status") or "status").strip().lower()
    store = get_workspace_billing_store()
    runtime_db = get_runtime_database()
    workspace_id = _workspace_id(args)

    if subcommand == "status":
        _print_summary(store.get_workspace_summary(workspace_id))
        return

    if subcommand == "plans":
        print("\nAvailable plans:")
        for plan in store.list_plans():
            metadata = dict(plan.get("metadata") or {})
            weekly_credit_limit = metadata.get("weekly_credit_limit") or 0
            monthly_soft_limit = metadata.get("monthly_soft_limit") or 0
            priority_level = metadata.get("priority_level") or "-"
            print(
                f"  - {plan.get('plan_id', '-')}: {plan.get('label', '-')}"
                f" | included {int(plan.get('included_credits') or 0):,}"
                f" | seats {int(plan.get('seat_limit') or 0)}"
                f" | connectors {int(plan.get('connector_limit') or 0)}"
                f" | weekly {int(weekly_credit_limit or 0):,}"
                f" | monthly {int(monthly_soft_limit or 0):,}"
                f" | priority {priority_level}"
            )
        return

    if subcommand == "inspect":
        limit = max(1, int(getattr(args, "limit", 10) or 10))
        print(f"\nWorkspace: {workspace_id}")
        _print_summary(store.get_workspace_summary(workspace_id))
        print("\nRecent ledger:")
        for entry in store.get_credit_ledger(workspace_id, limit=limit).get("items", []):
            print(
                f"  - {entry.get('entry_type', '-')}: {int(entry.get('delta_credits') or 0):+}"
                f" | {entry.get('bucket', '-')}"
                f" | {entry.get('created_at', '-')}"
            )
        print("\nRecent events:")
        for event in store.get_billing_events(workspace_id, limit=limit).get("items", []):
            print(
                f"  - {event.get('event_type', '-')}: {event.get('status', '-')}"
                f" | {event.get('reference_id', '-')}"
                f" | {event.get('created_at', '-')}"
            )
        return

    if subcommand == "grant":
        credits = int(getattr(args, "credits", 0) or 0)
        if credits <= 0:
            print("credits must be greater than zero")
            return
        reference_id = str(getattr(args, "reference_id", "") or f"cli:{workspace_id}:{int(datetime.now().timestamp())}").strip()
        actor_id = str(getattr(args, "actor_id", "") or "cli-admin").strip() or "cli-admin"
        result = store.record_credit_grant(
            workspace_id,
            credits,
            bucket=str(getattr(args, "bucket", "manual") or "manual"),
            reference_id=reference_id,
            metadata={
                "source": "cli",
                "actor_id": actor_id,
                "note": str(getattr(args, "note", "") or "").strip(),
            },
        )
        balance = result.get("balance") or {}
        print(f"\nGranted {credits:,} credits to {workspace_id}")
        print(f"New balance: {int(balance.get('total') or 0):,}")
        return

    if subcommand == "reset-weekly":
        balance = store.get_credit_balance(workspace_id)
        print(f"\nWorkspace: {workspace_id}")
        print(f"Plan:      {balance.get('plan_label', '-')}")
        print(f"Reset at:  {_format_timestamp(balance.get('reset_at'))}")
        print(f"Credits:   {int(balance.get('total') or 0):,}")
        print("Weekly reset refreshed safely.")
        return

    if subcommand == "backfill":
        requested_workspace_ids = [workspace_id] if str(getattr(args, "workspace_id", "") or getattr(args, "workspace", "") or "").strip() else None
        result = store.backfill_workspaces(requested_workspace_ids)
        print(f"\nBackfill complete for {int(result.get('count') or 0):,} workspace(s)")
        for item in result.get("workspaces", []):
            if not isinstance(item, dict):
                continue
            summary = dict(item.get("summary") or {})
            plan = summary.get("plan") or {}
            credit_balance = summary.get("credit_balance") or {}
            print(
                f"  - {item.get('workspace_id', '-')}: "
                f"{plan.get('label', '-')}"
                f" | {summary.get('subscription_state', {}).get('status', '-')}"
                f" | credits {int(credit_balance.get('total') or 0):,}"
            )
        if result.get("count") == 1:
            _print_summary(dict(result.get("workspaces", [{}])[0].get("summary") or {}))
        return

    if subcommand == "seats":
        action = str(getattr(args, "action", "list") or "list").strip().lower()
        access = runtime_db.access
        if action == "list":
            seats = access.seat_summary(workspace_id)
            print(f"\nWorkspace: {workspace_id}")
            _print_seat_summary(seats)
            members = access.list_memberships(workspace_id, include_users=True)
            if members:
                print("Members:")
                for member in members:
                    print(
                        f"  - {member.get('actor_id', '-')}: "
                        f"{member.get('role', '-')}"
                        f" | seat={'yes' if member.get('seat_assigned') else 'no'}"
                    )
            return
        actor_id = str(getattr(args, "actor_id", "") or "").strip()
        if not actor_id:
            print("actor_id must be provided for seat assignment changes")
            return
        assigned_by = str(getattr(args, "assigned_by", "") or "cli-admin").strip() or "cli-admin"
        if action == "assign":
            assignment = access.assign_seat(workspace_id=workspace_id, actor_id=actor_id, assigned_by=assigned_by)
            print(f"\nSeat assigned to {actor_id} in {workspace_id}")
            _print_seat_summary(access.seat_summary(workspace_id))
            print(f"Assignment id: {assignment.get('assignment_id', '-')}")
            return
        if action == "release":
            released = access.release_seat(
                workspace_id=workspace_id,
                actor_id=actor_id,
                released_by=assigned_by,
            )
            if not released:
                print("seat assignment not found")
                return
            print(f"\nSeat released for {actor_id} in {workspace_id}")
            _print_seat_summary(access.seat_summary(workspace_id))
            return
        print(f"Unknown seats action: {action}")
        return

    print(f"Unknown billing subcommand: {subcommand}")
