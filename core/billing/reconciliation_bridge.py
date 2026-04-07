from __future__ import annotations

import math
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Iterator

from core.feature_flags import get_feature_flag_registry
from core.observability.logger import get_structured_logger
from core.observability.trace_context import get_trace_context


def _safe_list(values: set[str]) -> list[str]:
    return sorted(item for item in values if str(item or "").strip())


@dataclass
class BillingUsageScope:
    workspace_id: str
    usage_id: str
    metric: str
    run_id: str = ""
    mission_id: str = ""
    session_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    started_at: float = field(default_factory=time.time)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    usage_samples: int = 0
    providers: set[str] = field(default_factory=set)
    models: set[str] = field(default_factory=set)

    def record(
        self,
        *,
        provider: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        cost_usd: float,
    ) -> None:
        prompt = max(0, int(prompt_tokens or 0))
        completion = max(0, int(completion_tokens or 0))
        total = prompt + completion
        self.prompt_tokens += prompt
        self.completion_tokens += completion
        self.total_tokens += total
        self.cost_usd = round(float(self.cost_usd) + max(0.0, float(cost_usd or 0.0)), 8)
        self.usage_samples += 1
        provider_key = str(provider or "").strip().lower()
        model_name = str(model or "").strip()
        if provider_key:
            self.providers.add(provider_key)
        if model_name:
            self.models.add(model_name)

    def estimate_actual_credits(self) -> int:
        cost_based = int(math.ceil(max(0.0, float(self.cost_usd or 0.0)) * 1000.0))
        token_based = int(math.ceil(max(0, int(self.total_tokens or 0)) / 1500.0)) if self.total_tokens > 0 else 0
        return max(cost_based, token_based, 0)

    def summary(self) -> dict[str, Any]:
        return {
            "workspace_id": str(self.workspace_id or "").strip(),
            "usage_id": str(self.usage_id or "").strip(),
            "metric": str(self.metric or "").strip().lower(),
            "run_id": str(self.run_id or "").strip(),
            "mission_id": str(self.mission_id or "").strip(),
            "session_id": str(self.session_id or "").strip(),
            "started_at": float(self.started_at or 0.0),
            "duration_ms": int(max(0.0, time.time() - float(self.started_at or time.time())) * 1000),
            "prompt_tokens": int(self.prompt_tokens or 0),
            "completion_tokens": int(self.completion_tokens or 0),
            "total_tokens": int(self.total_tokens or 0),
            "cost_usd": round(float(self.cost_usd or 0.0), 8),
            "usage_samples": int(self.usage_samples or 0),
            "providers": _safe_list(self.providers),
            "models": _safe_list(self.models),
            "actual_credits_candidate": self.estimate_actual_credits(),
            "metadata": dict(self.metadata or {}),
        }


_ACTIVE_BILLING_USAGE_SCOPE: ContextVar[BillingUsageScope | None] = ContextVar(
    "elyan_billing_usage_scope",
    default=None,
)

_LOGGER = get_structured_logger("billing_reconciliation_bridge")


def _workspace_billing_store():
    from core.billing.workspace_billing import get_workspace_billing_store

    return get_workspace_billing_store()


def get_active_billing_usage_scope() -> BillingUsageScope | None:
    return _ACTIVE_BILLING_USAGE_SCOPE.get()


def _flag_enabled(name: str, *, actor_id: str = "", context: dict[str, Any] | None = None, default: bool = False) -> dict[str, Any]:
    return get_feature_flag_registry().resolve(
        name,
        user_id=actor_id,
        context=context,
        default=default,
    )


