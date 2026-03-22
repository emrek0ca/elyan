from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Iterable

from core.storage_paths import resolve_elyan_data_dir


def _now() -> float:
    return time.time()


def _safe_json(value: Any) -> Any:
    try:
        json.dumps(value, ensure_ascii=False, default=str)
        return value
    except Exception:
        return str(value)


@dataclass
class IntegrationTraceRecord:
    trace_id: str = field(default_factory=lambda: f"itr_{uuid.uuid4().hex[:12]}")
    request_id: str = ""
    user_id: str = ""
    session_id: str = ""
    channel: str = ""
    provider: str = ""
    connector_name: str = ""
    integration_type: str = ""
    operation: str = "connector"
    status: str = ""
    success: bool = False
    auth_state: str = ""
    auth_strategy: str = ""
    account_alias: str = ""
    fallback_used: bool = False
    fallback_reason: str = ""
    install_state: str = ""
    retry_count: int = 0
    latency_ms: float = 0.0
    evidence: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    verification: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["evidence"] = [_safe_json(item) for item in list(data.get("evidence") or [])]
        data["artifacts"] = [_safe_json(item) for item in list(data.get("artifacts") or [])]
        data["verification"] = _safe_json(dict(data.get("verification") or {}))
        data["metadata"] = _safe_json(dict(data.get("metadata") or {}))
        return data


class IntegrationTraceStore:
    def __init__(self, storage_root: Path | None = None) -> None:
        self.storage_root = Path(storage_root or (resolve_elyan_data_dir() / "integrations")).expanduser()
        self.storage_root.mkdir(parents=True, exist_ok=True)
        self.trace_path = self.storage_root / "integration_traces.jsonl"
        self._lock = threading.Lock()

    def record_trace(
        self,
        *,
        request_id: str = "",
        user_id: str = "",
        session_id: str = "",
        channel: str = "",
        provider: str = "",
        connector_name: str = "",
        integration_type: str = "",
        operation: str = "connector",
        status: str = "",
        success: bool = False,
        auth_state: str = "",
        auth_strategy: str = "",
        account_alias: str = "",
        fallback_used: bool = False,
        fallback_reason: str = "",
        install_state: str = "",
        retry_count: int = 0,
        latency_ms: float = 0.0,
        evidence: Iterable[dict[str, Any]] | None = None,
        artifacts: Iterable[dict[str, Any]] | None = None,
        verification: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        record = IntegrationTraceRecord(
            request_id=str(request_id or ""),
            user_id=str(user_id or ""),
            session_id=str(session_id or ""),
            channel=str(channel or ""),
            provider=str(provider or ""),
            connector_name=str(connector_name or ""),
            integration_type=str(integration_type or ""),
            operation=str(operation or "connector"),
            status=str(status or ""),
            success=bool(success),
            auth_state=str(auth_state or ""),
            auth_strategy=str(auth_strategy or ""),
            account_alias=str(account_alias or ""),
            fallback_used=bool(fallback_used),
            fallback_reason=str(fallback_reason or ""),
            install_state=str(install_state or ""),
            retry_count=max(0, int(retry_count or 0)),
            latency_ms=float(latency_ms or 0.0),
            evidence=[dict(item) for item in list(evidence or []) if isinstance(item, dict)],
            artifacts=[dict(item) for item in list(artifacts or []) if isinstance(item, dict)],
            verification=dict(verification or {}),
            metadata=dict(metadata or {}),
        )
        payload = record.to_dict()
        with self._lock:
            with self.trace_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str) + "\n")
        return payload

    def list_traces(
        self,
        *,
        limit: int = 100,
        provider: str = "",
        user_id: str = "",
        operation: str = "",
        connector_name: str = "",
        integration_type: str = "",
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        if not self.trace_path.exists():
            return rows
        low_provider = str(provider or "").strip().lower()
        low_user = str(user_id or "").strip().lower()
        low_operation = str(operation or "").strip().lower()
        low_connector = str(connector_name or "").strip().lower()
        low_type = str(integration_type or "").strip().lower()
        try:
            raw_lines = self.trace_path.read_text(encoding="utf-8").splitlines()
        except Exception:
            return rows
        for raw in reversed(raw_lines):
            if not raw.strip():
                continue
            try:
                item = json.loads(raw)
            except Exception:
                continue
            if low_provider and str(item.get("provider") or "").strip().lower() != low_provider:
                continue
            if low_user and str(item.get("user_id") or "").strip().lower() != low_user:
                continue
            if low_operation and str(item.get("operation") or "").strip().lower() != low_operation:
                continue
            if low_connector and str(item.get("connector_name") or "").strip().lower() != low_connector:
                continue
            if low_type and str(item.get("integration_type") or "").strip().lower() != low_type:
                continue
            rows.append(item)
            if len(rows) >= max(1, int(limit or 100)):
                break
        return rows

    def summary(self, *, limit: int = 200) -> dict[str, Any]:
        rows = self.list_traces(limit=limit)
        by_provider: dict[str, int] = {}
        by_operation: dict[str, int] = {}
        by_status: dict[str, int] = {}
        fallback_count = 0
        for row in rows:
            provider = str(row.get("provider") or "unknown")
            operation = str(row.get("operation") or "connector")
            status = str(row.get("status") or "unknown")
            by_provider[provider] = int(by_provider.get(provider, 0)) + 1
            by_operation[operation] = int(by_operation.get(operation, 0)) + 1
            by_status[status] = int(by_status.get(status, 0)) + 1
            if bool(row.get("fallback_used")):
                fallback_count += 1
        avg_latency = 0.0
        if rows:
            avg_latency = sum(float(row.get("latency_ms") or 0.0) for row in rows) / len(rows)
        return {
            "total": len(rows),
            "avg_latency_ms": round(avg_latency, 2),
            "fallback_count": fallback_count,
            "by_provider": by_provider,
            "by_operation": by_operation,
            "by_status": by_status,
            "recent": rows[:20],
            "trace_path": str(self.trace_path),
        }


_trace_store: IntegrationTraceStore | None = None


def get_integration_trace_store() -> IntegrationTraceStore:
    global _trace_store
    if _trace_store is None:
        _trace_store = IntegrationTraceStore()
    return _trace_store


__all__ = ["IntegrationTraceRecord", "IntegrationTraceStore", "get_integration_trace_store"]
