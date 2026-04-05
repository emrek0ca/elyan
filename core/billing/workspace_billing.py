from __future__ import annotations

import hashlib
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from core.billing.commercial_types import PLAN_CATALOG, TOKEN_PACK_CATALOG, get_plan, get_token_pack
from core.billing.iyzico_provider import IyzicoProvider
from core.billing.payment_provider import BillingProfile, CheckoutRequest, ProviderCompletion
from core.persistence import get_runtime_database
from core.storage_paths import resolve_elyan_data_dir


def _now() -> float:
    return time.time()


def _stable_id(prefix: str, *parts: str) -> str:
    joined = "::".join(str(part or "").strip() for part in parts)
    digest = hashlib.sha1(joined.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


def _period_key(ts: float | None = None) -> str:
    return time.strftime("%Y-%m", time.gmtime(float(ts or _now())))


def _plan_entitlements(plan_id: str) -> dict[str, Any]:
    plan = get_plan(plan_id)
    legacy_threads = {
        "free": 12,
        "pro": 120,
        "team": 600,
        "enterprise": 5000,
    }
    monthly_usage_budget = {
        "free": 10_000,
        "pro": 150_000,
        "team": 750_000,
        "enterprise": 5_000_000,
    }
    return {
        "plan_id": plan.plan_id,
        "included_credits": int(plan.included_credits),
        "seat_limit": int(plan.seat_limit),
        "connector_limit": int(plan.connector_limit),
        "artifact_limit": int(plan.artifact_limit),
        "premium_models": bool(plan.premium_models),
        "support_tier": str(plan.support_tier),
        "monthly_usage_budget": int(monthly_usage_budget.get(plan.plan_id, 10_000)),
        "max_threads": int(legacy_threads.get(plan.plan_id, 12)),
        "max_connectors": int(plan.connector_limit),
        "artifact_exports": int(plan.artifact_limit),
        "team_seats": int(plan.seat_limit),
        "workspace_policy": dict(plan.metadata or {}),
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
        key = str(workspace_id or "local-workspace").strip() or "local-workspace"
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
        workspace_key = str(workspace_id or "local-workspace").strip() or "local-workspace"
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
        balance = self._repository.get_credit_balance(record.workspace_id)
        period = _period_key()
        if str(record.metadata.get("included_credit_period") or "") == period:
            return balance
        if int(plan.included_credits) <= 0:
            record.metadata["included_credit_period"] = period
            record.updated_at = _now()
            self._save()
            return balance
        entry_id = _stable_id("included", record.workspace_id, effective_plan_id, period)
        self._repository.record_credit_entry(
            {
                "entry_id": entry_id,
                "workspace_id": record.workspace_id,
                "bucket": "included",
                "entry_type": "grant",
                "delta_credits": int(plan.included_credits),
                "reference_id": f"{effective_plan_id}:{period}",
                "metadata": {
                    "grant_type": "monthly_included",
                    "period": period,
                    "plan_id": effective_plan_id,
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
                "reference_id": f"{effective_plan_id}:{period}",
                "payload": {
                    "workspace_id": record.workspace_id,
                    "plan_id": effective_plan_id,
                    "credits": int(plan.included_credits),
                    "period": period,
                },
            }
        )
        record.metadata["included_credit_period"] = period
        record.metadata["effective_plan_id"] = effective_plan_id
        record.updated_at = _now()
        self._save()
        self._snapshot_entitlements(record.workspace_id, scope="monthly_refresh")
        return self._repository.get_credit_balance(record.workspace_id)

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
        workspace_key = str(workspace_id or "local-workspace").strip() or "local-workspace"
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
        return self._ensure_included_credits(record)

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
        return {
            "workspace_id": record.workspace_id,
            "plan_id": effective_plan_id,
            "requested_plan_id": record.plan_id,
            "status": self._normalize_status(record.status),
            "provider": str(record.metadata.get("provider") or self._provider.provider_name),
            "entitlements": entitlements,
            "credits": balance,
            "workspace_owned": True,
            "hybrid_billing": True,
            "degraded": bool(degraded_reason),
            "degraded_reason": degraded_reason,
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
            "budget": _plan_entitlements(self._effective_plan_id(record)).get("monthly_usage_budget", 0),
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

    def estimate_usage_credits(self, metric: str, amount: int = 1, *, metadata: dict[str, Any] | None = None) -> int:
        metric_key = str(metric or "unknown").strip().lower()
        count = max(1, int(amount or 1))
        details = dict(metadata or {})
        mode = str(details.get("mode") or details.get("task_type") or "cowork").strip().lower() or "cowork"
        prompt_length = max(
            0,
            int(details.get("prompt_length") or details.get("chars") or details.get("content_length") or 0),
        )
        routing_profile = str(details.get("routing_profile") or "balanced").strip().lower()
        review_strictness = str(details.get("review_strictness") or "balanced").strip().lower()
        prompt_surcharge = min(4, prompt_length // 900) if prompt_length > 0 else 0
        quality_surcharge = 1 if routing_profile == "quality_first" or review_strictness == "strict" else 0

        if metric_key == "inbox_events":
            return 0
        if metric_key == "task_extractions":
            return count
        if metric_key == "cowork_threads":
            base = {
                "cowork": 3,
                "document": 4,
                "presentation": 5,
                "website": 6,
            }.get(mode, 3)
            return count * (base + prompt_surcharge + quality_surcharge)
        if metric_key == "cowork_turns":
            base = {
                "cowork": 2,
                "document": 3,
                "presentation": 4,
                "website": 5,
            }.get(mode, 2)
            return count * (base + prompt_surcharge + quality_surcharge)
        if metric_key == "workflow_runs":
            base = {
                "document": 8,
                "presentation": 10,
                "website": 12,
            }.get(mode, 8)
            return count * (base + prompt_surcharge + quality_surcharge)
        return 0

    def authorize_usage(self, workspace_id: str, metric: str, amount: int = 1, *, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        estimated_credits = max(
            0,
            int((metadata or {}).get("estimated_credits") or self.estimate_usage_credits(metric, amount, metadata=metadata)),
        )
        decision = self.authorize_credits(workspace_id, required_credits=estimated_credits)
        return {
            **decision,
            "workspace_id": str(workspace_id or "local-workspace").strip() or "local-workspace",
            "metric": str(metric or "unknown").strip() or "unknown",
            "amount": max(0, int(amount or 0)),
            "estimated_credits": estimated_credits,
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
        workspace_key = str(workspace_id or "local-workspace").strip() or "local-workspace"
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
        if "estimated_credits" not in usage_metadata and "credits" not in usage_metadata:
            estimated_credits = self.estimate_usage_credits(metric, amount, metadata=usage_metadata)
            if estimated_credits > 0:
                usage_metadata["estimated_credits"] = estimated_credits
        entry = UsageLedgerEntry(
            usage_id=f"usage_{int(_now() * 1000)}_{len(record.usage) + 1}",
            workspace_id=record.workspace_id,
            metric=str(metric or "unknown").strip() or "unknown",
            amount=max(0, int(amount or 0)),
            metadata=usage_metadata,
        )
        record.usage.append(entry)
        record.updated_at = _now()
        self._repository.record_usage(entry.to_dict())
        self._repository.upsert_workspace(record.to_dict())
        estimated_credits = max(0, int(entry.metadata.get("estimated_credits") or entry.metadata.get("credits") or 0))
        if estimated_credits > 0:
            self.debit_credits(
                record.workspace_id,
                required_credits=estimated_credits,
                reference_id=entry.usage_id,
                metadata={"metric": entry.metric, **entry.metadata},
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
        workspace_key = str(workspace_id or "local-workspace").strip() or "local-workspace"
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
            entry_scope = period
            grant_metadata.setdefault("period", period)
            grant_metadata.setdefault("grant_type", "plan_included")
        else:
            entry_scope = str(reference_id or grant_metadata.get("pack_id") or grant_metadata.get("token_pack_id") or grant_credits).strip()
            grant_metadata.setdefault("grant_type", "token_pack")
        entry = self._repository.record_credit_entry(
            {
                "entry_id": _stable_id("creditgrant", workspace_key, normalized_bucket, entry_scope),
                "workspace_id": workspace_key,
                "bucket": normalized_bucket,
                "entry_type": "grant",
                "delta_credits": grant_credits,
                "reference_id": str(reference_id or "").strip(),
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
                "reference_id": str(reference_id or "").strip(),
                "payload": {
                    "workspace_id": workspace_key,
                    "bucket": normalized_bucket,
                    "credits": grant_credits,
                    "reference_id": str(reference_id or "").strip(),
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
        return {
            "workspace_id": workspace_key,
            "bucket": normalized_bucket,
            "credits": grant_credits,
            "reference_id": str(reference_id or "").strip(),
            "entry": entry,
            "event": event,
            "balance": snapshot.get("credits") if isinstance(snapshot, dict) else self._repository.get_credit_balance(workspace_key),
        }

    def reconcile_usage(
        self,
        workspace_id: str,
        *,
        usage_id: str,
        actual_credits: int,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        workspace_key = str(workspace_id or "local-workspace").strip() or "local-workspace"
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
            "usage": usage,
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
