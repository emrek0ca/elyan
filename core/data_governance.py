from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from security.privacy_guard import redact_text, sanitize_for_storage, sanitize_object


def _now() -> float:
    return time.time()


def _uuid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class DataClassification(str, Enum):
    PERSONAL = "personal"
    WORKSPACE = "workspace"
    OPERATIONAL = "operational"
    PUBLIC = "public"
    SECRET = "secret"


@dataclass
class ConsentPolicy:
    allow_personal_data_learning: bool = False
    allow_workspace_data_learning: bool = True
    allow_operational_data_learning: bool = True
    allow_public_data_learning: bool = True
    allow_secret_data_learning: bool = False
    allow_global_aggregation: bool = True
    allow_export: bool = True
    allow_delete: bool = True
    workspace_only: bool = True
    paused: bool = False
    opt_out: bool = False
    retention_mode: str = "standard"
    updated_at: float = field(default_factory=_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "allow_personal_data_learning": bool(self.allow_personal_data_learning),
            "allow_workspace_data_learning": bool(self.allow_workspace_data_learning),
            "allow_operational_data_learning": bool(self.allow_operational_data_learning),
            "allow_public_data_learning": bool(self.allow_public_data_learning),
            "allow_secret_data_learning": bool(self.allow_secret_data_learning),
            "allow_global_aggregation": bool(self.allow_global_aggregation),
            "allow_export": bool(self.allow_export),
            "allow_delete": bool(self.allow_delete),
            "workspace_only": bool(self.workspace_only),
            "paused": bool(self.paused),
            "opt_out": bool(self.opt_out),
            "retention_mode": str(self.retention_mode or "standard"),
            "updated_at": float(self.updated_at or 0.0),
            "metadata": dict(self.metadata or {}),
        }


@dataclass
class RetentionPolicy:
    retention_class: str = "standard"
    ttl_days: int = 365
    redact_personal_data: bool = True
    redact_secret_data: bool = True
    workspace_only: bool = True
    legal_hold: bool = False
    updated_at: float = field(default_factory=_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "retention_class": str(self.retention_class or "standard"),
            "ttl_days": max(0, int(self.ttl_days or 0)),
            "redact_personal_data": bool(self.redact_personal_data),
            "redact_secret_data": bool(self.redact_secret_data),
            "workspace_only": bool(self.workspace_only),
            "legal_hold": bool(self.legal_hold),
            "updated_at": float(self.updated_at or 0.0),
            "metadata": dict(self.metadata or {}),
        }


@dataclass
class WorkspaceDataPolicy:
    workspace_id: str
    allow_personal_data_learning: bool = False
    allow_workspace_data_learning: bool = True
    allow_operational_data_learning: bool = True
    allow_public_data_learning: bool = True
    allow_secret_data_learning: bool = False
    allow_global_aggregation: bool = True
    redact_personal_data: bool = True
    redact_secret_data: bool = True
    learning_scope: str = "workspace"
    retention_policy: RetentionPolicy = field(default_factory=RetentionPolicy)
    updated_at: float = field(default_factory=_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_id": str(self.workspace_id or "local-workspace"),
            "allow_personal_data_learning": bool(self.allow_personal_data_learning),
            "allow_workspace_data_learning": bool(self.allow_workspace_data_learning),
            "allow_operational_data_learning": bool(self.allow_operational_data_learning),
            "allow_public_data_learning": bool(self.allow_public_data_learning),
            "allow_secret_data_learning": bool(self.allow_secret_data_learning),
            "allow_global_aggregation": bool(self.allow_global_aggregation),
            "redact_personal_data": bool(self.redact_personal_data),
            "redact_secret_data": bool(self.redact_secret_data),
            "learning_scope": str(self.learning_scope or "workspace"),
            "retention_policy": self.retention_policy.to_dict(),
            "updated_at": float(self.updated_at or 0.0),
            "metadata": dict(self.metadata or {}),
        }


