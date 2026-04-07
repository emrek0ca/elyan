from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from core.db import CORE_MIGRATIONS, DbManager, Repository, get_db_manager
from core.storage_paths import resolve_elyan_data_dir
from core.privacy.redactor import get_redactor
from security.privacy_guard import sanitize_for_storage, sanitize_object


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
            "payload": dict(self.payload or {}),
            "text": str(self.text or ""),
            "metadata": dict(self.metadata or {}),
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
            "payload": dict(self.payload or {}),
            "consent_policy": self.consent_policy.to_dict(),
            "retention_policy": self.retention_policy.to_dict(),
            "metadata": dict(self.metadata or {}),
            "created_at": float(self.created_at or 0.0),
        }


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def classify_data(
    payload: Any = None,
    *,
    text: str = "",
    source_kind: str = "",
    metadata: dict[str, Any] | None = None,
    default: DataClassification = DataClassification.OPERATIONAL,
) -> DataClassification:
    meta = dict(metadata or {})
    content = _normalize_text(text or payload)
    source = _normalize_text(source_kind).lower()
    if source in {"secret", "credential", "token", "key"}:
        return DataClassification.SECRET
    if source in {"workspace", "project", "repo", "artifact", "document", "file", "code"}:
        return DataClassification.WORKSPACE
    if source in {"public", "readme", "docs", "article", "blog", "website"}:
        return DataClassification.PUBLIC
    if source in {"message", "user_input", "prompt", "interaction"}:
        return DataClassification.PERSONAL
    if content != get_redactor().redact(content).value:
        if any(marker in content.lower() for marker in ("token", "secret", "password", "api key", "ssh key")):
            return DataClassification.SECRET
        return DataClassification.PERSONAL
    if any(bool(meta.get(key)) for key in ("contains_secret", "secret", "api_key", "token")):
        return DataClassification.SECRET
    if any(bool(meta.get(key)) for key in ("email", "display_name", "phone", "user_input")):
        return DataClassification.PERSONAL
    return default


def build_retention_policy(classification: DataClassification, *, metadata: dict[str, Any] | None = None) -> RetentionPolicy:
    meta = dict(metadata or {})
    if classification is DataClassification.SECRET:
        return RetentionPolicy(retention_class="ephemeral", ttl_days=int(meta.get("ttl_days") or 7), metadata=meta)
    if classification is DataClassification.PERSONAL:
        return RetentionPolicy(retention_class="short", ttl_days=int(meta.get("ttl_days") or 30), metadata=meta)
    if classification is DataClassification.PUBLIC:
        return RetentionPolicy(retention_class="standard", ttl_days=int(meta.get("ttl_days") or 365), workspace_only=False, redact_personal_data=False, metadata=meta)
    if classification is DataClassification.OPERATIONAL:
        return RetentionPolicy(retention_class="aggregate", ttl_days=int(meta.get("ttl_days") or 365), workspace_only=False, metadata=meta)
    return RetentionPolicy(retention_class="standard", ttl_days=int(meta.get("ttl_days") or 365), metadata=meta)


def build_workspace_data_policy(
    workspace_id: str = "local-workspace",
    *,
    metadata: dict[str, Any] | None = None,
    allow_global_aggregation: bool = True,
) -> WorkspaceDataPolicy:
    return WorkspaceDataPolicy(
        workspace_id=str(workspace_id or "local-workspace"),
        allow_global_aggregation=bool(allow_global_aggregation),
        retention_policy=RetentionPolicy(metadata=dict(metadata or {})),
        metadata=dict(metadata or {}),
    )


