from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.storage_paths import resolve_elyan_data_dir
from security.audit import get_audit_logger
from utils.logger import get_logger

logger = get_logger("decision_fabric")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _tokenize(value: str) -> list[str]:
    return [token for token in _normalize_text(value).split(" ") if token]


@dataclass(slots=True)
class Decision:
    id: str = ""
    summary: str = ""
    context: str = ""
    actor_id: str = "local-user"
    workspace_id: str = "local-workspace"
    timestamp: str = ""
    related_event_ids: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def normalized(self) -> Decision:
        return Decision(
            id=str(self.id or f"decision_{uuid.uuid4().hex[:12]}").strip(),
            summary=" ".join(str(self.summary or "").strip().split()),
            context=" ".join(str(self.context or "").strip().split()),
            actor_id=str(self.actor_id or "local-user").strip() or "local-user",
            workspace_id=str(self.workspace_id or "local-workspace").strip() or "local-workspace",
            timestamp=str(self.timestamp or _utc_now()).strip() or _utc_now(),
            related_event_ids=[str(item).strip() for item in list(self.related_event_ids or []) if str(item).strip()],
            tags=[str(item).strip() for item in list(self.tags or []) if str(item).strip()],
            metadata=dict(self.metadata or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        clean = self.normalized()
        return {
            "id": clean.id,
            "summary": clean.summary,
            "context": clean.context,
            "actor_id": clean.actor_id,
            "workspace_id": clean.workspace_id,
            "timestamp": clean.timestamp,
            "related_event_ids": list(clean.related_event_ids),
            "tags": list(clean.tags),
            "metadata": dict(clean.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> Decision:
        row = dict(payload or {})
        return cls(
            id=str(row.get("id") or "").strip(),
            summary=str(row.get("summary") or "").strip(),
            context=str(row.get("context") or "").strip(),
            actor_id=str(row.get("actor_id") or "local-user").strip() or "local-user",
            workspace_id=str(row.get("workspace_id") or "local-workspace").strip() or "local-workspace",
            timestamp=str(row.get("timestamp") or "").strip(),
            related_event_ids=[str(item).strip() for item in list(row.get("related_event_ids") or []) if str(item).strip()],
            tags=[str(item).strip() for item in list(row.get("tags") or []) if str(item).strip()],
            metadata=dict(row.get("metadata") or {}),
        ).normalized()


class DecisionFabric:
    def __init__(self, storage_path: str | Path | None = None, *, audit_logger: Any | None = None) -> None:
        default_path = resolve_elyan_data_dir() / "memory" / "decision_fabric.jsonl"
        self.storage_path = Path(storage_path or default_path).expanduser().resolve()
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.audit_logger = audit_logger or get_audit_logger()
        self._lock = threading.Lock()

    def record(self, decision: Decision) -> str:
        entry = decision.normalized()
        with self._lock:
            with self.storage_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")
        self._audit(
            action="record",
            success=True,
            params={
                "workspace_id": entry.workspace_id,
                "actor_id": entry.actor_id,
                "tag_count": len(entry.tags),
                "related_event_count": len(entry.related_event_ids),
            },
            result={"decision_id": entry.id},
        )
        return entry.id

    def search(self, query: str, workspace_id: str, *, limit: int = 20) -> list[Decision]:
        workspace_key = str(workspace_id or "local-workspace").strip() or "local-workspace"
        tokens = _tokenize(query)
        decisions = [item for item in self._load_all() if item.workspace_id == workspace_key]
        scored: list[tuple[int, str, Decision]] = []
        for decision in decisions:
            score = self._score(decision, tokens)
            if score <= 0 and tokens:
                continue
            scored.append((score, decision.timestamp, decision))
        scored.sort(key=lambda row: (row[0], row[1]), reverse=True)
        results = [row[2] for row in scored[: max(1, int(limit or 20))]]
        self._audit(
            action="search",
            success=True,
            params={
                "workspace_id": workspace_key,
                "query": str(query or ""),
                "limit": max(1, int(limit or 20)),
            },
            result={"result_count": len(results)},
        )
        return results

    def _load_all(self) -> list[Decision]:
        if not self.storage_path.exists():
            return []
        rows: list[Decision] = []
        with self._lock:
            with self.storage_path.open("r", encoding="utf-8") as handle:
                for line_number, line in enumerate(handle, start=1):
                    content = str(line or "").strip()
                    if not content:
                        continue
                    try:
                        payload = json.loads(content)
                    except json.JSONDecodeError as exc:
                        logger.warning(f"decision_fabric_skipped_invalid_line:{line_number}:{exc}")
                        continue
                    if not isinstance(payload, dict):
                        logger.warning(f"decision_fabric_skipped_non_object_line:{line_number}")
                        continue
                    rows.append(Decision.from_dict(payload))
        return rows

    @staticmethod
    def _score(decision: Decision, tokens: list[str]) -> int:
        searchable = " ".join(
            [
                decision.summary,
                decision.context,
                " ".join(decision.tags),
                " ".join(decision.related_event_ids),
            ]
        )
        haystack = _normalize_text(searchable)
        if not tokens:
            return 1
        score = 0
        for token in tokens:
            if token in haystack:
                score += 2
            if any(token == tag.lower() for tag in decision.tags):
                score += 3
        return score

    def _audit(
        self,
        *,
        action: str,
        success: bool,
        params: dict[str, Any],
        result: dict[str, Any],
    ) -> None:
        self.audit_logger.log_operation(
            user_id=0,
            operation="decision_fabric",
            action=action,
            params=dict(params or {}),
            result=dict(result or {}),
            success=success,
            duration=0.0,
            risk_level="low",
            approved=True,
        )


__all__ = ["Decision", "DecisionFabric"]
