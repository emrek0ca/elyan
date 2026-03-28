from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from core.persistence import get_runtime_database
from core.storage_paths import resolve_elyan_data_dir


def _now() -> float:
    return time.time()


def _plan_entitlements(plan_id: str) -> dict[str, Any]:
    normalized = str(plan_id or "free").strip().lower()
    table = {
        "free": {
            "max_threads": 12,
            "max_connectors": 2,
            "artifact_exports": 12,
            "premium_models": False,
            "team_seats": 1,
            "monthly_usage_budget": 10000,
        },
        "pro": {
            "max_threads": 120,
            "max_connectors": 8,
            "artifact_exports": 240,
            "premium_models": True,
            "team_seats": 1,
            "monthly_usage_budget": 150000,
        },
        "team": {
            "max_threads": 600,
            "max_connectors": 24,
            "artifact_exports": 1600,
            "premium_models": True,
            "team_seats": 15,
            "monthly_usage_budget": 750000,
        },
        "enterprise": {
            "max_threads": 5000,
            "max_connectors": 200,
            "artifact_exports": 10000,
            "premium_models": True,
            "team_seats": 250,
            "monthly_usage_budget": 5000000,
        },
    }
    return dict(table.get(normalized, table["free"]))


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
        key = str(workspace_id or "local-workspace").strip() or "local-workspace"
        record = self._records.get(key)
        if record is None:
            record = WorkspaceBillingRecord(
                workspace_id=key,
                plan_id="free",
                status="active" if key == "local-workspace" else "inactive",
                billing_customer=f"ws_{hashlib.sha1(key.encode('utf-8')).hexdigest()[:12]}",
                metadata={"workspace_owned": True, "hybrid_billing": True},
            )
            self._records[key] = record
            self._save()
        return record

    def get_entitlements(self, workspace_id: str) -> dict[str, Any]:
        record = self._workspace(workspace_id)
        effective_plan_id = self._effective_plan_id(record)
        entitlements = _plan_entitlements(effective_plan_id)
        return {
            "workspace_id": record.workspace_id,
            "plan_id": effective_plan_id,
            "requested_plan_id": record.plan_id,
            "status": record.status,
            "entitlements": entitlements,
            "workspace_owned": True,
            "hybrid_billing": True,
            "degraded": effective_plan_id != record.plan_id,
            "degraded_reason": self._degraded_reason(record),
        }

    def get_usage(self, workspace_id: str, *, limit: int = 100) -> dict[str, Any]:
        record = self._workspace(workspace_id)
        recent = sorted(record.usage, key=lambda item: item.created_at, reverse=True)[: max(1, int(limit or 100))]
        totals: dict[str, int] = {}
        for item in record.usage:
            totals[item.metric] = int(totals.get(item.metric, 0)) + int(item.amount or 0)
        return {
            "workspace_id": record.workspace_id,
            "items": [item.to_dict() for item in recent],
            "totals": totals,
            "budget": _plan_entitlements(record.plan_id).get("monthly_usage_budget", 0),
        }

    def record_usage(self, workspace_id: str, metric: str, amount: int = 1, *, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        record = self._workspace(workspace_id)
        entry = UsageLedgerEntry(
            usage_id=f"usage_{int(_now() * 1000)}_{len(record.usage) + 1}",
            workspace_id=record.workspace_id,
            metric=str(metric or "unknown").strip() or "unknown",
            amount=max(0, int(amount or 0)),
            metadata=dict(metadata or {}),
        )
        record.usage.append(entry)
        record.updated_at = _now()
        self._repository.record_usage(entry.to_dict())
        self._repository.upsert_workspace(record.to_dict())
        return entry.to_dict()

    def get_workspace_summary(self, workspace_id: str) -> dict[str, Any]:
        record = self._workspace(workspace_id)
        usage = self.get_usage(workspace_id, limit=20)
        entitlements = self.get_entitlements(workspace_id)
        return {
            "workspace_id": record.workspace_id,
            "billing_customer": record.billing_customer,
            "plan": {
                "id": record.plan_id,
                "effective_id": self._effective_plan_id(record),
                "label": record.plan_id.replace("_", " ").title(),
                "status": record.status,
            },
            "subscription_state": {
                "status": record.status,
                "stripe_customer_id": record.stripe_customer_id,
                "stripe_subscription_id": record.stripe_subscription_id,
                "current_period_end": record.current_period_end,
            },
            "checkout_url": record.checkout_url,
            "portal_url": record.portal_url,
            "seats": record.seats,
            "entitlements": entitlements["entitlements"],
            "usage": usage,
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

    def _stripe_keys(self) -> tuple[str, str]:
        return (
            str(os.getenv("STRIPE_SECRET_KEY", "") or "").strip(),
            str(os.getenv("STRIPE_WEBHOOK_SECRET", "") or "").strip(),
        )

    @staticmethod
    def _degraded_reason(record: WorkspaceBillingRecord) -> str:
        normalized_status = str(record.status or "").strip().lower()
        if normalized_status in {"inactive", "past_due", "unpaid", "canceled", "cancelled", "incomplete_expired"}:
            return f"subscription_{normalized_status}"
        return ""

    def _effective_plan_id(self, record: WorkspaceBillingRecord) -> str:
        normalized_status = str(record.status or "").strip().lower()
        if normalized_status in {"active", "trialing"}:
            return str(record.plan_id or "free").strip().lower() or "free"
        return "free"

    @staticmethod
    def _normalize_subscription_status(value: str) -> str:
        normalized = str(value or "").strip().lower()
        if normalized in {"active", "trialing", "past_due", "inactive", "unpaid", "canceled", "cancelled", "incomplete", "incomplete_expired"}:
            return "inactive" if normalized in {"canceled", "cancelled"} else normalized
        return "inactive"

    @staticmethod
    def _stripe_price_env(plan_id: str) -> str:
        return f"STRIPE_PRICE_{str(plan_id or '').strip().upper()}"

    def _stripe_price_id(self, plan_id: str) -> str:
        normalized_plan = str(plan_id or "free").strip().lower() or "free"
        if normalized_plan == "free":
            raise RuntimeError("free_plan_no_checkout")
        price_id = str(os.getenv(self._stripe_price_env(normalized_plan), "") or "").strip()
        if not price_id:
            raise RuntimeError("stripe_price_missing")
        return price_id

    def _stripe_client(self):
        secret_key, _ = self._stripe_keys()
        if not secret_key:
            raise RuntimeError("stripe_not_configured")
        try:
            import stripe  # type: ignore
        except Exception as exc:
            raise RuntimeError("stripe_unavailable") from exc
        stripe.api_key = secret_key
        return stripe

    def create_checkout_session(
        self,
        *,
        workspace_id: str,
        plan_id: str,
        success_url: str,
        cancel_url: str,
    ) -> dict[str, Any]:
        record = self._workspace(workspace_id)
        stripe = self._stripe_client()
        normalized_plan = str(plan_id or "free").strip().lower() or "free"
        price_id = self._stripe_price_id(normalized_plan)
        session = stripe.checkout.Session.create(
            mode="subscription",
            success_url=success_url,
            cancel_url=cancel_url,
            customer=record.stripe_customer_id or None,
            metadata={"workspace_id": record.workspace_id, "plan_id": normalized_plan},
            line_items=[{"price": price_id, "quantity": 1}],
        )
        record.checkout_url = str(getattr(session, "url", "") or "")
        record.metadata["pending_plan_id"] = normalized_plan
        record.updated_at = _now()
        self._save()
        return {
            "workspace_id": record.workspace_id,
            "plan_id": normalized_plan,
            "session_id": str(getattr(session, "id", "") or ""),
            "url": record.checkout_url,
        }

    def create_portal_session(self, *, workspace_id: str, return_url: str) -> dict[str, Any]:
        record = self._workspace(workspace_id)
        stripe = self._stripe_client()
        if not record.stripe_customer_id:
            raise RuntimeError("stripe_customer_missing")
        session = stripe.billing_portal.Session.create(customer=record.stripe_customer_id, return_url=return_url)
        record.portal_url = str(getattr(session, "url", "") or "")
        record.updated_at = _now()
        self._save()
        return {
            "workspace_id": record.workspace_id,
            "url": record.portal_url,
        }

    def handle_webhook(self, payload: bytes, signature: str) -> dict[str, Any]:
        secret_key, webhook_secret = self._stripe_keys()
        if not secret_key or not webhook_secret:
            raise RuntimeError("stripe_not_configured")
        try:
            import stripe  # type: ignore
        except Exception as exc:
            raise RuntimeError("stripe_unavailable") from exc
        event = stripe.Webhook.construct_event(payload=payload, sig_header=signature, secret=webhook_secret)
        event_type = str(event.get("type") or "")
        obj = dict((event.get("data") or {}).get("object") or {})
        metadata = obj.get("metadata") if isinstance(obj.get("metadata"), dict) else {}
        workspace_id = str((obj.get("metadata") or {}).get("workspace_id") or "local-workspace").strip() or "local-workspace"
        record = self._workspace(workspace_id)
        record.metadata["last_webhook_type"] = event_type
        if metadata.get("plan_id"):
            record.plan_id = str(metadata.get("plan_id") or record.plan_id)
        if event_type == "checkout.session.completed":
            record.stripe_customer_id = str(obj.get("customer") or record.stripe_customer_id or "")
            record.status = "active"
        elif event_type in {"customer.subscription.created", "customer.subscription.updated"}:
            record.stripe_subscription_id = str(obj.get("id") or record.stripe_subscription_id or "")
            record.stripe_customer_id = str(obj.get("customer") or record.stripe_customer_id or "")
            record.status = self._normalize_subscription_status(str(obj.get("status") or record.status or "active"))
            record.current_period_end = float(obj.get("current_period_end") or record.current_period_end or 0.0)
        elif event_type in {"customer.subscription.deleted", "invoice.payment_failed"}:
            record.status = "past_due" if event_type == "invoice.payment_failed" else "inactive"
        degraded_reason = self._degraded_reason(record)
        if degraded_reason:
            record.metadata["degraded_reason"] = degraded_reason
            record.metadata["effective_plan_id"] = self._effective_plan_id(record)
        else:
            record.metadata.pop("degraded_reason", None)
            record.metadata["effective_plan_id"] = self._effective_plan_id(record)
        record.updated_at = _now()
        self._save()
        return {
            "event_type": event_type,
            "workspace_id": workspace_id,
            "status": record.status,
            "effective_plan_id": self._effective_plan_id(record),
        }

    def verify_webhook_signature(self, payload: bytes, signature: str) -> dict[str, Any]:
        _, webhook_secret = self._stripe_keys()
        if not webhook_secret:
            raise RuntimeError("stripe_not_configured")
        digest = hmac.new(webhook_secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
        return {"verified": hmac.compare_digest(digest, signature or "")}


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
