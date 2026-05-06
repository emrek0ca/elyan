from __future__ import annotations

import hashlib
import calendar
import math
import os
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover - Python builds without zoneinfo support
    ZoneInfo = None  # type: ignore[assignment]

from core.billing.commercial_types import PLAN_CATALOG, TOKEN_PACK_CATALOG, get_plan, get_token_pack
from core.billing.iyzico_provider import IyzicoProvider
from core.billing.payment_provider import BillingProfile, CheckoutRequest, ProviderCompletion
from core.persistence import get_runtime_database
from core.observability.trace_context import get_trace_context
from core.storage_paths import resolve_elyan_data_dir


def _now() -> float:
    return time.time()


def _workspace_key(workspace_id: str | None) -> str:
    return str(workspace_id or "local-workspace").strip() or "local-workspace"


def _stable_id(prefix: str, *parts: str) -> str:
    joined = "::".join(str(part or "").strip() for part in parts)
    digest = hashlib.sha1(joined.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


def _period_key(ts: float | None = None) -> str:
    return time.strftime("%Y-%m", time.gmtime(float(ts or _now())))


def _timezone(name: str | None = None) -> timezone:
    tz_name = str(name or "UTC").strip() or "UTC"
    if ZoneInfo is not None:
        try:
            return ZoneInfo(tz_name)
        except Exception:
            pass
    if tz_name.upper() == "UTC":
        return timezone.utc
    return timezone.utc


def _month_window(dt: datetime, anchor_day: int, tz_name: str) -> tuple[str, datetime, datetime]:
    anchor = max(1, min(int(anchor_day or 1), 28))
    current_anchor = dt.replace(day=min(anchor, calendar.monthrange(dt.year, dt.month)[1]), hour=0, minute=0, second=0, microsecond=0)
    if dt.day < anchor:
        month = dt.month - 1 or 12
        year = dt.year - 1 if dt.month == 1 else dt.year
        current_anchor = dt.replace(
            year=year,
            month=month,
            day=min(anchor, calendar.monthrange(year, month)[1]),
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
    next_month = current_anchor.month + 1
    next_year = current_anchor.year
    if next_month > 12:
        next_month = 1
        next_year += 1
    next_anchor = current_anchor.replace(
        year=next_year,
        month=next_month,
        day=min(anchor, calendar.monthrange(next_year, next_month)[1]),
    )
    period_key = f"monthly:{current_anchor.date().isoformat()}:{tz_name}"
    return period_key, current_anchor, next_anchor


def _week_window(dt: datetime, anchor_weekday: int, tz_name: str) -> tuple[str, datetime, datetime]:
    anchor = max(0, min(int(anchor_weekday or 0), 6))
    days_since_anchor = (dt.weekday() - anchor) % 7
    current_anchor = (dt - timedelta(days=days_since_anchor)).replace(hour=0, minute=0, second=0, microsecond=0)
    next_anchor = current_anchor + timedelta(days=7)
    period_key = f"weekly:{current_anchor.date().isoformat()}:{tz_name}"
    return period_key, current_anchor, next_anchor


def _billing_period_info(plan_id: str, *, ts: float | None = None) -> dict[str, Any]:
    plan = get_plan(plan_id)
    metadata = dict(plan.metadata or {})
    reset_policy = dict(metadata.get("reset_policy") or {})
    cycle = str(metadata.get("billing_cycle") or reset_policy.get("type") or ("weekly" if plan.plan_id == "free" else "monthly")).strip().lower()
    tz_name = str(reset_policy.get("timezone") or metadata.get("reset_timezone") or "Europe/Istanbul").strip() or "Europe/Istanbul"
    anchor_weekday = int(reset_policy.get("anchor_weekday") or metadata.get("reset_anchor_weekday") or 0)
    anchor_day = int(reset_policy.get("anchor_day") or metadata.get("reset_anchor_day") or 1)
    tz = _timezone(tz_name)
    now_dt = datetime.fromtimestamp(float(ts or _now()), tz=tz)
    if cycle == "weekly":
        period_key, period_start, next_boundary = _week_window(now_dt, anchor_weekday, tz_name)
    else:
        period_key, period_start, next_boundary = _month_window(now_dt, anchor_day, tz_name)
    return {
        "cycle": cycle,
        "period": period_key,
        "period_start": period_start.timestamp(),
        "reset_at": next_boundary.timestamp(),
        "timezone": tz_name,
        "anchor_weekday": anchor_weekday,
        "anchor_day": anchor_day,
    }


def _plan_entitlements(plan_id: str) -> dict[str, Any]:
    plan = get_plan(plan_id)
    metadata = dict(plan.metadata or {})
    tool_access = dict(metadata.get("tool_access") or {})
    reset_policy = dict(metadata.get("reset_policy") or {})
    weekly_credit_limit = int(metadata.get("weekly_credit_limit") or (plan.included_credits if str(metadata.get("billing_cycle") or "") == "weekly" else 0))
    monthly_soft_limit = int(metadata.get("monthly_soft_limit") or plan.included_credits)
    max_context_size = int(metadata.get("max_context_size") or 8192)
    memory_retention_days = int(metadata.get("memory_retention_days") or 30)
    requests_per_minute = int(metadata.get("requests_per_minute") or 30)
    credit_spend_cap_per_hour = int(metadata.get("credit_spend_cap_per_hour") or max(1000, plan.included_credits // 8))
    weekly_hard_cap = int(metadata.get("weekly_hard_cap") or weekly_credit_limit or 0)
    priority_level = str(metadata.get("priority_level") or "standard")
    rollover_policy = str(metadata.get("rollover_policy") or ("none" if plan.plan_id == "free" else "carry"))
    monthly_usage_budget = int(metadata.get("monthly_usage_budget") or plan.included_credits or 10_000)
    return {
        "plan_id": plan.plan_id,
        "included_credits": int(plan.included_credits),
        "weekly_credit_limit": weekly_credit_limit,
        "monthly_soft_limit": monthly_soft_limit,
        "seat_limit": int(plan.seat_limit),
        "connector_limit": int(plan.connector_limit),
        "artifact_limit": int(plan.artifact_limit),
        "premium_models": bool(plan.premium_models),
        "support_tier": str(plan.support_tier),
        "monthly_usage_budget": monthly_usage_budget,
        "max_threads": int(metadata.get("max_threads") or {"free": 12, "pro": 120, "team": 600, "enterprise": 5000}.get(plan.plan_id, 12)),
        "max_connectors": int(plan.connector_limit),
        "artifact_exports": int(plan.artifact_limit),
        "team_seats": int(plan.seat_limit),
        "max_context_size": max_context_size,
        "memory_retention_days": memory_retention_days,
        "tool_access": {
            "web_tools": bool(tool_access.get("web_tools", True)),
            "file_analysis": bool(tool_access.get("file_analysis", True)),
            "voice_features": bool(tool_access.get("voice_features", False)),
            "screen_features": bool(tool_access.get("screen_features", False)),
            "multi_agent": bool(tool_access.get("multi_agent", False)),
            "premium_memory": bool(tool_access.get("premium_memory", False)),
            "priority_queue": bool(tool_access.get("priority_queue", False)),
            "deep_mode": bool(tool_access.get("deep_mode", False)),
        },
        "deep_mode": bool(metadata.get("deep_mode", False)),
        "multi_agent": bool(metadata.get("multi_agent", False)),
        "priority_queue": bool(metadata.get("priority_queue", False)),
        "priority_level": priority_level,
        "rollover_policy": rollover_policy,
        "reset_policy": reset_policy,
        "requests_per_minute": requests_per_minute,
        "credit_spend_cap_per_hour": credit_spend_cap_per_hour,
        "weekly_hard_cap": weekly_hard_cap,
        "workspace_policy": metadata,
    }


_BILLING_PROFILE_FIELDS = (
    "full_name",
    "email",
    "phone",
    "identity_number",
    "address_line1",
    "city",
    "zip_code",
    "country",
)


@dataclass
class UsageLedgerEntry:
    usage_id: str
    workspace_id: str
    metric: str
    amount: int
    created_at: float = field(default_factory=_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "UsageLedgerEntry":
        return cls(
            usage_id=str(payload.get("usage_id") or f"usage_{int(_now() * 1000)}"),
            workspace_id=str(payload.get("workspace_id") or "local-workspace"),
            metric=str(payload.get("metric") or "unknown"),
            amount=max(0, int(payload.get("amount") or 0)),
            created_at=float(payload.get("created_at") or _now()),
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass
class WorkspaceBillingRecord:
    workspace_id: str
    plan_id: str = "free"
    status: str = "inactive"
    billing_customer: str = ""
    stripe_customer_id: str = ""
    stripe_subscription_id: str = ""
    current_period_end: float = 0.0
    seats: int = 1
    checkout_url: str = ""
    portal_url: str = ""
    updated_at: float = field(default_factory=_now)
    metadata: dict[str, Any] = field(default_factory=dict)
    usage: list[UsageLedgerEntry] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["usage"] = [item.to_dict() for item in self.usage]
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "WorkspaceBillingRecord":
        return cls(
            workspace_id=str(payload.get("workspace_id") or "local-workspace"),
            plan_id=str(payload.get("plan_id") or "free"),
            status=str(payload.get("status") or "inactive"),
            billing_customer=str(payload.get("billing_customer") or ""),
            stripe_customer_id=str(payload.get("stripe_customer_id") or ""),
            stripe_subscription_id=str(payload.get("stripe_subscription_id") or ""),
            current_period_end=float(payload.get("current_period_end") or 0.0),
            seats=max(1, int(payload.get("seats") or 1)),
            checkout_url=str(payload.get("checkout_url") or ""),
            portal_url=str(payload.get("portal_url") or ""),
            updated_at=float(payload.get("updated_at") or _now()),
            metadata=dict(payload.get("metadata") or {}),
            usage=[UsageLedgerEntry.from_dict(item) for item in list(payload.get("usage") or []) if isinstance(item, dict)],
        )


class WorkspaceBillingStore:
    def __init__(self, storage_path: Path | None = None) -> None:
        self.storage_path = Path(storage_path or (resolve_elyan_data_dir() / "billing" / "workspaces.json")).expanduser()
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self._records: dict[str, WorkspaceBillingRecord] = {}
        self._repository = get_runtime_database().billing
        self._provider = IyzicoProvider()
        self._load()

    def _load(self) -> None:
        self._repository.ensure_legacy_import(self.storage_path)
        payload = self._repository.load_workspace_records()
        self._records = {
            str(workspace_id): WorkspaceBillingRecord.from_dict(item)
            for workspace_id, item in payload.items()
            if isinstance(item, dict)
        }

    def _save(self) -> None:
        for record in self._records.values():
            self._repository.upsert_workspace(record.to_dict())

    def _workspace(self, workspace_id: str) -> WorkspaceBillingRecord:
        key = _workspace_key(workspace_id)
        record = self._records.get(key)
        if record is None:
            record = WorkspaceBillingRecord(
                workspace_id=key,
                plan_id="free",
                status="active" if key == "local-workspace" else "inactive",
                seats=get_plan("free").seat_limit,
                billing_customer=f"ws_{hashlib.sha1(key.encode('utf-8')).hexdigest()[:12]}",
                metadata={
                    "workspace_owned": True,
                    "hybrid_billing": True,
                    "provider": self._provider.provider_name,
                },
            )
            self._records[key] = record
            self._save()
        return record

    @staticmethod
    def _normalize_status(value: str) -> str:
        normalized = str(value or "").strip().lower()
        if normalized in {"active", "trialing", "pending", "past_due", "unpaid", "overdue", "inactive", "cancelled", "canceled"}:
            if normalized == "overdue":
                return "past_due"
            return "inactive" if normalized in {"cancelled", "canceled"} else normalized
        if normalized in {"success", "succeeded", "paid", "completed"}:
            return "active"
        if normalized in {"failed", "declined"}:
            return "past_due"
        return "inactive"

    @staticmethod
    def _is_success_status(value: str) -> bool:
        return str(value or "").strip().lower() in {"active", "trialing", "success", "succeeded", "paid", "completed"}

    @staticmethod
    def _is_failure_status(value: str) -> bool:
        return str(value or "").strip().lower() in {"failed", "declined", "cancelled", "canceled", "past_due", "unpaid", "overdue"}

    def _effective_plan_id(self, record: WorkspaceBillingRecord) -> str:
        normalized = self._normalize_status(record.status)
        if normalized in {"active", "trialing"}:
            return str(record.plan_id or "free").strip().lower() or "free"
        return "free"

    def _degraded_reason(self, record: WorkspaceBillingRecord) -> str:
        normalized = self._normalize_status(record.status)
        if normalized in {"inactive", "past_due", "unpaid"} and str(record.plan_id or "free").strip().lower() != "free":
            return f"subscription_{normalized}"
        return ""

    @staticmethod
    def _normalize_billing_profile_payload(payload: dict[str, Any] | None) -> tuple[dict[str, str], list[str]]:
        normalized = {
            field: str((payload or {}).get(field) or "").strip()
            for field in _BILLING_PROFILE_FIELDS
        }
        missing = [field for field, value in normalized.items() if not value]
        return normalized, missing

    @staticmethod
    def _public_checkout_status(value: str) -> str:
        normalized = str(value or "").strip().lower()
        if normalized in {"success", "succeeded", "paid", "completed", "active", "trialing", "subscription.order.success"}:
            return "completed"
        if normalized in {"failed", "failure", "declined", "cancelled", "canceled", "past_due", "unpaid", "overdue", "subscription.order.failed"}:
            return "failed"
        return "pending"

    @staticmethod
    def _coerce_timestamp(value: Any) -> float:
        try:
            numeric = float(value or 0.0)
        except Exception:
            return 0.0
        if numeric > 10_000_000_000:
            return numeric / 1000.0
        return numeric

    def _billing_profile_state(self, workspace_id: str) -> dict[str, Any]:
        workspace_key = _workspace_key(workspace_id)
        self._workspace(workspace_key)
        stored = self._repository.get_billing_profile(workspace_key)
        normalized, missing = self._normalize_billing_profile_payload((stored or {}).get("profile") if isinstance(stored, dict) else {})
        return {
            "workspace_id": workspace_key,
            "profile": normalized,
            "is_complete": len(missing) == 0,
            "missing_fields": missing,
            "updated_at": float((stored or {}).get("updated_at") or 0.0) if isinstance(stored, dict) else 0.0,
        }

    @staticmethod
    def _actor_scope_key(workspace_id: str, actor_id: str) -> str:
        workspace_key = _workspace_key(workspace_id)
        actor_key = str(actor_id or "").strip() or workspace_key
        return actor_key

    @staticmethod
    def _bucket_window_key(bucket_type: str, *, ts: float, period_key: str = "") -> str:
        normalized = str(bucket_type or "").strip().lower()
        if normalized == "request_minute":
            return f"minute:{int(float(ts) // 60)}"
        if normalized == "credit_hour":
            return f"hour:{int(float(ts) // 3600)}"
        if normalized == "period_spend":
            return f"period:{str(period_key or '').strip()}"
        return f"window:{int(float(ts))}"

    @staticmethod
    def _limit_hint_for_plan(plan_id: str, *, metric: str, remaining: int, reset_at: float) -> dict[str, Any]:
        plan = get_plan(plan_id)
        label = str(plan.label or plan.plan_id or "Plan")
        upgrade_plan = "pro" if plan.plan_id == "free" else "team"
        if metric in {"requests_per_minute", "credit_spend_cap_per_hour"}:
            action = "Bekle ve yeniden dene"
        else:
            action = "Plan yükselt"
        return {
            "plan_id": plan.plan_id,
            "plan_label": label,
            "upgrade_plan_id": upgrade_plan,
            "message": f"{label} plan limiti yaklaştı.",
            "cta": action,
            "remaining": max(0, int(remaining or 0)),
            "reset_at": float(reset_at or 0.0),
        }

    def _usage_context(self, workspace_id: str, metric: str, amount: int, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        details = dict(metadata or {})
        trace_context = get_trace_context()
        workspace_key = _workspace_key(workspace_id)
        metric_key = str(metric or "unknown").strip().lower() or "unknown"
        if trace_context is not None:
            trace_workspace_id = str(getattr(trace_context, "workspace_id", "") or "").strip()
            trace_session_id = str(getattr(trace_context, "session_id", "") or "").strip()
            trace_request_id = str(getattr(trace_context, "request_id", "") or "").strip()
            trace_id = str(getattr(trace_context, "trace_id", "") or "").strip()
            trace_source = str(getattr(trace_context, "source", "") or "").strip()
            if trace_workspace_id and not str(details.get("workspace_id") or "").strip():
                details["workspace_id"] = trace_workspace_id
            if trace_session_id and not str(details.get("session_id") or "").strip():
                details["session_id"] = trace_session_id
            if trace_request_id and not str(details.get("request_id") or "").strip():
                details["request_id"] = trace_request_id
            if trace_id and not str(details.get("trace_id") or "").strip():
                details["trace_id"] = trace_id
            if trace_source and not str(details.get("trace_source") or "").strip():
                details["trace_source"] = trace_source
        priority = str(details.get("priority") or details.get("priority_level") or "normal").strip().lower() or "normal"
        prompt_length = max(
            0,
            int(details.get("prompt_length") or details.get("chars") or details.get("content_length") or 0),
        )
        input_tokens = max(0, int(details.get("input_tokens") or details.get("prompt_tokens") or 0))
        output_tokens = max(0, int(details.get("output_tokens") or details.get("completion_tokens") or 0))
        reasoning_tokens = max(0, int(details.get("reasoning_tokens") or details.get("thinking_tokens") or 0))
        tool_calls = max(0, int(details.get("tool_calls") or details.get("tools_used") or 0))
        memory_ops = max(0, int(details.get("memory_ops") or details.get("memory_writes") or 0))
        model_name = str(details.get("model_name") or details.get("model") or "").strip()
        provider = str(details.get("provider") or "").strip().lower()
        model_tier = str(details.get("model_tier") or details.get("model_class") or "").strip().lower()
        actor_id = self._actor_scope_key(workspace_key, str(details.get("actor_id") or details.get("user_id") or ""))
        session_id = str(details.get("session_id") or "").strip()
        run_id = str(details.get("run_id") or "").strip()
        mission_id = str(details.get("mission_id") or "").strip()
        reference_id = str(details.get("reference_id") or details.get("billing_reference_id") or run_id or mission_id or "").strip()
        routing_profile = str(details.get("routing_profile") or "balanced").strip().lower() or "balanced"
        review_strictness = str(details.get("review_strictness") or "balanced").strip().lower() or "balanced"
        mode = str(details.get("mode") or details.get("task_type") or "cowork").strip().lower() or "cowork"
        deep_mode = bool(details.get("deep_mode") or details.get("reasoning_mode") or details.get("multi_agent_recommended"))
        queue_priority = bool(details.get("priority_queue") or details.get("queue_priority"))
        estimated_override = details.get("estimated_credits")
        if estimated_override is None:
            estimated_override = details.get("credits")
        period_info = _billing_period_info(self._effective_plan_id(self._workspace(workspace_key)))
        bucket_base = details.get("bucket") or metric_key
        token_estimate = 0
        weighted_tokens = input_tokens + output_tokens + (reasoning_tokens * 2)
        if weighted_tokens > 0:
            token_estimate = int((weighted_tokens + 1199) // 1200)
        return {
            "workspace_id": workspace_key,
            "actor_id": actor_id,
            "session_id": session_id,
            "trace_id": str(details.get("trace_id") or "").strip(),
            "request_id": str(details.get("request_id") or "").strip(),
            "trace_source": str(details.get("trace_source") or "").strip(),
            "run_id": run_id,
            "mission_id": mission_id,
            "reference_id": reference_id,
            "metric": metric_key,
            "amount": max(1, int(amount or 1)),
            "provider": provider,
            "model_name": model_name,
            "model_tier": model_tier,
            "priority": priority,
            "routing_profile": routing_profile,
            "review_strictness": review_strictness,
            "mode": mode,
            "deep_mode": deep_mode,
            "queue_priority": queue_priority,
            "prompt_length": prompt_length,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "reasoning_tokens": reasoning_tokens,
            "tool_calls": tool_calls,
            "memory_ops": memory_ops,
            "estimated_override": estimated_override,
            "token_estimate": token_estimate,
            "bucket_base": str(bucket_base or metric_key).strip().lower() or metric_key,
            "period": str(period_info.get("period") or ""),
            "reset_at": float(period_info.get("reset_at") or 0.0),
            "cycle": str(period_info.get("cycle") or ""),
            "timezone": str(period_info.get("timezone") or "UTC"),
            "metadata": details,
        }

    def _feature_allowed(self, workspace_id: str, feature: str) -> dict[str, Any]:
        record = self._workspace(workspace_id)
        entitlements = _plan_entitlements(self._effective_plan_id(record))
        feature_key = str(feature or "").strip().lower()
        tool_access = dict((entitlements.get("tool_access") or {}))
        if feature_key in {"web_tools", "file_analysis", "voice_features", "screen_features", "multi_agent", "premium_memory", "priority_queue", "deep_mode"}:
            allowed = bool(tool_access.get(feature_key, False))
        elif feature_key == "long_context":
            allowed = int(entitlements.get("max_context_size") or 0) >= 32768
        elif feature_key == "high_priority":
            allowed = bool(tool_access.get("priority_queue", False))
        else:
            allowed = True
        return {
            "allowed": allowed,
            "feature": feature_key,
            "plan_id": self._effective_plan_id(record),
            "reset_at": float(self.get_credit_balance(workspace_id).get("reset_at") or 0.0),
            "entitlements": entitlements,
            "upgrade_hint": self._limit_hint_for_plan(
                self._effective_plan_id(record),
                metric=feature_key,
                remaining=0 if not allowed else 1,
                reset_at=float(self.get_credit_balance(workspace_id).get("reset_at") or 0.0),
            )
            if not allowed
            else None,
            "reason": "feature_not_included" if not allowed else "allowed",
        }

    def _rate_limit_bucket_state(self, workspace_id: str, *, bucket_type: str, bucket_key: str) -> dict[str, Any]:
        normalized_workspace = str(workspace_id or "local-workspace").strip() or "local-workspace"
        normalized_bucket = str(bucket_type or "").strip().lower()
        normalized_key = str(bucket_key or "").strip()
        buckets = self._repository.list_rate_limit_buckets(normalized_workspace, limit=100, bucket_type=normalized_bucket)
        for bucket in buckets:
            if str(bucket.get("bucket_key") or "").strip() == normalized_key:
                return bucket
        return {
            "bucket_id": _stable_id("rl", normalized_workspace, normalized_bucket, normalized_key),
            "workspace_id": normalized_workspace,
            "actor_id": normalized_workspace,
            "metric": normalized_bucket,
            "bucket_type": normalized_bucket,
            "bucket_key": normalized_key,
            "request_count": 0,
            "credit_spend": 0,
            "hard_cap": 0,
            "soft_cap": 0,
            "status": "open",
            "last_allowed_at": 0.0,
            "last_blocked_at": 0.0,
            "last_reason": "",
            "metadata": {},
            "created_at": 0.0,
            "updated_at": 0.0,
        }

    def _record_rate_limit_bucket(
        self,
        workspace_id: str,
        *,
        actor_id: str,
        metric: str,
        bucket_type: str,
        bucket_key: str,
        request_count: int = 0,
        credit_spend: int = 0,
        hard_cap: int = 0,
        soft_cap: int = 0,
        status: str = "open",
        reason: str = "",
        metadata: dict[str, Any] | None = None,
        allowed_at: float = 0.0,
        blocked_at: float = 0.0,
        created_at: float | None = None,
    ) -> dict[str, Any]:
        normalized_workspace = str(workspace_id or "local-workspace").strip() or "local-workspace"
        normalized_actor = self._actor_scope_key(normalized_workspace, actor_id)
        normalized_metric = str(metric or "").strip().lower()
        normalized_bucket = str(bucket_type or "").strip().lower()
        normalized_key = str(bucket_key or "").strip()
        bucket_id = _stable_id("rl", normalized_workspace, normalized_actor, normalized_metric, normalized_bucket, normalized_key)
        existing = self._repository.get_rate_limit_bucket(bucket_id)
        payload = {
            "bucket_id": bucket_id,
            "workspace_id": normalized_workspace,
            "actor_id": normalized_actor,
            "metric": normalized_metric,
            "bucket_type": normalized_bucket,
            "bucket_key": normalized_key,
            "request_count": max(0, int(request_count or 0)),
            "credit_spend": max(0, int(credit_spend or 0)),
            "hard_cap": max(0, int(hard_cap or 0)),
            "soft_cap": max(0, int(soft_cap or 0)),
            "status": str(status or "open").strip().lower() or "open",
            "last_allowed_at": float(allowed_at or 0.0),
            "last_blocked_at": float(blocked_at or 0.0),
            "last_reason": str(reason or "").strip(),
            "metadata": dict(metadata or {}),
            "created_at": float((existing or {}).get("created_at") or created_at or _now()),
            "updated_at": _now(),
        }
        return self._repository.upsert_rate_limit_bucket(payload)

    def _collect_usage_summary(self, workspace_id: str, *, limit: int = 100) -> dict[str, Any]:
        record = self._workspace(workspace_id)
        workspace_key = record.workspace_id
        entitlements = _plan_entitlements(self._effective_plan_id(record))
        balance = self._repository.get_credit_balance(workspace_key)
        period_info = _billing_period_info(self._effective_plan_id(record))
        usage_entries = sorted(record.usage, key=lambda item: item.created_at, reverse=True)
        recent_entries = usage_entries[: max(1, int(limit or 100))]
        recent_events = self._repository.list_usage_events(workspace_key, limit=max(50, min(250, int(limit or 100) * 5)))
        by_metric: Counter[str] = Counter()
        by_actor: Counter[str] = Counter()
        top_sources: Counter[str] = Counter()
        for entry in record.usage:
            entry_metadata = dict(entry.metadata or {})
            estimated = int(entry_metadata.get("estimated_credits") or entry_metadata.get("credits") or 0)
            by_metric[str(entry.metric or "unknown")] += max(0, estimated)
        for event in recent_events:
            actor = str(event.get("actor_id") or workspace_key).strip() or workspace_key
            estimated = int(event.get("estimated_credits") or event.get("actual_credits") or 0)
            by_actor[actor] += max(0, estimated)
            metric_key = str(event.get("metric") or "unknown").strip().lower() or "unknown"
            source_label = str(event.get("model_name") or event.get("provider") or metric_key).strip() or metric_key
            top_sources[source_label] += max(0, estimated)
        triggered_limits: list[dict[str, Any]] = []
        for bucket_type in ("request_minute", "credit_hour", "period_spend"):
            buckets = self._repository.list_rate_limit_buckets(workspace_key, limit=100, bucket_type=bucket_type)
            for bucket in buckets:
                status = str(bucket.get("status") or "open").strip().lower()
                hard_cap = int(bucket.get("hard_cap") or 0)
                soft_cap = int(bucket.get("soft_cap") or 0)
                current = int(bucket.get("request_count") or bucket.get("credit_spend") or 0)
                cap = hard_cap or soft_cap
                if status in {"blocked", "warn"} or (cap > 0 and current >= cap):
                    triggered_limits.append(
                        {
                            "bucket_type": bucket_type,
                            "bucket_key": str(bucket.get("bucket_key") or ""),
                            "metric": str(bucket.get("metric") or ""),
                            "status": status,
                            "current": current,
                            "limit": cap,
                            "reason": str(bucket.get("last_reason") or ""),
                        }
                    )
        period_spend = 0
        for bucket in self._repository.list_rate_limit_buckets(workspace_key, limit=100, bucket_type="period_spend"):
            if str(bucket.get("bucket_key") or "") == str(period_info.get("period") or ""):
                period_spend = max(period_spend, int(bucket.get("credit_spend") or 0))
        request_spend = 0
        for bucket in self._repository.list_rate_limit_buckets(workspace_key, limit=100, bucket_type="request_minute"):
            if str(bucket.get("bucket_key") or ""):
                request_spend = max(request_spend, int(bucket.get("request_count") or 0))
        hour_spend = 0
        for bucket in self._repository.list_rate_limit_buckets(workspace_key, limit=100, bucket_type="credit_hour"):
            if str(bucket.get("bucket_key") or ""):
                hour_spend = max(hour_spend, int(bucket.get("credit_spend") or 0))
        limit_remaining = max(0, int(balance.get("total") or 0))
        upgrade_hint = None
        if self._effective_plan_id(record) == "free" and (triggered_limits or limit_remaining <= max(50, int(entitlements.get("weekly_credit_limit") or 0) // 5)):
            upgrade_hint = self._limit_hint_for_plan("free", metric="weekly_credit_limit", remaining=limit_remaining, reset_at=float(period_info.get("reset_at") or 0.0))
        elif limit_remaining <= max(100, int(entitlements.get("monthly_soft_limit") or 0) // 10):
            upgrade_hint = self._limit_hint_for_plan(self._effective_plan_id(record), metric="monthly_soft_limit", remaining=limit_remaining, reset_at=float(period_info.get("reset_at") or 0.0))
        return {
            "workspace_id": workspace_key,
            "plan_id": self._effective_plan_id(record),
            "period": period_info,
            "credit_balance": balance,
            "remaining_credits": limit_remaining,
            "totals": {
                "requests": int(sum(int(item.amount or 0) for item in record.usage)),
                "estimated_credits": int(sum(int((item.metadata or {}).get("estimated_credits") or (item.metadata or {}).get("credits") or 0) for item in record.usage)),
            },
            "recent_usage": [item.to_dict() for item in recent_entries],
            "usage_events": recent_events[: max(1, int(limit or 100))],
            "by_metric": [
                {"metric": metric, "credits": credits}
                for metric, credits in by_metric.most_common()
            ],
            "by_actor": [
                {"actor_id": actor, "credits": credits}
                for actor, credits in by_actor.most_common()
            ],
            "top_cost_sources": [
                {"source": source, "credits": credits}
                for source, credits in top_sources.most_common()
            ],
            "triggered_limits": triggered_limits,
            "request_spend": int(request_spend),
            "hour_spend": int(hour_spend),
            "period_spend": int(period_spend),
            "upgrade_hint": upgrade_hint,
            "entitlements": entitlements,
        }

    def _enrich_credit_balance(
        self,
        workspace_id: str,
        balance: dict[str, Any],
        *,
        period_info: dict[str, Any] | None = None,
        entitlements: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        record = self._workspace(workspace_id)
        effective_plan_id = self._effective_plan_id(record)
        plan = get_plan(effective_plan_id)
        period_state = period_info or _billing_period_info(effective_plan_id)
        entitlement_state = entitlements or _plan_entitlements(effective_plan_id)
        payload = dict(balance or {})
        payload.update(
            {
                "plan_id": effective_plan_id,
                "plan_label": plan.label,
                "period": str(period_state.get("period") or ""),
                "cycle": str(period_state.get("cycle") or ""),
                "reset_at": float(period_state.get("reset_at") or 0.0),
                "timezone": str(period_state.get("timezone") or "UTC"),
                "rollover_policy": str(entitlement_state.get("rollover_policy") or "carry"),
                "weekly_credit_limit": int(entitlement_state.get("weekly_credit_limit") or 0),
                "monthly_soft_limit": int(entitlement_state.get("monthly_soft_limit") or 0),
                "requests_per_minute": int(entitlement_state.get("requests_per_minute") or 0),
                "credit_spend_cap_per_hour": int(entitlement_state.get("credit_spend_cap_per_hour") or 0),
                "weekly_hard_cap": int(entitlement_state.get("weekly_hard_cap") or 0),
            }
        )
        return payload

    def _rate_limit_snapshot(self, context: dict[str, Any], entitlements: dict[str, Any]) -> dict[str, Any]:
        workspace_id = str(context.get("workspace_id") or "local-workspace").strip() or "local-workspace"
        actor_id = str(context.get("actor_id") or workspace_id).strip() or workspace_id
        metric = str(context.get("metric") or "unknown").strip().lower() or "unknown"
        period = str(context.get("period") or "").strip()
        now = _now()
        request_key = self._bucket_window_key("request_minute", ts=now)
        credit_key = self._bucket_window_key("credit_hour", ts=now)
        period_key = self._bucket_window_key("period_spend", ts=now, period_key=period)
        request_bucket = self._rate_limit_bucket_state(workspace_id, bucket_type="request_minute", bucket_key=request_key)
        credit_bucket = self._rate_limit_bucket_state(workspace_id, bucket_type="credit_hour", bucket_key=credit_key)
        period_bucket = self._rate_limit_bucket_state(workspace_id, bucket_type="period_spend", bucket_key=period_key)
        request_limit = max(0, int(entitlements.get("requests_per_minute") or 0))
        credit_limit = max(0, int(entitlements.get("credit_spend_cap_per_hour") or 0))
        period_limit = max(0, int(entitlements.get("weekly_hard_cap") or entitlements.get("monthly_soft_limit") or 0))
        request_count = int(request_bucket.get("request_count") or 0)
        hour_spend = int(credit_bucket.get("credit_spend") or 0)
        period_spend = int(period_bucket.get("credit_spend") or 0)
        return {
            "workspace_id": workspace_id,
            "actor_id": actor_id,
            "metric": metric,
            "period": period,
            "request_key": request_key,
            "credit_key": credit_key,
            "period_key": period_key,
            "request_bucket": request_bucket,
            "credit_bucket": credit_bucket,
            "period_bucket": period_bucket,
            "request_limit": request_limit,
            "credit_limit": credit_limit,
            "period_limit": period_limit,
            "soft_period_limit": max(0, int(entitlements.get("monthly_soft_limit") or 0)),
            "request_count": request_count,
            "hour_spend": hour_spend,
            "period_spend": period_spend,
            "request_remaining": max(0, request_limit - request_count) if request_limit > 0 else 0,
            "credit_remaining": max(0, credit_limit - hour_spend) if credit_limit > 0 else 0,
            "period_remaining": max(0, period_limit - period_spend) if period_limit > 0 else 0,
        }

    @staticmethod
    def _bucket_status(current: int, limit: int) -> str:
        if limit <= 0:
            return "open"
        if current >= limit:
            return "blocked"
        if current >= max(1, int(limit * 0.8)):
            return "warn"
        return "open"

    def _estimate_credit_cost(self, context: dict[str, Any]) -> int:
        base_estimate = max(0, int(context.get("estimated_override") or 0))
        metric_estimate = self.estimate_usage_credits(
            str(context.get("metric") or "unknown"),
            int(context.get("amount") or 1),
            metadata=dict(context.get("metadata") or {}),
        )
        token_estimate = max(0, int(context.get("token_estimate") or 0))
        raw_estimate = max(base_estimate, metric_estimate, token_estimate)
        tool_cost = max(0, int(context.get("tool_calls") or 0))
        memory_cost = max(0, int(context.get("memory_ops") or 0))
        multiplier = 1.0
        if bool(context.get("deep_mode")):
            multiplier += 0.35
        if bool(context.get("queue_priority")) or str(context.get("priority") or "").strip().lower() in {"high", "urgent", "critical"}:
            multiplier += 0.15
        if str(context.get("model_tier") or "").strip().lower() in {"premium", "pro", "frontier"}:
            multiplier += 0.2
        if str(context.get("routing_profile") or "").strip().lower() == "quality_first":
            multiplier += 0.15
        if str(context.get("review_strictness") or "").strip().lower() == "strict":
            multiplier += 0.1
        multiplier = min(multiplier, 2.5)
        composite = max(0, int(math.ceil((raw_estimate + tool_cost + memory_cost) * multiplier)))
        return composite

    def _usage_event_payload(
        self,
        context: dict[str, Any],
        *,
        usage_id: str,
        status: str,
        event_type: str = "usage",
        estimated_credits: int = 0,
        actual_credits: int = 0,
    ) -> dict[str, Any]:
        metadata = dict(context.get("metadata") or {})
        return {
            "event_id": usage_id,
            "workspace_id": str(context.get("workspace_id") or "local-workspace"),
            "actor_id": str(context.get("actor_id") or ""),
            "session_id": str(context.get("session_id") or ""),
            "run_id": str(context.get("run_id") or ""),
            "usage_id": usage_id,
            "metric": str(context.get("metric") or "unknown"),
            "event_type": event_type,
            "status": status,
            "reference_id": str(context.get("reference_id") or usage_id),
            "provider": str(context.get("provider") or ""),
            "model_name": str(context.get("model_name") or ""),
            "priority": str(context.get("priority") or "normal"),
            "input_tokens": max(0, int(context.get("input_tokens") or 0)),
            "output_tokens": max(0, int(context.get("output_tokens") or 0)),
            "reasoning_tokens": max(0, int(context.get("reasoning_tokens") or 0)),
            "tool_calls": max(0, int(context.get("tool_calls") or 0)),
            "memory_ops": max(0, int(context.get("memory_ops") or 0)),
            "prompt_length": max(0, int(context.get("prompt_length") or 0)),
            "estimated_credits": max(0, int(estimated_credits or 0)),
            "actual_credits": max(0, int(actual_credits or 0)),
            "bucket": str(context.get("bucket_base") or context.get("metric") or "usage"),
            "metadata": metadata,
            "created_at": _now(),
        }

    def record_usage_event(self, context: dict[str, Any]) -> dict[str, Any]:
        usage_id = str(context.get("usage_id") or context.get("reference_id") or _stable_id("usageevt", str(context.get("workspace_id") or "local-workspace"), str(context.get("metric") or "unknown"), str(_now()))).strip()
        estimated_credits = max(0, int(context.get("estimated_credits") or 0))
        actual_credits = max(0, int(context.get("actual_credits") or estimated_credits))
        status = str(context.get("status") or "recorded").strip().lower() or "recorded"
        event_type = str(context.get("event_type") or "usage").strip().lower() or "usage"
        payload = self._usage_event_payload(
            context,
            usage_id=usage_id,
            status=status,
            event_type=event_type,
            estimated_credits=estimated_credits,
            actual_credits=actual_credits,
        )
        return self._repository.record_usage_event(payload)

    def check_feature_access(self, workspace_id: str, feature: str) -> dict[str, Any]:
        return self._feature_allowed(workspace_id, feature)

    def get_usage_summary(self, workspace_id: str, *, limit: int = 100) -> dict[str, Any]:
        return self._collect_usage_summary(workspace_id, limit=limit)

    def _callback_url(self, workspace_id: str, *, mode: str, reference_id: str) -> str:
        base_url = str(os.getenv("IYZICO_PUBLIC_CALLBACK_BASE_URL", "") or "").strip().rstrip("/")
        if not base_url:
            return ""
        return self._append_query(
            f"{base_url}/api/v1/billing/callbacks/iyzico",
            {
                "workspace_id": workspace_id,
                "mode": mode,
                "reference_id": reference_id,
            },
        )

    def _require_checkout_billing_profile(self, workspace_id: str) -> BillingProfile | None:
        if not self._provider._real_api_enabled():
            return None
        profile_state = self._billing_profile_state(workspace_id)
        if not profile_state["is_complete"]:
            raise RuntimeError(f"billing_profile_incomplete:{','.join(profile_state['missing_fields'])}")
        return BillingProfile(**dict(profile_state["profile"]))

    def _serialize_checkout_session(self, session: dict[str, Any] | None) -> dict[str, Any] | None:
        if not isinstance(session, dict):
            return None
        return {
            "reference_id": str(session.get("reference_id") or ""),
            "workspace_id": str(session.get("workspace_id") or "local-workspace"),
            "mode": str(session.get("mode") or "subscription"),
            "catalog_id": str(session.get("catalog_id") or ""),
            "provider": str(session.get("provider") or self._provider.provider_name),
            "status": self._public_checkout_status(str(session.get("status") or "pending")),
            "provider_status": str(session.get("status") or "pending"),
            "launch_url": str(session.get("payment_page_url") or ""),
            "payment_page_url": str(session.get("payment_page_url") or ""),
            "callback_url": str(session.get("callback_url") or ""),
            "provider_payment_id": str(session.get("provider_payment_id") or ""),
            "subscription_reference_code": str(session.get("subscription_reference_code") or ""),
            "created_at": float(session.get("created_at") or 0.0),
            "updated_at": float(session.get("updated_at") or 0.0),
            "completed_at": float(session.get("completed_at") or 0.0),
        }

    def _persist_checkout_session(
        self,
        *,
        reference_id: str,
        workspace_id: str,
        mode: str,
        catalog_id: str,
        provider: str,
        status: str,
        payment_page_url: str,
        callback_url: str,
        provider_token: str = "",
        provider_payment_id: str = "",
        subscription_reference_code: str = "",
        raw_last_payload: dict[str, Any] | None = None,
        completed_at: float = 0.0,
    ) -> dict[str, Any]:
        existing = self._repository.get_checkout_session(reference_id)
        return self._repository.upsert_checkout_session(
            {
                "reference_id": reference_id,
                "workspace_id": workspace_id,
                "mode": mode,
                "catalog_id": catalog_id,
                "provider": provider,
                "provider_token": provider_token or str((existing or {}).get("provider_token") or ""),
                "provider_payment_id": provider_payment_id or str((existing or {}).get("provider_payment_id") or ""),
                "subscription_reference_code": subscription_reference_code or str((existing or {}).get("subscription_reference_code") or ""),
                "status": status,
                "payment_page_url": payment_page_url or str((existing or {}).get("payment_page_url") or ""),
                "callback_url": callback_url or str((existing or {}).get("callback_url") or ""),
                "raw_last_payload": dict(raw_last_payload or (existing or {}).get("raw_last_payload") or {}),
                "created_at": float((existing or {}).get("created_at") or _now()),
                "updated_at": _now(),
                "completed_at": completed_at or float((existing or {}).get("completed_at") or 0.0),
            }
        )

    def _resolve_checkout_session_for_completion(self, completion: ProviderCompletion) -> dict[str, Any] | None:
        if str(completion.reference_id or "").strip():
            session = self._repository.get_checkout_session(str(completion.reference_id or "").strip())
            if session:
                return session
        if str(completion.provider_token or "").strip():
            session = self._repository.get_checkout_session_by_provider_token(str(completion.provider_token or "").strip())
            if session:
                return session
        if str(completion.subscription_reference_code or "").strip():
            session = self._repository.get_checkout_session_by_subscription_reference(str(completion.subscription_reference_code or "").strip())
            if session:
                return session
        return None

    def _apply_provider_completion(self, completion: ProviderCompletion, *, source: str) -> dict[str, Any]:
        session = self._resolve_checkout_session_for_completion(completion)
        workspace_id = str((session or {}).get("workspace_id") or completion.workspace_id or "").strip()
        if not workspace_id:
            raise RuntimeError(
                f"webhook_unresolvable_workspace:ref={completion.reference_id}:"
                f"sub_ref={completion.subscription_reference_code}"
            )
        record = self._workspace(workspace_id)
        mode = str((session or {}).get("mode") or completion.mode or "subscription").strip() or "subscription"
        catalog_id = str((session or {}).get("catalog_id") or completion.catalog_id or "").strip().lower()
        reference_id = str((session or {}).get("reference_id") or completion.reference_id or "").strip()
        checkout_status = self._public_checkout_status(completion.status)
        provider_status = str(completion.status or "pending").strip().lower() or "pending"
        completed_at = self._coerce_timestamp(completion.completed_at) if checkout_status == "completed" else 0.0
        stored_session = None
        if reference_id:
            stored_session = self._persist_checkout_session(
                reference_id=reference_id,
                workspace_id=workspace_id,
                mode=mode,
                catalog_id=catalog_id,
                provider=completion.provider,
                status=provider_status,
                payment_page_url=str((session or {}).get("payment_page_url") or ""),
                callback_url=str((session or {}).get("callback_url") or ""),
                provider_token=str(completion.provider_token or ""),
                provider_payment_id=str(completion.provider_payment_id or ""),
                subscription_reference_code=str(completion.subscription_reference_code or ""),
                raw_last_payload=dict(completion.raw or {}),
                completed_at=completed_at,
            )

        grant_recorded = False
        record.metadata["provider"] = completion.provider
        record.metadata["last_checkout_source"] = source
        record.metadata["last_checkout_event_type"] = str(completion.event_type or "").strip()
        if completion.provider_payment_id:
            record.metadata["provider_payment_id"] = str(completion.provider_payment_id or "").strip()
        if completion.subscription_reference_code:
            record.metadata["provider_subscription_id"] = str(completion.subscription_reference_code or "").strip()
        if stored_session and stored_session.get("payment_page_url"):
            record.checkout_url = str(stored_session.get("payment_page_url") or "")
        if mode == "subscription" and catalog_id:
            record.plan_id = catalog_id
            record.seats = get_plan(catalog_id).seat_limit

        if checkout_status == "completed":
            if mode == "subscription" and catalog_id:
                plan = get_plan(catalog_id)
                record.status = "active"
                period_end = self._coerce_timestamp((completion.metadata or {}).get("end_date"))
                record.current_period_end = period_end or (_now() + (30 * 24 * 60 * 60))
                record.metadata.pop("pending_plan_id", None)
                record.metadata["effective_plan_id"] = plan.plan_id
                if int(plan.included_credits) > 0:
                    self.record_credit_grant(
                        workspace_id=workspace_id,
                        credits=int(plan.included_credits),
                        bucket="included",
                        reference_id=reference_id,
                        metadata={
                            "source": completion.provider,
                            "plan_id": plan.plan_id,
                            "grant_type": "plan_included",
                            "period": _period_key(),
                        },
                    )
                    grant_recorded = True
            elif mode == "token_pack" and catalog_id:
                token_pack = get_token_pack(catalog_id)
                granted_credits = int(completion.credits or (token_pack.credits + token_pack.bonus_credits))
                self.record_credit_grant(
                    workspace_id=workspace_id,
                    credits=granted_credits,
                    bucket="purchased",
                    reference_id=reference_id or token_pack.pack_id,
                    metadata={
                        "source": completion.provider,
                        "token_pack_id": token_pack.pack_id,
                        "pack_id": token_pack.pack_id,
                        "credits": token_pack.credits,
                        "bonus_credits": token_pack.bonus_credits,
                    },
                )
                record.metadata.pop("pending_token_pack_id", None)
                grant_recorded = True
        elif checkout_status == "failed" and mode == "subscription":
            record.status = "past_due" if provider_status in {"past_due", "unpaid", "overdue"} else "inactive"

        degraded_reason = self._degraded_reason(record)
        if degraded_reason:
            record.metadata["degraded_reason"] = degraded_reason
        else:
            record.metadata.pop("degraded_reason", None)
        record.updated_at = _now()
        self._save()

        event_reference = reference_id or str(completion.subscription_reference_code or completion.provider_payment_id or "").strip()
        self._repository.record_billing_event(
            {
                "event_id": _stable_id("billevt", workspace_id, source, mode, event_reference or provider_status),
                "workspace_id": workspace_id,
                "provider": completion.provider,
                "event_type": f"billing.{source}.{mode}.{checkout_status}",
                "status": checkout_status,
                "reference_id": event_reference,
                "payload": {
                    "workspace_id": workspace_id,
                    "mode": mode,
                    "catalog_id": catalog_id,
                    "provider_status": provider_status,
                    "source": source,
                    "completion": completion.to_dict(),
                },
            }
        )
        self._snapshot_entitlements(workspace_id, scope=f"{source}_{mode}")
        latest_session = self._repository.get_checkout_session(reference_id) if reference_id else stored_session
        return {
            "event_type": str(completion.event_type or ""),
            "provider": completion.provider,
            "workspace_id": workspace_id,
            "status": record.status,
            "checkout_status": checkout_status,
            "provider_status": provider_status,
            "effective_plan_id": self._effective_plan_id(record),
            "plan_id": catalog_id if mode == "subscription" else "",
            "token_pack_id": catalog_id if mode == "token_pack" else "",
            "reference_id": reference_id,
            "grant_recorded": grant_recorded,
            "credits": self._repository.get_credit_balance(workspace_id),
            "checkout": self._serialize_checkout_session(latest_session),
            "matched": bool(session or reference_id or completion.workspace_id),
        }

    def _ensure_included_credits(self, record: WorkspaceBillingRecord) -> dict[str, Any]:
        effective_plan_id = self._effective_plan_id(record)
        plan = get_plan(effective_plan_id)
        entitlements = _plan_entitlements(effective_plan_id)
        period_info = _billing_period_info(effective_plan_id)
        period = str(period_info.get("period") or _period_key())
        period_reset_at = float(period_info.get("reset_at") or 0.0)
        rollover_policy = str(entitlements.get("rollover_policy") or "carry").strip().lower() or "carry"
        balance = self._repository.get_credit_balance(record.workspace_id)
        included_period = str(record.metadata.get("included_credit_period") or "").strip()
        included_reference = f"{effective_plan_id}:{period}"
        existing_current_grant = self._repository.list_credit_entries_for_reference(
            record.workspace_id,
            reference_id=included_reference,
            entry_type="grant",
            limit=5,
        )
        current_grant_present = any(
            str((entry.get("metadata") or {}).get("period") or "").strip() == period
            or str(entry.get("reference_id") or "").strip() == included_reference
            for entry in existing_current_grant
        )
        if included_period == period and current_grant_present:
            return self._enrich_credit_balance(record.workspace_id, balance, period_info=period_info, entitlements=entitlements)

        if rollover_policy == "none" and included_period != period:
            included_balance = int(balance.get("included") or 0)
            if included_balance > 0:
                expire_reference = f"{effective_plan_id}:{included_period or 'legacy'}:expire"
                expire_entry_id = _stable_id("expire", record.workspace_id, effective_plan_id, included_period or "legacy")
                self._repository.record_credit_entry(
                    {
                        "entry_id": expire_entry_id,
                        "workspace_id": record.workspace_id,
                        "bucket": "included",
                        "entry_type": "expire",
                        "delta_credits": -included_balance,
                        "reference_id": expire_reference,
                        "metadata": {
                            "grant_type": "period_expire",
                            "expired_period": included_period or "legacy",
                            "next_period": period,
                            "plan_id": effective_plan_id,
                        },
                    }
                )
                self._repository.record_billing_event(
                    {
                        "event_id": _stable_id("billevt", record.workspace_id, "included", "expire", effective_plan_id, included_period or "legacy"),
                        "workspace_id": record.workspace_id,
                        "provider": "internal",
                        "event_type": "billing.included_credits.expired",
                        "status": "applied",
                        "reference_id": expire_reference,
                        "payload": {
                            "workspace_id": record.workspace_id,
                            "plan_id": effective_plan_id,
                            "credits": included_balance,
                            "expired_period": included_period or "legacy",
                            "next_period": period,
                        },
                    }
                )
                balance = self._repository.get_credit_balance(record.workspace_id)

        if int(plan.included_credits) > 0 and not current_grant_present:
            entry_id = _stable_id("included", record.workspace_id, effective_plan_id, period)
            self._repository.record_credit_entry(
                {
                    "entry_id": entry_id,
                    "workspace_id": record.workspace_id,
                    "bucket": "included",
                    "entry_type": "grant",
                    "delta_credits": int(plan.included_credits),
                    "reference_id": included_reference,
                    "metadata": {
                        "grant_type": "weekly_reset" if int(entitlements.get("weekly_credit_limit") or 0) > 0 else "monthly_included",
                        "period": period,
                        "reset_at": period_reset_at,
                        "plan_id": effective_plan_id,
                        "rollover_policy": rollover_policy,
                    },
                }
            )
            self._repository.record_billing_event(
                {
                    "event_id": _stable_id("billevt", record.workspace_id, "included", effective_plan_id, period),
                    "workspace_id": record.workspace_id,
                    "provider": "internal",
                    "event_type": "billing.included_credits.granted",
                    "status": "applied",
                    "reference_id": included_reference,
                    "payload": {
                        "workspace_id": record.workspace_id,
                        "plan_id": effective_plan_id,
                        "credits": int(plan.included_credits),
                        "period": period,
                        "reset_at": period_reset_at,
                        "rollover_policy": rollover_policy,
                    },
                }
            )
            balance = self._repository.get_credit_balance(record.workspace_id)

        record.metadata["included_credit_period"] = period
        record.metadata["included_credit_reset_at"] = period_reset_at
        record.metadata["effective_plan_id"] = effective_plan_id
        record.metadata["rollover_policy"] = rollover_policy
        record.updated_at = _now()
        self._save()
        self._snapshot_entitlements(record.workspace_id, scope="monthly_refresh")
        return self._enrich_credit_balance(record.workspace_id, balance, period_info=period_info, entitlements=entitlements)

    def _snapshot_entitlements(self, workspace_id: str, *, scope: str) -> dict[str, Any]:
        record = self._workspace(workspace_id)
        balance = self._repository.get_credit_balance(record.workspace_id)
        payload = {
            "workspace_id": record.workspace_id,
            "plan_id": self._effective_plan_id(record),
            "requested_plan_id": record.plan_id,
            "status": self._normalize_status(record.status),
            "entitlements": _plan_entitlements(self._effective_plan_id(record)),
            "credits": balance,
            "degraded_reason": self._degraded_reason(record),
        }
        return self._repository.record_entitlement_snapshot(
            {
                "workspace_id": record.workspace_id,
                "scope": scope,
                "payload": payload,
            }
        )

    def list_plans(self) -> list[dict[str, Any]]:
        return [plan.to_dict() for plan in PLAN_CATALOG.values()]

    def list_token_packs(self) -> list[dict[str, Any]]:
        return [pack.to_dict() for pack in TOKEN_PACK_CATALOG.values()]

    def get_billing_profile(self, workspace_id: str) -> dict[str, Any]:
        return self._billing_profile_state(workspace_id)

    def list_known_workspaces(self) -> list[str]:
        return self._repository.list_known_workspace_ids()

    def backfill_workspace(self, workspace_id: str, *, scope: str = "backfill") -> dict[str, Any]:
        workspace_key = _workspace_key(workspace_id)
        summary = self.get_workspace_summary(workspace_key)
        return {
            "workspace_id": workspace_key,
            "scope": str(scope or "backfill").strip() or "backfill",
            "summary": summary,
        }

    def backfill_workspaces(self, workspace_ids: list[str] | None = None, *, scope: str = "backfill") -> dict[str, Any]:
        candidates = list(workspace_ids) if workspace_ids is not None else self.list_known_workspaces()
        normalized = sorted({str(workspace_id or "").strip() for workspace_id in candidates if str(workspace_id or "").strip()})
        results = [self.backfill_workspace(workspace_id, scope=scope) for workspace_id in normalized]
        return {
            "scope": str(scope or "backfill").strip() or "backfill",
            "count": len(results),
            "workspace_ids": normalized,
            "workspaces": results,
        }

    def update_billing_profile(self, workspace_id: str, profile_payload: dict[str, Any]) -> dict[str, Any]:
        record = self._workspace(workspace_id)
        normalized, missing = self._normalize_billing_profile_payload(profile_payload)
        stored = self._repository.upsert_billing_profile(
            record.workspace_id,
            {
                **normalized,
                "updated_at": _now(),
            },
        )
        record.updated_at = _now()
        self._save()
        self._repository.record_billing_event(
            {
                "event_id": _stable_id("billevt", record.workspace_id, "billing_profile", "updated"),
                "workspace_id": record.workspace_id,
                "provider": self._provider.provider_name,
                "event_type": "billing.profile.updated",
                "status": "applied",
                "reference_id": record.workspace_id,
                "payload": {
                    "workspace_id": record.workspace_id,
                    "is_complete": len(missing) == 0,
                    "missing_fields": missing,
                    "updated_at": float(stored.get("updated_at") or _now()) if isinstance(stored, dict) else _now(),
                },
            }
        )
        return self._billing_profile_state(record.workspace_id)

    def get_checkout_session(self, workspace_id: str, reference_id: str, *, refresh: bool = True) -> dict[str, Any] | None:
        workspace_key = _workspace_key(workspace_id)
        normalized_reference = str(reference_id or "").strip()
        if not normalized_reference:
            return None
        session = self._repository.get_checkout_session(normalized_reference)
        if session is None or str(session.get("workspace_id") or "") != workspace_key:
            return None
        if refresh and self._public_checkout_status(str(session.get("status") or "")) == "pending" and str(session.get("provider_token") or "").strip():
            try:
                if str(session.get("mode") or "") == "token_pack":
                    completion = self._provider.retrieve_token_pack_checkout(
                        token=str(session.get("provider_token") or ""),
                        reference_id=normalized_reference,
                    )
                else:
                    completion = self._provider.retrieve_subscription_checkout(
                        token=str(session.get("provider_token") or ""),
                        reference_id=normalized_reference,
                    )
                self._apply_provider_completion(completion, source="callback")
                session = self._repository.get_checkout_session(normalized_reference) or session
            except RuntimeError:
                session = self._repository.get_checkout_session(normalized_reference) or session
        return self._serialize_checkout_session(session)

    def complete_checkout_callback(
        self,
        *,
        token: str,
        reference_id: str = "",
        mode: str = "",
    ) -> dict[str, Any]:
        normalized_token = str(token or "").strip()
        if not normalized_token:
            raise RuntimeError("iyzico_checkout_token_required")
        session = None
        if reference_id:
            session = self._repository.get_checkout_session(reference_id)
        if session is None:
            session = self._repository.get_checkout_session_by_provider_token(normalized_token)
        resolved_mode = str(mode or (session or {}).get("mode") or "subscription").strip() or "subscription"
        resolved_reference_id = str(reference_id or (session or {}).get("reference_id") or "").strip()
        if resolved_mode == "token_pack":
            completion = self._provider.retrieve_token_pack_checkout(token=normalized_token, reference_id=resolved_reference_id)
        else:
            completion = self._provider.retrieve_subscription_checkout(token=normalized_token, reference_id=resolved_reference_id)
        return self._apply_provider_completion(completion, source="callback")

    def get_checkout_launch_payload(self, reference_id: str) -> dict[str, Any] | None:
        session = self._repository.get_checkout_session(reference_id)
        if session is None:
            return None
        raw_payload = dict(session.get("raw_last_payload") or {})
        return {
            "reference_id": str(session.get("reference_id") or ""),
            "mode": str(session.get("mode") or "subscription"),
            "payment_page_url": str(session.get("payment_page_url") or ""),
            "checkout_form_content": str(
                raw_payload.get("checkoutFormContent")
                or raw_payload.get("checkout_form_content")
                or (((raw_payload.get("metadata") if isinstance(raw_payload.get("metadata"), dict) else {}) or {}).get("checkout_form_content"))
                or ""
            ),
            "raw": raw_payload,
        }

    def get_credit_balance(self, workspace_id: str) -> dict[str, Any]:
        record = self._workspace(workspace_id)
        balance = self._ensure_included_credits(record)
        period_info = _billing_period_info(self._effective_plan_id(record))
        entitlements = _plan_entitlements(self._effective_plan_id(record))
        return self._enrich_credit_balance(record.workspace_id, balance, period_info=period_info, entitlements=entitlements)

    def get_credit_ledger(self, workspace_id: str, *, limit: int = 100) -> dict[str, Any]:
        self.get_credit_balance(workspace_id)
        return {
            "workspace_id": str(workspace_id or "local-workspace").strip() or "local-workspace",
            "items": self._repository.list_credit_ledger(workspace_id, limit=limit),
        }

    def get_billing_events(self, workspace_id: str, *, limit: int = 100) -> dict[str, Any]:
        return {
            "workspace_id": str(workspace_id or "local-workspace").strip() or "local-workspace",
            "items": self._repository.list_billing_events(workspace_id, limit=limit),
        }

    def get_entitlements(self, workspace_id: str) -> dict[str, Any]:
        record = self._workspace(workspace_id)
        balance = self._ensure_included_credits(record)
        effective_plan_id = self._effective_plan_id(record)
        entitlements = _plan_entitlements(effective_plan_id)
        degraded_reason = self._degraded_reason(record)
        period_info = _billing_period_info(effective_plan_id)
        usage_summary = self._collect_usage_summary(record.workspace_id, limit=25)
        return {
            "workspace_id": record.workspace_id,
            "plan_id": effective_plan_id,
            "requested_plan_id": record.plan_id,
            "status": self._normalize_status(record.status),
            "provider": str(record.metadata.get("provider") or self._provider.provider_name),
            "entitlements": entitlements,
            "credits": self._enrich_credit_balance(record.workspace_id, balance, period_info=period_info, entitlements=entitlements),
            "workspace_owned": True,
            "hybrid_billing": True,
            "degraded": bool(degraded_reason),
            "degraded_reason": degraded_reason,
            "reset_at": float(period_info.get("reset_at") or 0.0),
            "usage_summary": usage_summary,
            "feature_access": entitlements.get("tool_access") or {},
        }

    def get_usage(self, workspace_id: str, *, limit: int = 100) -> dict[str, Any]:
        record = self._workspace(workspace_id)
        summary = self._collect_usage_summary(record.workspace_id, limit=limit)
        recent = sorted(record.usage, key=lambda item: item.created_at, reverse=True)[: max(1, int(limit or 100))]
        totals: dict[str, int] = {}
        for item in record.usage:
            totals[item.metric] = int(totals.get(item.metric, 0)) + int(item.amount or 0)
        return {
            "workspace_id": record.workspace_id,
            "items": [item.to_dict() for item in recent],
            "totals": totals,
            "budget": _plan_entitlements(self._effective_plan_id(record)).get("monthly_usage_budget", 0),
            "summary": summary,
            "reset_at": float(summary.get("period", {}).get("reset_at") or 0.0),
        }

    def get_usage_entry(self, workspace_id: str, usage_id: str) -> dict[str, Any] | None:
        record = self._workspace(workspace_id)
        normalized = str(usage_id or "").strip()
        if not normalized:
            return None
        for item in record.usage:
            if str(item.usage_id or "").strip() == normalized:
                return item.to_dict()
        payload = self._repository.get_usage(normalized)
        if payload is None or str(payload.get("workspace_id") or "") != str(record.workspace_id):
            return None
        return payload

    def _sync_usage_metadata(self, workspace_id: str, usage_id: str, metadata: dict[str, Any]) -> dict[str, Any] | None:
        record = self._workspace(workspace_id)
        normalized = str(usage_id or "").strip()
        if not normalized:
            return None
        updated_payload = None
        for item in record.usage:
            if str(item.usage_id or "").strip() == normalized:
                item.metadata = dict(metadata or {})
                updated_payload = item.to_dict()
                break
        if updated_payload is None:
            payload = self._repository.get_usage(normalized)
            if payload is None:
                return None
            entry = UsageLedgerEntry.from_dict({**payload, "metadata": dict(metadata or {})})
            record.usage.append(entry)
            updated_payload = entry.to_dict()
        record.updated_at = _now()
        self._repository.update_usage_metadata(normalized, dict(metadata or {}))
        self._repository.upsert_workspace(record.to_dict())
        return updated_payload

    def _resolve_usage_event_identity(self, context: dict[str, Any]) -> tuple[str, str]:
        usage_id = str(context.get("usage_id") or context.get("reference_id") or "").strip()
        if not usage_id:
            usage_id = _stable_id(
                "usage",
                str(context.get("workspace_id") or "local-workspace"),
                str(context.get("actor_id") or ""),
                str(context.get("metric") or "unknown"),
                str(context.get("session_id") or ""),
                str(context.get("run_id") or ""),
                str(_now()),
            )
        reference_id = str(context.get("reference_id") or usage_id).strip() or usage_id
        return usage_id, reference_id

    def estimate_usage_credits(self, metric: str, amount: int = 1, *, metadata: dict[str, Any] | None = None) -> int:
        details = dict(metadata or {})
        metric_key = str(metric or "unknown").strip().lower()
        count = max(1, int(amount or 1))
        mode = str(details.get("mode") or details.get("task_type") or "cowork").strip().lower() or "cowork"
        prompt_length = max(
            0,
            int(details.get("prompt_length") or details.get("chars") or details.get("content_length") or 0),
        )
        routing_profile = str(details.get("routing_profile") or "balanced").strip().lower() or "balanced"
        review_strictness = str(details.get("review_strictness") or "balanced").strip().lower() or "balanced"
        input_tokens = max(0, int(details.get("input_tokens") or details.get("prompt_tokens") or 0))
        output_tokens = max(0, int(details.get("output_tokens") or details.get("completion_tokens") or 0))
        reasoning_tokens = max(0, int(details.get("reasoning_tokens") or details.get("thinking_tokens") or 0))
        tool_calls = max(0, int(details.get("tool_calls") or details.get("tools_used") or 0))
        memory_ops = max(0, int(details.get("memory_ops") or details.get("memory_writes") or 0))
        deep_mode = bool(details.get("deep_mode") or details.get("reasoning_mode") or details.get("multi_agent_recommended"))
        priority = str(details.get("priority") or details.get("priority_level") or "").strip().lower()
        model_tier = str(details.get("model_tier") or details.get("model_class") or "").strip().lower()
        prompt_surcharge = min(4, prompt_length // 900) if prompt_length > 0 else 0
        quality_surcharge = 1 if routing_profile == "quality_first" or review_strictness == "strict" else 0
        weighted_tokens = input_tokens + output_tokens + (reasoning_tokens * 2)
        token_estimate = int(math.ceil(weighted_tokens / 1200.0)) if weighted_tokens > 0 else 0
        feature_surcharge = tool_calls + memory_ops
        factor = 1.0
        if deep_mode:
            factor += 0.35
        if priority in {"high", "urgent", "critical"}:
            factor += 0.15
        if model_tier in {"premium", "pro", "frontier"}:
            factor += 0.2
        if routing_profile == "quality_first":
            factor += 0.15
        if review_strictness == "strict":
            factor += 0.1
        factor = min(factor, 2.5)

        if metric_key == "inbox_events":
            return 0
        if metric_key == "task_extractions":
            return max(1, count)
        if metric_key == "cowork_threads":
            base = {
                "cowork": 3,
                "document": 4,
                "presentation": 5,
                "website": 6,
            }.get(mode, 3)
            raw = max(base + prompt_surcharge + quality_surcharge, token_estimate + feature_surcharge)
            return max(1, int(math.ceil(raw * factor))) * count
        if metric_key == "cowork_turns":
            base = {
                "cowork": 2,
                "document": 3,
                "presentation": 4,
                "website": 5,
            }.get(mode, 2)
            raw = max(base + prompt_surcharge + quality_surcharge, token_estimate + feature_surcharge)
            return max(1, int(math.ceil(raw * factor))) * count
        if metric_key == "workflow_runs":
            base = {
                "document": 8,
                "presentation": 10,
                "website": 12,
            }.get(mode, 8)
            raw = max(base + prompt_surcharge + quality_surcharge, token_estimate + feature_surcharge + 2)
            return max(1, int(math.ceil(raw * factor))) * count
        return max(0, int(math.ceil((token_estimate + feature_surcharge) * factor)))

    def authorize_usage(self, workspace_id: str, metric: str, amount: int = 1, *, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        context = self._usage_context(workspace_id, metric, amount, metadata)
        effective_plan_id = self._effective_plan_id(self._workspace(context["workspace_id"]))
        entitlements = _plan_entitlements(effective_plan_id)
        estimated_override = context.get("estimated_override")
        if estimated_override is not None:
            estimated_override = max(0, int(estimated_override or 0))
        estimated_credits = max(
            0,
            int(
                estimated_override
                if estimated_override is not None
                else self._estimate_credit_cost(context)
            ),
        )
        balance = self.get_credit_balance(context["workspace_id"])
        rate_snapshot = self._rate_limit_snapshot(context, entitlements)
        credit_balance = int(balance.get("total") or 0)
        request_limit = int(rate_snapshot.get("request_limit") or 0)
        credit_limit = int(rate_snapshot.get("credit_limit") or 0)
        hard_period_limit = int(rate_snapshot.get("period_limit") or 0)
        soft_period_limit = int(rate_snapshot.get("soft_period_limit") or 0)
        request_count = int(rate_snapshot.get("request_count") or 0)
        hour_spend = int(rate_snapshot.get("hour_spend") or 0)
        period_spend = int(rate_snapshot.get("period_spend") or 0)
        remaining_balance = max(0, credit_balance - estimated_credits)
        allowed = True
        reason = "within_limits"
        status_code = 200
        retry_after = 0
        degraded = False
        if request_limit > 0 and request_count >= request_limit:
            allowed = False
            reason = "requests_per_minute_limit_reached"
            status_code = 429
            retry_after = 60
        elif credit_limit > 0 and hour_spend + estimated_credits > credit_limit:
            allowed = False
            reason = "credit_spend_cap_per_hour_reached"
            status_code = 429
            retry_after = 3600
        elif hard_period_limit > 0 and period_spend + estimated_credits > hard_period_limit:
            allowed = False
            reason = "weekly_hard_cap_reached" if str(rate_snapshot.get("period") or "").startswith("weekly:") else "monthly_hard_cap_reached"
            status_code = 402
            retry_after = max(0, int(float(context.get("reset_at") or 0.0) - _now()))
        elif credit_balance < estimated_credits:
            allowed = False
            reason = "insufficient_credits"
            status_code = 402
        elif soft_period_limit > 0 and period_spend + estimated_credits >= max(1, int(soft_period_limit * 0.8)):
            degraded = True
        elif credit_balance <= max(50, int(entitlements.get("weekly_credit_limit") or entitlements.get("monthly_soft_limit") or 0) // 10):
            degraded = True

        if allowed and not degraded and soft_period_limit > 0 and period_spend + estimated_credits >= soft_period_limit:
            degraded = True

        upgrade_hint = self._limit_hint_for_plan(
            effective_plan_id,
            metric=str(metric or "unknown"),
            remaining=remaining_balance,
            reset_at=float(context.get("reset_at") or 0.0),
        ) if (degraded or not allowed) else None
        if not allowed:
            decision = {
                "allowed": False,
                "reason": reason,
                "status_code": status_code,
                "retry_after": retry_after,
                "required_credits": estimated_credits,
                "available_credits": credit_balance,
                "source_order": ["included", "purchased"],
            }
        else:
            decision = {
                "allowed": True,
                "reason": reason,
                "status_code": status_code,
                "retry_after": retry_after,
                "required_credits": estimated_credits,
                "available_credits": credit_balance,
                "source_order": ["included", "purchased"],
                "degraded": degraded,
            }
        return {
            **decision,
            "workspace_id": context["workspace_id"],
            "actor_id": context["actor_id"],
            "session_id": context["session_id"],
            "run_id": context["run_id"],
            "mission_id": context["mission_id"],
            "metric": context["metric"],
            "amount": context["amount"],
            "estimated_credits": estimated_credits,
            "credit_balance": balance,
            "rate_limits": rate_snapshot,
            "upgrade_hint": upgrade_hint,
            "reset_at": float(context.get("reset_at") or 0.0),
            "feature_access": entitlements.get("tool_access") or {},
        }

    def authorize_credits(self, workspace_id: str, *, required_credits: int) -> dict[str, Any]:
        balance = self.get_credit_balance(workspace_id)
        required = max(0, int(required_credits or 0))
        included = int(balance.get("included") or 0)
        purchased = int(balance.get("purchased") or 0)
        total = int(balance.get("total") or 0)
        if total >= required:
            return {
                "allowed": True,
                "required_credits": required,
                "available_credits": total,
                "source_order": ["included", "purchased"],
            }
        return {
            "allowed": False,
            "required_credits": required,
            "available_credits": total,
            "source_order": ["included", "purchased"],
            "reason": "insufficient_credits",
        }

    def debit_credits(
        self,
        workspace_id: str,
        *,
        required_credits: int,
        reference_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        workspace_key = _workspace_key(workspace_id)
        decision = self.authorize_credits(workspace_key, required_credits=required_credits)
        if not decision.get("allowed", False):
            raise RuntimeError("insufficient_credits")
        remaining = max(0, int(required_credits or 0))
        balance = self.get_credit_balance(workspace_key)
        debits: list[dict[str, Any]] = []
        for bucket in ("included", "purchased"):
            bucket_balance = int(balance.get(bucket) or 0)
            if remaining <= 0 or bucket_balance <= 0:
                continue
            delta = min(bucket_balance, remaining)
            entry = self._repository.record_credit_entry(
                {
                    "entry_id": _stable_id("usage", workspace_key, bucket, reference_id or str(_now()), str(delta)),
                    "workspace_id": workspace_key,
                    "bucket": bucket,
                    "entry_type": "usage",
                    "delta_credits": -delta,
                    "reference_id": reference_id,
                    "metadata": dict(metadata or {}),
                }
            )
            debits.append(entry)
            remaining -= delta
        self._repository.record_billing_event(
            {
                "event_id": _stable_id("billevt", workspace_key, "usage", reference_id or str(_now()), str(required_credits)),
                "workspace_id": workspace_key,
                "provider": "internal",
                "event_type": "billing.credit.debited",
                "status": "applied",
                "reference_id": reference_id,
                "payload": {
                    "workspace_id": workspace_key,
                    "required_credits": int(required_credits or 0),
                    "entries": debits,
                    "metadata": dict(metadata or {}),
                },
            }
        )
        return {
            "workspace_id": workspace_key,
            "required_credits": int(required_credits or 0),
            "entries": debits,
            "balance": self._repository.get_credit_balance(workspace_key),
        }

    def record_usage(self, workspace_id: str, metric: str, amount: int = 1, *, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        record = self._workspace(workspace_id)
        usage_metadata = dict(metadata or {})
        context = self._usage_context(record.workspace_id, metric, amount, usage_metadata)
        for key in ("trace_id", "request_id", "trace_source"):
            value = str(context.get(key) or "").strip()
            if value and not str(usage_metadata.get(key) or "").strip():
                usage_metadata[key] = value
        if context.get("session_id") and not str(usage_metadata.get("session_id") or "").strip():
            usage_metadata["session_id"] = str(context.get("session_id") or "").strip()
        if context.get("workspace_id") and not str(usage_metadata.get("workspace_id") or "").strip():
            usage_metadata["workspace_id"] = str(context.get("workspace_id") or "").strip()
        if "estimated_credits" not in usage_metadata and "credits" not in usage_metadata:
            estimated_credits = self._estimate_credit_cost(context)
            if estimated_credits > 0:
                usage_metadata["estimated_credits"] = estimated_credits
        else:
            estimated_credits = max(0, int(usage_metadata.get("estimated_credits") or usage_metadata.get("credits") or 0))
        usage_id, reference_id = self._resolve_usage_event_identity({**context, "metadata": usage_metadata})
        if estimated_credits > 0:
            self.debit_credits(
                record.workspace_id,
                required_credits=estimated_credits,
                reference_id=reference_id,
                metadata={"metric": str(metric or "unknown").strip() or "unknown", **usage_metadata},
            )
        entry = UsageLedgerEntry(
            usage_id=usage_id,
            workspace_id=record.workspace_id,
            metric=str(metric or "unknown").strip() or "unknown",
            amount=max(0, int(amount or 0)),
            metadata=usage_metadata,
        )
        record.usage.append(entry)
        record.updated_at = _now()
        self._repository.record_usage(entry.to_dict())
        self._repository.upsert_workspace(record.to_dict())
        rate_snapshot = self._rate_limit_snapshot({**context, "usage_id": usage_id, "reference_id": reference_id}, _plan_entitlements(self._effective_plan_id(record)))
        now = _now()
        request_key = str(rate_snapshot.get("request_key") or "")
        credit_key = str(rate_snapshot.get("credit_key") or "")
        period_key = str(rate_snapshot.get("period_key") or "")
        request_bucket = self._rate_limit_bucket_state(record.workspace_id, bucket_type="request_minute", bucket_key=request_key)
        credit_bucket = self._rate_limit_bucket_state(record.workspace_id, bucket_type="credit_hour", bucket_key=credit_key)
        period_bucket = self._rate_limit_bucket_state(record.workspace_id, bucket_type="period_spend", bucket_key=period_key)
        request_count = int(request_bucket.get("request_count") or 0) + 1
        credit_spend = int(credit_bucket.get("credit_spend") or 0) + max(0, estimated_credits)
        period_spend = int(period_bucket.get("credit_spend") or 0) + max(0, estimated_credits)
        minute_status = self._bucket_status(request_count, int(rate_snapshot.get("request_limit") or 0))
        hour_status = self._bucket_status(credit_spend, int(rate_snapshot.get("credit_limit") or 0))
        period_status = self._bucket_status(period_spend, int(rate_snapshot.get("period_limit") or 0))
        self._record_rate_limit_bucket(
            record.workspace_id,
            actor_id=str(context.get("actor_id") or record.workspace_id),
            metric=str(metric or "unknown"),
            bucket_type="request_minute",
            bucket_key=request_key,
            request_count=request_count,
            credit_spend=max(0, estimated_credits),
            hard_cap=int(rate_snapshot.get("request_limit") or 0),
            soft_cap=max(0, int(rate_snapshot.get("request_limit") or 0)),
            status=minute_status,
            reason="request_recorded",
            metadata={"usage_id": usage_id, "session_id": context.get("session_id"), "run_id": context.get("run_id")},
            allowed_at=now,
            created_at=now,
        )
        self._record_rate_limit_bucket(
            record.workspace_id,
            actor_id=str(context.get("actor_id") or record.workspace_id),
            metric=str(metric or "unknown"),
            bucket_type="credit_hour",
            bucket_key=credit_key,
            request_count=request_count,
            credit_spend=credit_spend,
            hard_cap=int(rate_snapshot.get("credit_limit") or 0),
            soft_cap=max(0, int(rate_snapshot.get("credit_limit") or 0) - max(1, int(rate_snapshot.get("credit_limit") or 0) // 5)),
            status=hour_status,
            reason="credit_spend_recorded",
            metadata={"usage_id": usage_id, "session_id": context.get("session_id"), "run_id": context.get("run_id")},
            allowed_at=now,
            created_at=now,
        )
        self._record_rate_limit_bucket(
            record.workspace_id,
            actor_id=str(context.get("actor_id") or record.workspace_id),
            metric=str(metric or "unknown"),
            bucket_type="period_spend",
            bucket_key=period_key,
            request_count=request_count,
            credit_spend=period_spend,
            hard_cap=int(rate_snapshot.get("period_limit") or 0),
            soft_cap=max(0, int(rate_snapshot.get("period_limit") or 0) - max(1, int(rate_snapshot.get("period_limit") or 0) // 10)),
            status=period_status,
            reason="period_spend_recorded",
            metadata={"usage_id": usage_id, "session_id": context.get("session_id"), "run_id": context.get("run_id")},
            allowed_at=now,
            created_at=now,
        )
        self.record_usage_event(
            {
                **context,
                "usage_id": usage_id,
                "reference_id": reference_id,
                "status": "recorded",
                "event_type": "usage",
                "estimated_credits": estimated_credits,
                "actual_credits": estimated_credits,
                "metadata": {**usage_metadata, "source": "record_usage"},
            }
        )
        return entry.to_dict()

    def record_credit_grant(
        self,
        workspace_id: str,
        credits: int,
        *,
        bucket: str = "purchased",
        reference_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        workspace_key = _workspace_key(workspace_id)
        grant_credits = max(0, int(credits or 0))
        if grant_credits <= 0:
            return {
                "workspace_id": workspace_key,
                "bucket": str(bucket or "purchased").strip().lower() or "purchased",
                "credits": 0,
                "reference_id": str(reference_id or "").strip(),
                "balance": self._repository.get_credit_balance(workspace_key),
            }
        normalized_bucket = "included" if str(bucket or "").strip().lower() == "included" else "purchased"
        grant_metadata = dict(metadata or {})
        record = self._workspace(workspace_key)
        if normalized_bucket == "included":
            period = str(grant_metadata.get("period") or _period_key()).strip() or _period_key()
            plan_id = str(
                grant_metadata.get("plan_id")
                or grant_metadata.get("effective_plan_id")
                or record.metadata.get("effective_plan_id")
                or record.plan_id
                or "free"
            ).strip().lower() or "free"
            entry_scope = f"{plan_id}:{period}"
            grant_metadata.setdefault("period", period)
            grant_metadata.setdefault("plan_id", plan_id)
            grant_metadata.setdefault("grant_type", "plan_included")
            grant_metadata.setdefault("source_reference_id", str(reference_id or "").strip())
        else:
            entry_scope = str(reference_id or grant_metadata.get("pack_id") or grant_metadata.get("token_pack_id") or grant_credits).strip()
            grant_metadata.setdefault("grant_type", "token_pack")
        reference_value = entry_scope if normalized_bucket == "included" else str(reference_id or "").strip()
        entry = self._repository.record_credit_entry(
            {
                "entry_id": _stable_id("creditgrant", workspace_key, normalized_bucket, entry_scope),
                "workspace_id": workspace_key,
                "bucket": normalized_bucket,
                "entry_type": "grant",
                "delta_credits": grant_credits,
                "reference_id": reference_value,
                "metadata": grant_metadata,
            }
        )
        event = self._repository.record_billing_event(
            {
                "event_id": _stable_id("billevt", workspace_key, "credit.granted", normalized_bucket, entry_scope),
                "workspace_id": workspace_key,
                "provider": str(grant_metadata.get("source") or "internal"),
                "event_type": "credit.granted",
                "status": "applied",
                "reference_id": reference_value,
                "payload": {
                    "workspace_id": workspace_key,
                    "bucket": normalized_bucket,
                    "credits": grant_credits,
                    "reference_id": reference_value,
                    "source_reference_id": str(reference_id or "").strip(),
                    "metadata": grant_metadata,
                },
            }
        )
        if normalized_bucket == "included":
            record.metadata["included_credit_period"] = str(grant_metadata.get("period") or _period_key())
        if grant_metadata.get("plan_id"):
            record.metadata["effective_plan_id"] = str(grant_metadata.get("plan_id") or "").strip().lower()
        record.updated_at = _now()
        self._save()
        snapshot = self._snapshot_entitlements(workspace_key, scope="credit_grant")
        balance = self._repository.get_credit_balance(workspace_key)
        return {
            "workspace_id": workspace_key,
            "bucket": normalized_bucket,
            "credits": grant_credits,
            "reference_id": reference_value,
            "entry": entry,
            "event": event,
            "balance": balance,
        }

    def reconcile_usage(
        self,
        workspace_id: str,
        *,
        usage_id: str,
        actual_credits: int,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        workspace_key = _workspace_key(workspace_id)
        usage = self.get_usage_entry(workspace_key, usage_id)
        if usage is None:
            raise KeyError("usage not found")
        usage_metadata = dict(usage.get("metadata") or {})
        existing_reconciliation = usage_metadata.get("reconciliation") if isinstance(usage_metadata.get("reconciliation"), dict) else {}
        if str(existing_reconciliation.get("status") or "").strip().lower() in {"applied", "no_change", "insufficient_credits"}:
            return {
                "workspace_id": workspace_key,
                "usage_id": str(usage.get("usage_id") or usage_id),
                "metric": str(usage.get("metric") or "unknown"),
                "estimated_credits": int(usage_metadata.get("estimated_credits") or usage_metadata.get("credits") or 0),
                "actual_credits": int(existing_reconciliation.get("actual_credits") or 0),
                "delta_credits": int(existing_reconciliation.get("delta_credits") or 0),
                "status": str(existing_reconciliation.get("status") or "applied"),
                "reconciled": True,
                "idempotent": True,
                "credit_balance": self._repository.get_credit_balance(workspace_key),
            }

        estimated_credits = max(0, int(usage_metadata.get("estimated_credits") or usage_metadata.get("credits") or 0))
        actual = max(0, int(actual_credits or 0))
        delta = int(actual - estimated_credits)
        reconciliation_reference = f"{str(usage.get('usage_id') or usage_id).strip()}:reconcile"
        applied_entries: list[dict[str, Any]] = []
        status = "no_change"
        if delta > 0:
            decision = self.authorize_credits(workspace_key, required_credits=delta)
            if not decision.get("allowed", False):
                status = "insufficient_credits"
                reconciliation_payload = {
                    "status": status,
                    "reconciled_at": _now(),
                    "estimated_credits": estimated_credits,
                    "actual_credits": actual,
                    "delta_credits": delta,
                    "reference_id": reconciliation_reference,
                    "metadata": dict(metadata or {}),
                }
                usage_metadata["reconciliation"] = reconciliation_payload
                self._sync_usage_metadata(workspace_key, str(usage.get("usage_id") or usage_id), usage_metadata)
                self.record_usage_event(
                    {
                        "workspace_id": workspace_key,
                        "actor_id": str(usage_metadata.get("actor_id") or (metadata or {}).get("actor_id") or ""),
                        "session_id": str(usage_metadata.get("session_id") or (metadata or {}).get("session_id") or ""),
                        "run_id": str(usage_metadata.get("run_id") or (metadata or {}).get("run_id") or ""),
                        "usage_id": str(usage.get("usage_id") or usage_id),
                        "reference_id": reconciliation_reference,
                        "metric": str(usage.get("metric") or "unknown"),
                        "status": status,
                        "event_type": "reconciled",
                        "estimated_credits": estimated_credits,
                        "actual_credits": actual,
                        "metadata": dict(metadata or {}),
                    }
                )
                self._repository.record_billing_event(
                    {
                        "event_id": _stable_id("billevt", workspace_key, "usage_reconcile", str(usage.get("usage_id") or usage_id)),
                        "workspace_id": workspace_key,
                        "provider": "internal",
                        "event_type": "billing.usage.reconciled",
                        "status": status,
                        "reference_id": str(usage.get("usage_id") or usage_id),
                        "payload": {
                            "workspace_id": workspace_key,
                            "usage_id": str(usage.get("usage_id") or usage_id),
                            "metric": str(usage.get("metric") or "unknown"),
                            "estimated_credits": estimated_credits,
                            "actual_credits": actual,
                            "delta_credits": delta,
                            "decision": decision,
                            "metadata": dict(metadata or {}),
                        },
                    }
                )
                return {
                    "workspace_id": workspace_key,
                    "usage_id": str(usage.get("usage_id") or usage_id),
                    "metric": str(usage.get("metric") or "unknown"),
                    "estimated_credits": estimated_credits,
                    "actual_credits": actual,
                    "delta_credits": delta,
                    "status": status,
                    "reconciled": False,
                    "credit_balance": self._repository.get_credit_balance(workspace_key),
                }
            debit_result = self.debit_credits(
                workspace_key,
                required_credits=delta,
                reference_id=reconciliation_reference,
                metadata={
                    "usage_id": str(usage.get("usage_id") or usage_id),
                    "metric": str(usage.get("metric") or "unknown"),
                    "reconciliation": True,
                    **dict(metadata or {}),
                },
            )
            applied_entries = list(debit_result.get("entries") or [])
            status = "applied"
        elif delta < 0:
            remaining_refund = abs(delta)
            original_entries = self._repository.list_credit_entries_for_reference(
                workspace_key,
                reference_id=str(usage.get("usage_id") or usage_id),
                entry_type="usage",
                limit=20,
            )
            for source_entry in original_entries:
                debited = abs(min(0, int(source_entry.get("delta_credits") or 0)))
                if debited <= 0 or remaining_refund <= 0:
                    continue
                refund_delta = min(debited, remaining_refund)
                applied_entries.append(
                    self._repository.record_credit_entry(
                        {
                            "entry_id": _stable_id(
                                "recon",
                                workspace_key,
                                str(usage.get("usage_id") or usage_id),
                                str(source_entry.get("bucket") or "included"),
                                str(refund_delta),
                            ),
                            "workspace_id": workspace_key,
                            "bucket": str(source_entry.get("bucket") or "included"),
                            "entry_type": "reconciliation_refund",
                            "delta_credits": refund_delta,
                            "reference_id": reconciliation_reference,
                            "metadata": {
                                "usage_id": str(usage.get("usage_id") or usage_id),
                                "metric": str(usage.get("metric") or "unknown"),
                                "source_entry_id": str(source_entry.get("entry_id") or ""),
                                **dict(metadata or {}),
                            },
                        }
                    )
                )
                remaining_refund -= refund_delta
            status = "applied"

        reconciliation_payload = {
            "status": status,
            "reconciled_at": _now(),
            "estimated_credits": estimated_credits,
            "actual_credits": actual,
            "delta_credits": delta,
            "reference_id": reconciliation_reference,
            "entries": applied_entries,
            "metadata": dict(metadata or {}),
        }
        usage_metadata["reconciliation"] = reconciliation_payload
        updated_usage = self._sync_usage_metadata(workspace_key, str(usage.get("usage_id") or usage_id), usage_metadata)
        self.record_usage_event(
            {
                "workspace_id": workspace_key,
                "actor_id": str(usage_metadata.get("actor_id") or (metadata or {}).get("actor_id") or ""),
                "session_id": str(usage_metadata.get("session_id") or (metadata or {}).get("session_id") or ""),
                "run_id": str(usage_metadata.get("run_id") or (metadata or {}).get("run_id") or ""),
                "usage_id": str(usage.get("usage_id") or usage_id),
                "reference_id": reconciliation_reference,
                "metric": str(usage.get("metric") or "unknown"),
                "status": status,
                "event_type": "reconciled",
                "estimated_credits": estimated_credits,
                "actual_credits": actual,
                "metadata": dict(metadata or {}),
            }
        )
        self._repository.record_billing_event(
            {
                "event_id": _stable_id("billevt", workspace_key, "usage_reconcile", str(usage.get("usage_id") or usage_id)),
                "workspace_id": workspace_key,
                "provider": "internal",
                "event_type": "billing.usage.reconciled",
                "status": status,
                "reference_id": str(usage.get("usage_id") or usage_id),
                "payload": {
                    "workspace_id": workspace_key,
                    "usage_id": str(usage.get("usage_id") or usage_id),
                    "metric": str(usage.get("metric") or "unknown"),
                    "estimated_credits": estimated_credits,
                    "actual_credits": actual,
                    "delta_credits": delta,
                    "entries": applied_entries,
                    "metadata": dict(metadata or {}),
                },
            }
        )
        self._snapshot_entitlements(workspace_key, scope="usage_reconciliation")
        return {
            "workspace_id": workspace_key,
            "usage_id": str(usage.get("usage_id") or usage_id),
            "metric": str(usage.get("metric") or "unknown"),
            "estimated_credits": estimated_credits,
            "actual_credits": actual,
            "delta_credits": delta,
            "status": status,
            "reconciled": True,
            "usage": updated_usage or usage,
            "entries": applied_entries,
            "credit_balance": self._repository.get_credit_balance(workspace_key),
        }

    def get_workspace_summary(self, workspace_id: str) -> dict[str, Any]:
        record = self._workspace(workspace_id)
        entitlements = self.get_entitlements(workspace_id)
        usage = self.get_usage(workspace_id, limit=20)
        current_plan = get_plan(entitlements["plan_id"])
        billing_profile = self.get_billing_profile(workspace_id)
        usage_summary = self.get_usage_summary(workspace_id, limit=50)
        notifications = self.list_notifications(workspace_id, limit=8)
        active_checkout = None
        pending_reference_id = str(record.metadata.get("pending_reference_id") or "").strip()
        if pending_reference_id:
            active_checkout = self.get_checkout_session(record.workspace_id, pending_reference_id, refresh=False)
        return {
            "workspace_id": record.workspace_id,
            "billing_customer": record.billing_customer,
            "provider": str(record.metadata.get("provider") or self._provider.provider_name),
            "plan": {
                "id": record.plan_id,
                "effective_id": entitlements["plan_id"],
                "label": current_plan.label,
                "status": entitlements["status"],
            },
            "subscription_state": {
                "status": entitlements["status"],
                "current_period_end": float(record.current_period_end or 0.0),
                "provider_customer_id": str(record.metadata.get("provider_customer_id") or record.stripe_customer_id or ""),
                "provider_subscription_id": str(record.metadata.get("provider_subscription_id") or record.stripe_subscription_id or ""),
            },
            "checkout_url": record.checkout_url,
            "portal_url": record.portal_url,
            "seats": max(int(record.seats or 1), int(current_plan.seat_limit)),
            "credit_balance": entitlements["credits"],
            "entitlements": entitlements["entitlements"],
            "feature_access": entitlements.get("feature_access") or entitlements["entitlements"].get("tool_access") or {},
            "usage": usage,
            "usage_summary": usage_summary,
            "reset_at": float(usage_summary.get("period", {}).get("reset_at") or 0.0),
            "top_cost_sources": list(usage_summary.get("top_cost_sources") or []),
            "triggered_limits": list(usage_summary.get("triggered_limits") or []),
            "upgrade_hint": usage_summary.get("upgrade_hint"),
            "notifications": notifications,
            "unread_notifications": int(sum(1 for item in notifications if str(item.get("status") or "").strip() != "seen")),
            "recent_usage_summary": {
                "requests": int((usage_summary.get("totals") or {}).get("requests") or 0),
                "estimated_credits": int((usage_summary.get("totals") or {}).get("estimated_credits") or 0),
            },
            "plans": self.list_plans(),
            "token_packs": self.list_token_packs(),
            "billing_profile": billing_profile,
            "active_checkout": active_checkout,
            "metadata": dict(record.metadata or {}),
        }

    def enforce_limit(self, workspace_id: str, *, metric: str, current_value: int) -> dict[str, Any]:
        entitlements = self.get_entitlements(workspace_id)
        limit = int((entitlements.get("entitlements") or {}).get(metric, -1))
        if limit >= 0 and int(current_value) >= limit:
            return {
                "allowed": False,
                "reason": f"{metric}_limit_reached",
                "metric": metric,
                "current": int(current_value),
                "limit": limit,
                "plan_id": entitlements.get("plan_id"),
            }
        return {
            "allowed": True,
            "reason": "within_limits",
            "metric": metric,
            "current": int(current_value),
            "limit": limit,
            "plan_id": entitlements.get("plan_id"),
        }

    def _append_query(self, base_url: str, payload: dict[str, Any]) -> str:
        separator = "&" if "?" in base_url else "?"
        return f"{base_url}{separator}{urlencode({k: v for k, v in payload.items() if str(v or '').strip()})}"

    def create_checkout_session(
        self,
        *,
        workspace_id: str,
        plan_id: str,
        success_url: str,
        cancel_url: str,
        customer_email: str = "",
    ) -> dict[str, Any]:
        record = self._workspace(workspace_id)
        plan = get_plan(plan_id)
        if plan.plan_id == "free":
            raise RuntimeError("free_plan_no_checkout")
        reference_id = _stable_id("chk", record.workspace_id, plan.plan_id, str(_now()))
        billing_profile = self._require_checkout_billing_profile(record.workspace_id)
        callback_url = self._callback_url(record.workspace_id, mode="subscription", reference_id=reference_id)
        request = CheckoutRequest(
            workspace_id=record.workspace_id,
            external_reference=reference_id,
            customer_email=str(customer_email or ""),
            success_url=str(success_url or "").strip(),
            cancel_url=str(cancel_url or "").strip(),
            callback_url=callback_url,
            billing_profile=billing_profile,
            metadata={"plan_id": plan.plan_id},
        )
        session = self._provider.create_subscription_checkout(plan_id=plan.plan_id, request=request)
        stored_session = self._persist_checkout_session(
            reference_id=reference_id,
            workspace_id=record.workspace_id,
            mode="subscription",
            catalog_id=plan.plan_id,
            provider=session.provider,
            status=str(session.status or "pending"),
            payment_page_url=str(session.payment_page_url or session.launch_url or ""),
            callback_url=str(session.callback_url or callback_url or ""),
            provider_token=str(session.provider_token or ""),
            provider_payment_id=str(session.provider_payment_id or ""),
            subscription_reference_code=str(session.subscription_reference_code or ""),
            raw_last_payload=dict((session.metadata or {}).get("raw") or session.to_dict()),
        )
        record.checkout_url = str(session.payment_page_url or session.launch_url or "")
        record.metadata["provider"] = self._provider.provider_name
        record.metadata["pending_plan_id"] = plan.plan_id
        record.metadata["pending_reference_id"] = reference_id
        record.updated_at = _now()
        self._save()
        self._repository.record_billing_event(
            {
                "event_id": _stable_id("billevt", record.workspace_id, "checkout", reference_id),
                "workspace_id": record.workspace_id,
                "provider": session.provider,
                "event_type": "billing.checkout.initiated",
                "status": self._public_checkout_status(session.status),
                "reference_id": reference_id,
                "payload": {
                    "workspace_id": record.workspace_id,
                    "mode": "subscription",
                    "plan_id": plan.plan_id,
                    "checkout": session.to_dict(),
                },
            }
        )
        self._snapshot_entitlements(record.workspace_id, scope="checkout_pending")
        return {
            "workspace_id": record.workspace_id,
            "plan_id": plan.plan_id,
            "provider": session.provider,
            "reference_id": reference_id,
            "status": self._public_checkout_status(session.status),
            "url": session.launch_url,
            "launch_url": session.launch_url,
            "checkout": self._serialize_checkout_session(stored_session),
        }

    def purchase_token_pack(
        self,
        *,
        workspace_id: str,
        pack_id: str,
        success_url: str,
        cancel_url: str,
        customer_email: str = "",
    ) -> dict[str, Any]:
        record = self._workspace(workspace_id)
        pack = get_token_pack(pack_id)
        reference_id = _stable_id("pack", record.workspace_id, pack.pack_id, str(_now()))
        billing_profile = self._require_checkout_billing_profile(record.workspace_id)
        callback_url = self._callback_url(record.workspace_id, mode="token_pack", reference_id=reference_id)
        request = CheckoutRequest(
            workspace_id=record.workspace_id,
            external_reference=reference_id,
            customer_email=str(customer_email or ""),
            success_url=str(success_url or "").strip(),
            cancel_url=str(cancel_url or "").strip(),
            callback_url=callback_url,
            billing_profile=billing_profile,
            metadata={"token_pack_id": pack.pack_id},
        )
        session = self._provider.create_token_pack_checkout(pack_id=pack.pack_id, request=request)
        stored_session = self._persist_checkout_session(
            reference_id=reference_id,
            workspace_id=record.workspace_id,
            mode="token_pack",
            catalog_id=pack.pack_id,
            provider=session.provider,
            status=str(session.status or "pending"),
            payment_page_url=str(session.payment_page_url or session.launch_url or ""),
            callback_url=str(session.callback_url or callback_url or ""),
            provider_token=str(session.provider_token or ""),
            provider_payment_id=str(session.provider_payment_id or ""),
            subscription_reference_code=str(session.subscription_reference_code or ""),
            raw_last_payload=dict((session.metadata or {}).get("raw") or session.to_dict()),
        )
        record.checkout_url = str(session.payment_page_url or session.launch_url or "")
        record.metadata["provider"] = self._provider.provider_name
        record.metadata["pending_token_pack_id"] = pack.pack_id
        record.metadata["pending_reference_id"] = reference_id
        record.updated_at = _now()
        self._save()
        self._repository.record_billing_event(
            {
                "event_id": _stable_id("billevt", record.workspace_id, "token_pack", reference_id),
                "workspace_id": record.workspace_id,
                "provider": session.provider,
                "event_type": "billing.token_pack.checkout.initiated",
                "status": self._public_checkout_status(session.status),
                "reference_id": reference_id,
                "payload": {
                    "workspace_id": record.workspace_id,
                    "mode": "token_pack",
                    "token_pack_id": pack.pack_id,
                    "checkout": session.to_dict(),
                },
            }
        )
        return {
            "workspace_id": record.workspace_id,
            "token_pack_id": pack.pack_id,
            "provider": session.provider,
            "reference_id": reference_id,
            "status": self._public_checkout_status(session.status),
            "url": session.launch_url,
            "launch_url": session.launch_url,
            "checkout": self._serialize_checkout_session(stored_session),
        }

    def create_portal_session(self, *, workspace_id: str, return_url: str) -> dict[str, Any]:
        record = self._workspace(workspace_id)
        portal_base = str(os.getenv("IYZICO_PORTAL_URL", "") or "").strip()
        if portal_base:
            portal_url = self._append_query(
                portal_base,
                {
                    "workspace_id": record.workspace_id,
                    "return_url": str(return_url or "").strip(),
                },
            )
        else:
            portal_url = str(return_url or "").strip() or "https://tauri.localhost/settings/billing"
        record.portal_url = portal_url
        record.updated_at = _now()
        self._save()
        return {
            "workspace_id": record.workspace_id,
            "provider": str(record.metadata.get("provider") or self._provider.provider_name),
            "url": portal_url,
        }

    def list_notifications(self, workspace_id: str, *, limit: int = 50, status: str = "") -> list[dict[str, Any]]:
        return self._repository.list_notifications(workspace_id, limit=limit, status=status)

    def mark_notification_seen(self, notification_id: str) -> dict[str, Any] | None:
        return self._repository.mark_notification_seen(notification_id)

    def post_notification(
        self,
        *,
        workspace_id: str,
        title: str,
        body: str,
        kind: str = "announcement",
        source: str = "control_plane",
        status: str = "unseen",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._repository.record_notification(
            {
                "workspace_id": workspace_id,
                "title": title,
                "body": body,
                "kind": kind,
                "source": source,
                "status": status,
                "metadata": dict(metadata or {}),
            }
        )

    def handle_webhook(
        self,
        payload: bytes,
        signature_or_headers: str | dict[str, str] | None = None,
        *,
        provider: str = "iyzico",
    ) -> dict[str, Any]:
        headers: dict[str, str]
        if isinstance(signature_or_headers, dict):
            headers = {str(key).lower(): str(value) for key, value in signature_or_headers.items()}
        else:
            headers = {}
            if signature_or_headers:
                headers["x-iyzico-signature"] = str(signature_or_headers)
        normalized_provider = str(provider or "iyzico").strip().lower() or "iyzico"
        if normalized_provider != "iyzico":
            raise RuntimeError(f"unsupported_billing_provider:{normalized_provider}")
        completion = self._provider.handle_webhook(payload=payload, headers=headers)
        return self._apply_provider_completion(completion, source="webhook")

    def verify_webhook_signature(self, payload: bytes, signature: str) -> dict[str, Any]:
        try:
            self._provider.handle_webhook(
                payload=payload,
                headers={
                    "x-iyz-signature-v3": str(signature or ""),
                    "x-iyzico-signature": str(signature or ""),
                },
            )
        except RuntimeError as exc:
            return {"verified": False, "error": str(exc)}
        return {"verified": True}


_workspace_billing_store: WorkspaceBillingStore | None = None


def get_workspace_billing_store(storage_path: Path | None = None) -> WorkspaceBillingStore:
    global _workspace_billing_store
    if _workspace_billing_store is None:
        _workspace_billing_store = WorkspaceBillingStore(storage_path=storage_path)
    return _workspace_billing_store


__all__ = [
    "UsageLedgerEntry",
    "WorkspaceBillingRecord",
    "WorkspaceBillingStore",
    "get_workspace_billing_store",
]