@dataclass
class PrivacyDecision:
    decision_id: str = field(default_factory=lambda: _uuid("privacy"))
    workspace_id: str = "local-workspace"
    user_id: str = "local-user"
    source_kind: str = "runtime"
    classification: DataClassification = DataClassification.OPERATIONAL
    learning_scope: str = "workspace"
    shared_learning_eligible: bool = True
    redacted: bool = True
    reason: str = ""
    consent_policy: ConsentPolicy = field(default_factory=ConsentPolicy)
    retention_policy: RetentionPolicy = field(default_factory=RetentionPolicy)
    payload: dict[str, Any] = field(default_factory=dict)
    text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": str(self.decision_id),
            "workspace_id": str(self.workspace_id or "local-workspace"),
            "user_id": str(self.user_id or "local-user"),
            "source_kind": str(self.source_kind or "runtime"),
            "classification": self.classification.value,
            "learning_scope": str(self.learning_scope or "workspace"),
            "shared_learning_eligible": bool(self.shared_learning_eligible),
            "redacted": bool(self.redacted),
            "reason": str(self.reason or ""),
            "consent_policy": self.consent_policy.to_dict(),
            "retention_policy": self.retention_policy.to_dict(),
            "payload": sanitize_object(dict(self.payload or {})),
            "text": str(self.text or ""),
            "metadata": sanitize_object(dict(self.metadata or {})),
            "created_at": float(self.created_at or 0.0),
        }


@dataclass
class DatasetEntry:
    entry_id: str = field(default_factory=lambda: _uuid("dataset"))
    workspace_id: str = "local-workspace"
    user_id: str = "local-user"
    source_kind: str = "runtime"
    source_id: str = ""
    classification: DataClassification = DataClassification.OPERATIONAL
    learning_scope: str = "workspace"
    shared_learning_eligible: bool = True
    redacted: bool = True
    text: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    consent_policy: ConsentPolicy = field(default_factory=ConsentPolicy)
    retention_policy: RetentionPolicy = field(default_factory=RetentionPolicy)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": str(self.entry_id),
            "workspace_id": str(self.workspace_id or "local-workspace"),
            "user_id": str(self.user_id or "local-user"),
            "source_kind": str(self.source_kind or "runtime"),
            "source_id": str(self.source_id or ""),
            "classification": self.classification.value,
            "learning_scope": str(self.learning_scope or "workspace"),
            "shared_learning_eligible": bool(self.shared_learning_eligible),
            "redacted": bool(self.redacted),
            "text": str(self.text or ""),
            "payload": sanitize_object(dict(self.payload or {})),
            "consent_policy": self.consent_policy.to_dict(),
            "retention_policy": self.retention_policy.to_dict(),
            "metadata": sanitize_object(dict(self.metadata or {})),
            "created_at": float(self.created_at or 0.0),
        }


_SECRET_RE = re.compile(r"\b(?:sk|pk|rk|api|token|key|secret|bearer)[-_]?[a-zA-Z0-9]{10,}\b", re.IGNORECASE)
_PERSONAL_HINTS = ("user_input", "user message", "message", "prompt", "reply", "email", "phone", "contact")
_WORKSPACE_HINTS = ("workspace", "project", "repo", "code", "file", "document", "artifact", "run", "task")
_PUBLIC_HINTS = ("public", "readme", "docs", "article", "blog", "website", "landing")
_OPERATIONAL_HINTS = ("operational", "execution", "tool", "approval", "feedback", "audit", "trace", "latency", "reliability")


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _has_personal_signal(text: str, metadata: dict[str, Any]) -> bool:
    lowered = text.lower()
    if any(hint in lowered for hint in _PERSONAL_HINTS):
        return True
    if any(isinstance(metadata.get(key), str) and str(metadata.get(key)).strip() for key in ("user_input", "email", "display_name", "prompt")):
        return True
    redacted = redact_text(text)
    return bool(redacted and redacted != text)


def _has_secret_signal(text: str, metadata: dict[str, Any]) -> bool:
    lowered = text.lower()
    if _SECRET_RE.search(text):
        return True
    if any(bool(metadata.get(key)) for key in ("contains_secret", "secret", "sensitive", "token", "api_key")):
        return True
    if any(marker in lowered for marker in ("password", "oauth", "refresh_token", "access_token", "ssh key")):
        return True
    return False


