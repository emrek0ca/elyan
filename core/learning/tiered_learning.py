from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from core.db import DbManager, Repository
from core.personalization.policy_learning import LearningSignal, PolicyLearningStore
from core.privacy import DataClassification, PrivacyEngine, get_privacy_engine, get_redactor
from core.storage_paths import resolve_elyan_data_dir


class LearningTier(str, Enum):
    TIER1 = "tier1"
    TIER2 = "tier2"
    TIER3 = "tier3"
    SKIPPED = "skipped"


@dataclass
class TieredSignal:
    user_id: str
    workspace_id: str = "local-workspace"
    task_type: str = "general"
    source_kind: str = "runtime"
    action: str = ""
    outcome: str = "unknown"
    latency_ms: float = 0.0
    text: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    raw_metadata: dict[str, Any] = field(default_factory=dict)
    classification: DataClassification = DataClassification.OPERATIONAL
    allow_global_aggregate: bool = False


class TieredLearningHub:
    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        privacy_engine: PrivacyEngine | None = None,
        policy_store: PolicyLearningStore | None = None,
    ) -> None:
        root = resolve_elyan_data_dir() / "learning"
        root.mkdir(parents=True, exist_ok=True)
        learning_path = Path(db_path or (root / "tiered.sqlite3")).expanduser()
        self.db = DbManager(db_path=learning_path, migrations=())
        with self.db.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    applied_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS operational_signals (
                    signal_id TEXT PRIMARY KEY,
                    user_hash TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    source_kind TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    action TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    latency_ms REAL NOT NULL DEFAULT 0,
                    classification TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_operational_signals_workspace_time
                    ON operational_signals(workspace_id, created_at DESC);
                CREATE TABLE IF NOT EXISTS global_aggregate (
                    bucket TEXT PRIMARY KEY,
                    signal_count INTEGER NOT NULL DEFAULT 0,
                    success_count INTEGER NOT NULL DEFAULT 0,
                    total_latency_ms REAL NOT NULL DEFAULT 0,
                    updated_at REAL NOT NULL
                );
                """
            )
            conn.commit()
        self.repo = Repository(self.db)
        self.privacy_engine = privacy_engine or get_privacy_engine()
        self.policy_store = policy_store or PolicyLearningStore()

    @staticmethod
    def _user_hash(user_id: str) -> str:
        return hashlib.sha256(str(user_id or "local").encode("utf-8")).hexdigest()[:16]

    def record(self, signal: TieredSignal) -> dict[str, Any]:
        uid = str(signal.user_id or "local")
        policy = self.policy_store.get_user_policy(uid)
        if bool(policy.get("paused")) or bool(policy.get("opt_out")):
            return {"success": True, "tier": LearningTier.SKIPPED.value, "skipped": "learning_paused_or_opt_out", "user_id": uid}
        decision = self.privacy_engine.decide(
            user_id=uid,
            workspace_id=signal.workspace_id,
            source_kind=signal.source_kind,
            text=signal.text,
            payload=signal.payload,
            metadata=signal.raw_metadata,
            classification=signal.classification,
        )
        if not decision.shared_learning_eligible:
            return {
                "success": True,
                "tier": LearningTier.SKIPPED.value,
                "skipped": decision.reason or "privacy_denied",
                "decision": decision.to_dict(),
            }
        payload = get_redactor().redact_dict(dict(decision.payload or {})).value
        metadata = get_redactor().redact_dict(dict(signal.raw_metadata or {})).value
        learning_signal = LearningSignal(
            user_id=uid,
            task_type=str(signal.task_type or "general"),
            outcome=str(signal.outcome or "unknown"),
            latency_ms=float(signal.latency_ms or 0.0),
            source=str(signal.source_kind or "runtime"),
            action=str(signal.action or ""),
            metadata={key: value for key, value in dict(metadata or {}).items() if key != "raw_metadata"},
        )
        tier = LearningTier.TIER2 if decision.learning_scope in {"workspace", "global"} else LearningTier.TIER1
        if signal.classification is DataClassification.PUBLIC:
            tier = LearningTier.TIER1
        self.policy_store.record_signal(learning_signal)
        if tier is LearningTier.TIER2:
            self.repo.execute(
                """
                INSERT OR REPLACE INTO operational_signals(
                    signal_id, user_hash, workspace_id, source_kind, task_type, action, outcome, latency_ms, classification, payload_json, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"signal_{int(time.time() * 1000)}_{self._user_hash(uid)}",
                    self._user_hash(uid),
                    str(signal.workspace_id or "local-workspace"),
                    str(signal.source_kind or "runtime"),
                    str(signal.task_type or "general"),
                    str(signal.action or ""),
                    str(signal.outcome or "unknown"),
                    float(signal.latency_ms or 0.0),
                    decision.classification.value,
                    json.dumps(payload, sort_keys=True),
                    json.dumps(metadata, sort_keys=True),
                    time.time(),
                ),
            )
        if signal.allow_global_aggregate and bool(policy.get("opt_out")) is False and decision.learning_scope == "global":
            bucket = f"{signal.task_type}:{signal.action or 'default'}"
            current = self.repo.fetchone("SELECT * FROM global_aggregate WHERE bucket = ?", (bucket,)) or {}
            signal_count = int(current.get("signal_count") or 0) + 1
            success_count = int(current.get("success_count") or 0) + (1 if str(signal.outcome).lower() in {"success", "completed", "ok"} else 0)
            total_latency = float(current.get("total_latency_ms") or 0.0) + float(signal.latency_ms or 0.0)
            self.repo.execute(
                """
                INSERT OR REPLACE INTO global_aggregate(bucket, signal_count, success_count, total_latency_ms, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (bucket, signal_count, success_count, total_latency, time.time()),
            )
            tier = LearningTier.TIER3
        return {"success": True, "tier": tier.value, "decision": decision.to_dict()}

    def stats(self) -> dict[str, Any]:
        totals = self.repo.fetchone("SELECT COUNT(*) AS total FROM operational_signals") or {"total": 0}
        rows = self.repo.fetchall("SELECT classification, COUNT(*) AS count FROM operational_signals GROUP BY classification")
        return {
            "total_signals": int(totals.get("total") or 0),
            "by_classification": {str(row.get("classification") or "unknown"): int(row.get("count") or 0) for row in rows},
        }

    def global_summary(self) -> dict[str, Any]:
        rows = self.repo.fetchall("SELECT * FROM global_aggregate ORDER BY updated_at DESC")
        items = []
        for row in rows:
            count = max(1, int(row.get("signal_count") or 0))
            items.append(
                {
                    "bucket": str(row.get("bucket") or ""),
                    "signal_count": count,
                    "success_count": int(row.get("success_count") or 0),
                    "avg_latency_ms": float(row.get("total_latency_ms") or 0.0) / count,
                    "updated_at": float(row.get("updated_at") or 0.0),
                }
            )
        return {"aggregates": items, "total_buckets": len(items)}

    def delete_user_data(self, user_id: str) -> dict[str, Any]:
        deleted = self.repo.execute("DELETE FROM operational_signals WHERE user_hash = ?", (self._user_hash(user_id),))
        return {"user_id": str(user_id or "local"), "deleted": {"operational_signals": int(deleted)}}


_tiered_hub: TieredLearningHub | None = None


def get_tiered_hub(db_path: str | Path | None = None) -> TieredLearningHub:
    global _tiered_hub
    if db_path is not None:
        return TieredLearningHub(db_path=db_path)
    if _tiered_hub is None:
        _tiered_hub = TieredLearningHub()
    return _tiered_hub


__all__ = ["LearningTier", "TieredLearningHub", "TieredSignal", "get_tiered_hub"]