def _finalize_scope(scope: BillingUsageScope) -> None:
    actor_id = str((scope.metadata or {}).get("actor_id") or "").strip()
    context = {
        "workspace_id": str(scope.workspace_id or "").strip(),
        "metric": str(scope.metric or "").strip().lower(),
    }
    shadow_state = _flag_enabled(
        "billing_reconciliation_bridge_shadow",
        actor_id=actor_id,
        context=context,
        default=True,
    )
    apply_state = _flag_enabled(
        "billing_reconciliation_bridge_apply",
        actor_id=actor_id,
        context=context,
        default=False,
    )
    trace_context = get_trace_context()
    summary = scope.summary()
    summary["shadow_enabled"] = bool(shadow_state.get("enabled", False))
    summary["apply_enabled"] = bool(apply_state.get("enabled", False))
    summary["shadow_source"] = str(shadow_state.get("source") or "default")
    summary["apply_source"] = str(apply_state.get("source") or "default")

    if shadow_state.get("enabled", False):
        _LOGGER.log_event(
            "billing_reconciliation_bridge_scope",
            summary,
            level="info",
            session_id=summary["session_id"] or (trace_context.session_id if trace_context else None),
            run_id=summary["run_id"] or None,
            trace_id=trace_context.trace_id if trace_context else None,
            request_id=trace_context.request_id if trace_context else None,
            workspace_id=summary["workspace_id"] or (trace_context.workspace_id if trace_context else None),
        )

    if not apply_state.get("enabled", False):
        return
    if not summary["usage_id"]:
        return
    if summary["usage_samples"] <= 0 and summary["total_tokens"] <= 0 and float(summary["cost_usd"] or 0.0) <= 0.0:
        return

    reconciliation_metadata = {
        "source": "pricing_tracker_scope",
        "prompt_tokens": summary["prompt_tokens"],
        "completion_tokens": summary["completion_tokens"],
        "total_tokens": summary["total_tokens"],
        "cost_usd": summary["cost_usd"],
        "providers": list(summary["providers"]),
        "models": list(summary["models"]),
        "usage_samples": summary["usage_samples"],
        "run_id": summary["run_id"],
        "mission_id": summary["mission_id"],
    }
    try:
        result = _workspace_billing_store().reconcile_usage(
            summary["workspace_id"],
            usage_id=summary["usage_id"],
            actual_credits=summary["actual_credits_candidate"],
            metadata=reconciliation_metadata,
        )
        _LOGGER.log_event(
            "billing_reconciliation_bridge_applied",
            {
                **summary,
                "reconciliation_status": str(result.get("status") or ""),
                "delta_credits": int(result.get("delta_credits") or 0),
            },
            level="info",
            session_id=summary["session_id"] or (trace_context.session_id if trace_context else None),
            run_id=summary["run_id"] or None,
            trace_id=trace_context.trace_id if trace_context else None,
            request_id=trace_context.request_id if trace_context else None,
            workspace_id=summary["workspace_id"] or (trace_context.workspace_id if trace_context else None),
        )
    except Exception as exc:
        _LOGGER.log_event(
            "billing_reconciliation_bridge_error",
            {
                **summary,
                "error": str(exc),
            },
            level="warning",
            session_id=summary["session_id"] or (trace_context.session_id if trace_context else None),
            run_id=summary["run_id"] or None,
            trace_id=trace_context.trace_id if trace_context else None,
            request_id=trace_context.request_id if trace_context else None,
            workspace_id=summary["workspace_id"] or (trace_context.workspace_id if trace_context else None),
        )


@contextmanager
def activate_billing_usage_scope(
    *,
    workspace_id: str,
    usage_id: str,
    metric: str,
    run_id: str = "",
    mission_id: str = "",
    session_id: str = "",
    metadata: dict[str, Any] | None = None,
) -> Iterator[BillingUsageScope]:
    scope = BillingUsageScope(
        workspace_id=str(workspace_id or "").strip(),
        usage_id=str(usage_id or "").strip(),
        metric=str(metric or "").strip().lower(),
        run_id=str(run_id or "").strip(),
        mission_id=str(mission_id or "").strip(),
        session_id=str(session_id or "").strip(),
        metadata=dict(metadata or {}),
    )
    token = _ACTIVE_BILLING_USAGE_SCOPE.set(scope)
    try:
        yield scope
    finally:
        try:
            _finalize_scope(scope)
        finally:
            _ACTIVE_BILLING_USAGE_SCOPE.reset(token)


def record_pricing_usage(
    *,
    provider: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    cost_usd: float,
) -> bool:
    scope = get_active_billing_usage_scope()
    if scope is None:
        return False
    scope.record(
        provider=provider,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost_usd=cost_usd,
    )
    return True


__all__ = [
    "BillingUsageScope",
    "activate_billing_usage_scope",
    "get_active_billing_usage_scope",
    "record_pricing_usage",
]