def classify_data(
    payload: Any = None,
    *,
    text: str = "",
    source_kind: str = "",
    metadata: dict[str, Any] | None = None,
    default: DataClassification = DataClassification.OPERATIONAL,
) -> DataClassification:
    meta = dict(metadata or {})
    source = _normalize_text(source_kind).lower()
    content = _normalize_text(text or payload)
    if _has_secret_signal(content, meta) or source in {"secret", "credential", "token", "key"}:
        return DataClassification.SECRET
    if source in {"interaction", "prompt", "message", "user_input", "user_message", "login"} or _has_personal_signal(content, meta):
        return DataClassification.PERSONAL
    if source in {"workspace", "project", "repo", "file", "document", "artifact", "task", "code"}:
        return DataClassification.WORKSPACE
    if source in {"public", "readme", "docs", "article", "blog", "website"}:
        return DataClassification.PUBLIC
    if source in {"operational", "execution", "tool", "approval", "feedback", "audit", "trace", "reliability", "run"}:
        return DataClassification.OPERATIONAL
    if any(marker in content.lower() for marker in _WORKSPACE_HINTS):
        return DataClassification.WORKSPACE
    if any(marker in content.lower() for marker in _PUBLIC_HINTS):
        return DataClassification.PUBLIC
    if any(marker in content.lower() for marker in _OPERATIONAL_HINTS):
        return DataClassification.OPERATIONAL
    return default


def build_retention_policy(classification: DataClassification, *, metadata: dict[str, Any] | None = None) -> RetentionPolicy:
    meta = dict(metadata or {})
    if classification is DataClassification.SECRET:
        return RetentionPolicy(retention_class="ephemeral", ttl_days=int(meta.get("ttl_days") or 7), workspace_only=True, redact_personal_data=True, redact_secret_data=True, metadata=meta)
    if classification is DataClassification.PERSONAL:
        return RetentionPolicy(retention_class="short", ttl_days=int(meta.get("ttl_days") or 30), workspace_only=True, redact_personal_data=True, redact_secret_data=True, metadata=meta)
    if classification is DataClassification.WORKSPACE:
        return RetentionPolicy(retention_class="standard", ttl_days=int(meta.get("ttl_days") or 365), workspace_only=True, redact_personal_data=True, redact_secret_data=True, metadata=meta)
    if classification is DataClassification.PUBLIC:
        return RetentionPolicy(retention_class="standard", ttl_days=int(meta.get("ttl_days") or 365), workspace_only=False, redact_personal_data=False, redact_secret_data=True, metadata=meta)
    return RetentionPolicy(retention_class="aggregate", ttl_days=int(meta.get("ttl_days") or 365), workspace_only=False, redact_personal_data=True, redact_secret_data=True, metadata=meta)


def build_workspace_data_policy(
    workspace_id: str = "local-workspace",
    *,
    metadata: dict[str, Any] | None = None,
    allow_global_aggregation: bool = True,
) -> WorkspaceDataPolicy:
    meta = dict(metadata or {})
    return WorkspaceDataPolicy(
        workspace_id=str(workspace_id or "local-workspace"),
        allow_personal_data_learning=False,
        allow_workspace_data_learning=True,
        allow_operational_data_learning=True,
        allow_public_data_learning=True,
        allow_secret_data_learning=False,
        allow_global_aggregation=bool(allow_global_aggregation),
        redact_personal_data=True,
        redact_secret_data=True,
        learning_scope="workspace",
        retention_policy=RetentionPolicy(metadata=meta),
        metadata=meta,
    )