def _sanitize_text(value: str) -> tuple[str, bool]:
    clean = sanitize_for_storage(str(value or ""))
    result = get_redactor().redact(clean)
    return str(result.value or ""), bool(result.redacted or clean != value)


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
    sanitized_payload = sanitize_object(payload) if payload is not None else {}
    payload_result = get_redactor().redact_dict(sanitized_payload)
    sanitized_text, text_redacted = _sanitize_text(text)
    shared = False
    learning_scope = "local"
    reason = ""
    if consent.paused or consent.opt_out:
        reason = "learning_paused_or_opt_out"
    elif cls is DataClassification.SECRET:
        reason = "secret_data_default_denied"
    elif cls is DataClassification.PERSONAL:
        reason = "personal_data_default_denied"
    elif cls is DataClassification.OPERATIONAL and policy.allow_operational_data_learning and consent.allow_operational_data_learning:
        shared = True
        learning_scope = "global" if policy.allow_global_aggregation and consent.allow_global_aggregation else "workspace"
    elif cls is DataClassification.WORKSPACE and policy.allow_workspace_data_learning and consent.allow_workspace_data_learning:
        shared = True
        learning_scope = "workspace"
    elif cls is DataClassification.PUBLIC and policy.allow_public_data_learning and consent.allow_public_data_learning:
        shared = True
        learning_scope = "global" if policy.allow_global_aggregation and consent.allow_global_aggregation else "workspace"
    redacted = bool(text_redacted or payload_result.redacted or cls in {DataClassification.SECRET, DataClassification.OPERATIONAL})
    return PrivacyDecision(
        workspace_id=str(workspace_id or "local-workspace"),
        user_id=str(user_id or "local-user"),
        source_kind=str(source_kind or "runtime"),
        classification=cls,
        learning_scope=learning_scope,
        shared_learning_eligible=bool(shared and not reason),
        redacted=redacted,
        reason=reason,
        consent_policy=consent,
        retention_policy=retention,
        payload=dict(payload_result.value or {}),
        text=sanitized_text,
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
        payload=dict(decision.payload or {}),
        consent_policy=decision.consent_policy,
        retention_policy=decision.retention_policy,
        metadata=dict(decision.metadata or {}),
    )


class PrivacyEngine:
    def __init__(self, db_path: str | Path | None = None, *, runtime_db_path: str | Path | None = None) -> None:
        default_root = resolve_elyan_data_dir() / "privacy"
        default_root.mkdir(parents=True, exist_ok=True)
        consent_path = Path(db_path or (default_root / "consent.db")).expanduser()
        self.db = DbManager(db_path=consent_path, migrations=(CORE_MIGRATIONS[0],))
        self.repo = Repository(self.db)
        self.runtime_repo = Repository(get_db_manager(runtime_db_path)) if runtime_db_path is not None else Repository(get_db_manager())

    def _row_to_policy(self, row: dict[str, Any] | None) -> ConsentPolicy:
        if not row:
            return ConsentPolicy()
        metadata = json.loads(str(row.get("metadata_json") or "{}"))
        return ConsentPolicy(
            allow_personal_data_learning=bool(metadata.get("allow_personal_data_learning", False)),
            allow_workspace_data_learning=bool(metadata.get("allow_workspace_data_learning", True)),
            allow_operational_data_learning=bool(metadata.get("allow_operational_data_learning", True)),
            allow_public_data_learning=bool(metadata.get("allow_public_data_learning", True)),
            allow_secret_data_learning=False,
            allow_global_aggregation=bool(metadata.get("allow_global_aggregate", metadata.get("allow_global_aggregation", True))),
            paused=bool(metadata.get("paused", False)),
            opt_out=bool(metadata.get("opt_out", False)),
            retention_mode=str(metadata.get("retention_mode") or "standard"),
            updated_at=float(row.get("updated_at") or 0.0),
            metadata=metadata,
        )

    def set_consent(
        self,
        user_id: str,
        *,
        workspace_id: str = "local-workspace",
        scope: str = "learning",
        granted: bool = False,
        source: str = "privacy_api",
        expires_at: float = 0.0,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = _now()
        consent_id = _uuid("consent")
        payload = dict(metadata or {})
        row = (
            consent_id,
            str(user_id or "local-user"),
            str(workspace_id or "local-workspace"),
            str(scope or "learning"),
            int(bool(granted)),
            str(source or "privacy_api"),
            float(expires_at or 0.0),
            json.dumps(payload, sort_keys=True),
            now,
            now,
        )
        self.repo.execute(
            """
            INSERT INTO consent_policies(
                consent_id, user_id, workspace_id, scope, granted, source, expires_at, metadata_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            row,
        )
        self.runtime_repo.execute(
            """
            INSERT OR REPLACE INTO consent_policies(
                consent_id, user_id, workspace_id, scope, granted, source, expires_at, metadata_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            row,
        )
        return self.get_consent(user_id, workspace_id=workspace_id, scope=scope)

    def get_consent(self, user_id: str, *, workspace_id: str = "local-workspace", scope: str = "learning") -> dict[str, Any]:
        row = self.repo.fetchone(
            """
            SELECT * FROM consent_policies
            WHERE user_id = ? AND workspace_id = ? AND scope = ?
            ORDER BY updated_at DESC LIMIT 1
            """,
            (str(user_id or "local-user"), str(workspace_id or "local-workspace"), str(scope or "learning")),
        )
        policy = self._row_to_policy(row)
        granted = bool(row.get("granted", False)) if row else False
        return {
            "user_id": str(user_id or "local-user"),
            "workspace_id": str(workspace_id or "local-workspace"),
            "scope": str(scope or "learning"),
            "granted": granted,
            "policy": policy.to_dict(),
            "consent_id": str((row or {}).get("consent_id") or ""),
            "source": str((row or {}).get("source") or "privacy_engine"),
            "expires_at": float((row or {}).get("expires_at") or 0.0),
            "updated_at": float((row or {}).get("updated_at") or 0.0),
        }

    def decide(
        self,
        *,
        user_id: str,
        workspace_id: str = "local-workspace",
        source_kind: str = "runtime",
        text: str = "",
        payload: Any = None,
        metadata: dict[str, Any] | None = None,
        classification: DataClassification | str | None = None,
    ) -> PrivacyDecision:
        consent_row = self.get_consent(user_id, workspace_id=workspace_id, scope="learning")
        consent_payload = consent_row.get("policy") if bool(consent_row.get("granted")) else {}
        decision = build_privacy_decision(
            workspace_id=workspace_id,
            user_id=user_id,
            source_kind=source_kind,
            text=text,
            payload=payload,
            metadata=metadata,
            consent_policy=ConsentPolicy(**dict(consent_payload or {})),
            classification=classification,
        )
        if decision.classification is DataClassification.SECRET:
            decision.reason = "secret_data_default_denied"
        elif decision.classification is DataClassification.PERSONAL and not bool(consent_row.get("granted")):
            decision.reason = "personal_data_requires_consent"
            decision.shared_learning_eligible = False
            decision.learning_scope = "local"
        return decision

    def export_user_data(self, user_id: str, *, workspace_id: str = "local-workspace") -> dict[str, Any]:
        rows = self.repo.fetchall(
            """
            SELECT * FROM consent_policies
            WHERE user_id = ? AND workspace_id = ?
            ORDER BY updated_at DESC
            """,
            (str(user_id or "local-user"), str(workspace_id or "local-workspace")),
        )
        return {
            "user_id": str(user_id or "local-user"),
            "workspace_id": str(workspace_id or "local-workspace"),
            "consents": rows,
        }

    def delete_user_data(self, user_id: str, *, workspace_id: str = "") -> dict[str, Any]:
        params = [str(user_id or "local-user")]
        query = "DELETE FROM consent_policies WHERE user_id = ?"
        if workspace_id:
            query += " AND workspace_id = ?"
            params.append(str(workspace_id))
        deleted = self.repo.execute(query, params)
        self.runtime_repo.execute(query, params)
        return {
            "user_id": str(user_id or "local-user"),
            "workspace_id": str(workspace_id or "local-workspace"),
            "deleted": {"consent_policies": int(deleted)},
        }


_privacy_engine: PrivacyEngine | None = None


def get_privacy_engine(db_path: str | Path | None = None, *, runtime_db_path: str | Path | None = None) -> PrivacyEngine:
    global _privacy_engine
    if db_path is not None or runtime_db_path is not None:
        return PrivacyEngine(db_path=db_path, runtime_db_path=runtime_db_path)
    if _privacy_engine is None:
        _privacy_engine = PrivacyEngine()
    return _privacy_engine


__all__ = [
    "ConsentPolicy",
    "DataClassification",
    "DatasetEntry",
    "PrivacyDecision",
    "PrivacyEngine",
    "RetentionPolicy",
    "WorkspaceDataPolicy",
    "build_dataset_entry",
    "build_privacy_decision",
    "build_retention_policy",
    "build_workspace_data_policy",
    "classify_data",
    "get_privacy_engine",
]