def build_privacy_decision(
    *,
    workspace_id: str = "local-workspace",
    user_id: str = "local-user",
    source_kind: str = "runtime",
    text: str = "",
    payload: Any = None,
    metadata: dict[str, Any] | None = None,
    consent_policy: ConsentPolicy | None = None,
    workspace_policy: WorkspaceDataPolicy | None = None,
    classification: DataClassification | str | None = None,
) -> PrivacyDecision:
    meta = dict(metadata or {})
    policy = workspace_policy or build_workspace_data_policy(workspace_id, metadata=meta)
    consent = consent_policy or ConsentPolicy(
        allow_workspace_data_learning=policy.allow_workspace_data_learning,
        allow_operational_data_learning=policy.allow_operational_data_learning,
        allow_public_data_learning=policy.allow_public_data_learning,
        allow_secret_data_learning=policy.allow_secret_data_learning,
        allow_global_aggregation=policy.allow_global_aggregation,
        workspace_only=True,
        metadata=meta,
    )
    cls = classification
    if isinstance(cls, str) and cls.strip():
        try:
            cls = DataClassification(cls.strip().lower())
        except Exception:
            cls = None
    if not isinstance(cls, DataClassification):
        cls = classify_data(payload, text=text, source_kind=source_kind, metadata=meta)
    retention = build_retention_policy(cls, metadata=meta)
    shared = False
    learning_scope = "local"
    if cls is DataClassification.WORKSPACE and bool(policy.allow_workspace_data_learning) and bool(consent.allow_workspace_data_learning):
        shared = True
        learning_scope = "workspace"
    elif cls is DataClassification.OPERATIONAL and bool(policy.allow_operational_data_learning) and bool(consent.allow_operational_data_learning):
        shared = True
        learning_scope = "global" if bool(policy.allow_global_aggregation) and bool(consent.allow_global_aggregation) else "workspace"
    elif cls is DataClassification.PUBLIC and bool(policy.allow_public_data_learning) and bool(consent.allow_public_data_learning):
        shared = True
        learning_scope = "global" if bool(policy.allow_global_aggregation) and bool(consent.allow_global_aggregation) else "workspace"
    elif cls is DataClassification.PERSONAL:
        learning_scope = "local"
    else:
        learning_scope = "local"
    redacted_text = sanitize_object(text)
    if isinstance(redacted_text, str):
        redacted_text = sanitize_for_storage(redacted_text)
    else:
        redacted_text = sanitize_for_storage(str(redacted_text))
    reason = ""
    if cls is DataClassification.PERSONAL:
        reason = "personal_data_default_denied"
    elif cls is DataClassification.SECRET:
        reason = "secret_data_default_denied"
    return PrivacyDecision(
        workspace_id=str(workspace_id or "local-workspace"),
        user_id=str(user_id or "local-user"),
        source_kind=str(source_kind or "runtime"),
        classification=cls,
        learning_scope=learning_scope,
        shared_learning_eligible=bool(shared),
        redacted=bool(redacted_text != text),
        reason=reason,
        consent_policy=consent,
        retention_policy=retention,
        payload=sanitize_object(payload) if payload is not None else {},
        text=str(redacted_text or ""),
        metadata=meta,
    )


def build_dataset_entry(
    *,
    workspace_id: str = "local-workspace",
    user_id: str = "local-user",
    source_kind: str = "runtime",
    source_id: str = "",
    text: str = "",
    payload: Any = None,
    metadata: dict[str, Any] | None = None,
    consent_policy: ConsentPolicy | None = None,
    workspace_policy: WorkspaceDataPolicy | None = None,
    classification: DataClassification | str | None = None,
) -> DatasetEntry:
    decision = build_privacy_decision(
        workspace_id=workspace_id,
        user_id=user_id,
        source_kind=source_kind,
        text=text,
        payload=payload,
        metadata=metadata,
        consent_policy=consent_policy,
        workspace_policy=workspace_policy,
        classification=classification,
    )
    return DatasetEntry(
        workspace_id=decision.workspace_id,
        user_id=decision.user_id,
        source_kind=decision.source_kind,
        source_id=str(source_id or ""),
        classification=decision.classification,
        learning_scope=decision.learning_scope,
        shared_learning_eligible=decision.shared_learning_eligible,
        redacted=decision.redacted,
        text=decision.text,
        payload=decision.payload,
        consent_policy=decision.consent_policy,
        retention_policy=decision.retention_policy,
        metadata=dict(decision.metadata or {}),
    )


__all__ = [
    "ConsentPolicy",
    "DataClassification",
    "DatasetEntry",
    "PrivacyDecision",
    "RetentionPolicy",
    "WorkspaceDataPolicy",
    "build_dataset_entry",
    "build_privacy_decision",
    "build_retention_policy",
    "build_workspace_data_policy",
    "classify_data",
]
