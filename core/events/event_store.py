from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Dict, Iterable, List, Optional

from core.observability.logger import get_structured_logger
from core.runtime_backends import get_runtime_backend_registry

slog = get_structured_logger("event_store")


class EventType(str, Enum):
    AGENT_STARTED = "agent.started"
    AGENT_COMPLETED = "agent.completed"
    AGENT_FAILED = "agent.failed"
    TASK_RECEIVED = "task.received"
    TASK_PLANNED = "task.planned"
    TASK_STEP_STARTED = "task.step.started"
    TASK_STEP_COMPLETED = "task.step.completed"
    TASK_STEP_FAILED = "task.step.failed"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"
    TASK_CANCELLED = "task.cancelled"
    TOOL_INVOKED = "tool.invoked"
    TOOL_SUCCEEDED = "tool.succeeded"
    TOOL_FAILED = "tool.failed"
    FEEDBACK_RECEIVED = "feedback.received"
    POLICY_UPDATED = "policy.updated"
    BANDIT_UPDATED = "bandit.updated"
    APPROVAL_REQUESTED = "approval.requested"
    APPROVAL_GRANTED = "approval.granted"
    APPROVAL_DENIED = "approval.denied"
    SECURITY_DECISION_MADE = "security.decision_made"
    PROMPT_BLOCKED = "security.prompt_blocked"
    SECRET_REDACTED = "security.secret_redacted"
    CLOUD_ESCALATION_DENIED = "security.cloud_escalation_denied"
    CLOUD_ESCALATION_APPROVED = "security.cloud_escalation_approved"
    SANDBOX_VIOLATION = "security.sandbox_violation"
    TOKEN_ISSUED = "security.token_issued"
    TOKEN_REVOKED = "security.token_revoked"
    MEMORY_STORED = "memory.stored"
    MEMORY_RETRIEVED = "memory.retrieved"


@dataclass(slots=True)
class Event:
    event_id: str
    event_type: EventType
    aggregate_id: str
    aggregate_type: str
    payload: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    sequence_number: int = 0
    causation_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["event_type"] = self.event_type.value
        return data

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Event":
        payload_raw = row["payload"] if "payload" in row.keys() else "{}"
        try:
            payload = json.loads(payload_raw or "{}")
        except Exception:
            payload = {}
        try:
            event_type = EventType(str(row["event_type"]))
        except Exception:
            event_type = EventType.MEMORY_STORED
        return cls(
            event_id=str(row["event_id"]),
            event_type=event_type,
            aggregate_id=str(row["aggregate_id"]),
            aggregate_type=str(row["aggregate_type"]),
            payload=payload if isinstance(payload, dict) else {},
            timestamp=float(row["timestamp"] or 0.0),
            sequence_number=int(row["sequence_number"] or 0),
            causation_id=row["causation_id"],
        )


def _default_db_path() -> Path:
    return Path(os.path.expanduser("~/.elyan/events.db")).expanduser()


class EventStore:
    def __init__(self, db_path: str | Path | None = None, *, on_append: Optional[Callable[[Event], None]] = None):
        self.db_path = Path(db_path or _default_db_path()).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._callbacks: list[Callable[[Event], None]] = []
        if on_append is not None:
            self._callbacks.append(on_append)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._native_backend = None
        self._native_backend_name = "python"
        self._init_db()
        self._init_native_backend()

    @property
    def connection(self) -> sqlite3.Connection:
        return self._conn

    @property
    def lock(self) -> RLock:
        return self._lock

    def add_append_listener(self, callback: Callable[[Event], None]) -> None:
        self._callbacks.append(callback)

    def _init_db(self) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    aggregate_id TEXT NOT NULL,
                    aggregate_type TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    sequence_number INTEGER NOT NULL,
                    causation_id TEXT
                )
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_events_aggregate_seq ON events(aggregate_id, sequence_number)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_events_type_ts ON events(event_type, timestamp)")
            self._conn.commit()

    def _init_native_backend(self) -> None:
        try:
            adapter = get_runtime_backend_registry().get_event_store_adapter(self.db_path)
        except Exception as exc:
            adapter = None
            slog.log_event(
                "event_store_native_init_failed",
                {"error": str(exc), "db_path": str(self.db_path)},
                level="warning",
            )
        if adapter is not None:
            self._native_backend = adapter
            self._native_backend_name = getattr(adapter, "module_name", "rust")
            slog.log_event(
                "event_store_native_enabled",
                {"backend": self._native_backend_name, "db_path": str(self.db_path)},
            )

    def append(self, event: Event) -> int:
        callbacks = list(self._callbacks)
        if not event.event_id:
            event.event_id = str(uuid.uuid4())
        if not event.timestamp:
            event.timestamp = time.time()
        next_seq = None
        backend_used = "python"
        if self._native_backend is not None:
            try:
                native_seq = self._native_backend.append_event(event)
                if native_seq is not None:
                    next_seq = int(native_seq)
                    backend_used = self._native_backend_name
            except Exception as exc:
                slog.log_event(
                    "event_store_native_append_failed",
                    {"error": str(exc), "backend": self._native_backend_name},
                    level="warning",
                )

        if next_seq is None:
            with self._lock:
                cur = self._conn.cursor()
                cur.execute(
                    "SELECT COALESCE(MAX(sequence_number), 0) FROM events WHERE aggregate_id = ?",
                    (event.aggregate_id,),
                )
                next_seq = int(cur.fetchone()[0] or 0) + 1
                cur.execute(
                    """
                    INSERT INTO events (
                        event_id, event_type, aggregate_id, aggregate_type,
                        payload, timestamp, sequence_number, causation_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.event_id,
                        event.event_type.value,
                        event.aggregate_id,
                        event.aggregate_type,
                        json.dumps(event.payload or {}, ensure_ascii=False, default=str),
                        float(event.timestamp),
                        next_seq,
                        event.causation_id,
                    ),
                )
                self._conn.commit()
        event.sequence_number = next_seq
        slog.log_event(
            "event_stored",
            {
                "event_type": event.event_type.value,
                "aggregate_id": event.aggregate_id,
                "sequence_number": next_seq,
                "backend": backend_used,
            },
            session_id=str(event.payload.get("session_id") or None),
            run_id=str(event.payload.get("run_id") or None),
        )
        for callback in callbacks:
            try:
                callback(event)
            except Exception as exc:
                slog.log_event(
                    "event_append_callback_error",
                    {"error": str(exc), "callback": getattr(callback, "__name__", "callback")},
                    level="warning",
                )
        return next_seq

    def get_aggregate_events(self, aggregate_id: str, from_seq: int = 0) -> List[Event]:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                SELECT * FROM events
                WHERE aggregate_id = ? AND sequence_number >= ?
                ORDER BY sequence_number ASC
                """,
                (aggregate_id, int(from_seq)),
            )
            return [Event.from_row(row) for row in cur.fetchall()]

    def query_by_type(
        self,
        event_type: EventType | str,
        since: float | None = None,
        limit: int = 100,
    ) -> List[Event]:
        event_type_value = event_type.value if isinstance(event_type, EventType) else str(event_type)
        sql = "SELECT * FROM events WHERE event_type = ?"
        params: list[Any] = [event_type_value]
        if since is not None:
            sql += " AND timestamp >= ?"
            params.append(float(since))
        sql += " ORDER BY timestamp DESC LIMIT ?"
        params.append(int(limit))
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(sql, params)
            rows = cur.fetchall()
        return [Event.from_row(row) for row in rows]

    def replay_to_state(self, aggregate_id: str) -> Dict[str, Any]:
        state: Dict[str, Any] = {
            "aggregate_id": aggregate_id,
            "status": "unknown",
            "completed_steps": [],
            "tool_calls": [],
            "approvals": [],
            "memory": [],
            "security": [],
        }
        for event in self.get_aggregate_events(aggregate_id):
            payload = event.payload or {}
            et = event.event_type
            if et == EventType.TASK_RECEIVED:
                state["status"] = "pending"
                state["intent"] = payload.get("intent")
                state["session_id"] = payload.get("session_id")
                state["received_at"] = event.timestamp
            elif et == EventType.TASK_PLANNED:
                state["status"] = payload.get("status", state.get("status", "planned"))
                state["plan"] = payload.get("steps", payload.get("plan", []))
                state["planned_at"] = event.timestamp
            elif et == EventType.TASK_STEP_STARTED:
                state.setdefault("started_steps", []).append(payload)
            elif et == EventType.TASK_STEP_COMPLETED:
                state["completed_steps"].append(payload.get("step") or payload.get("name") or payload)
            elif et == EventType.TASK_STEP_FAILED:
                state.setdefault("failed_steps", []).append(payload)
                state["last_error"] = payload.get("error")
            elif et == EventType.TOOL_INVOKED:
                state["tool_calls"].append({"status": "invoked", **payload})
            elif et == EventType.TOOL_SUCCEEDED:
                state["tool_calls"].append({"status": "succeeded", **payload})
            elif et == EventType.TOOL_FAILED:
                state["tool_calls"].append({"status": "failed", **payload})
                state["last_error"] = payload.get("error")
            elif et == EventType.APPROVAL_REQUESTED:
                state["approvals"].append({"status": "requested", **payload})
            elif et == EventType.APPROVAL_GRANTED:
                state["approvals"].append({"status": "granted", **payload})
            elif et == EventType.APPROVAL_DENIED:
                state["approvals"].append({"status": "denied", **payload})
            elif et in {
                EventType.SECURITY_DECISION_MADE,
                EventType.PROMPT_BLOCKED,
                EventType.SECRET_REDACTED,
                EventType.CLOUD_ESCALATION_DENIED,
                EventType.CLOUD_ESCALATION_APPROVED,
                EventType.SANDBOX_VIOLATION,
                EventType.TOKEN_ISSUED,
                EventType.TOKEN_REVOKED,
            }:
                state["security"].append(
                    {
                        "event_type": et.value,
                        "timestamp": event.timestamp,
                        **payload,
                    }
                )
            elif et == EventType.MEMORY_STORED:
                state["memory"].append(payload)
            elif et == EventType.FEEDBACK_RECEIVED:
                state["feedback"] = payload
            elif et == EventType.TASK_COMPLETED:
                state["status"] = "completed"
                state["completed_at"] = event.timestamp
                state["result"] = payload.get("result", payload.get("output"))
                if "confidence" in payload:
                    state["confidence"] = payload["confidence"]
            elif et == EventType.TASK_CANCELLED:
                state["status"] = "cancelled"
                state["cancelled_at"] = event.timestamp
                state["reason"] = payload.get("reason")
            elif et == EventType.TASK_STEP_FAILED:
                state["status"] = "failed"
            elif et in {EventType.AGENT_FAILED, EventType.TASK_FAILED}:
                state["status"] = "failed"
                state["error"] = payload.get("error")
        return state


_event_store: Optional[EventStore] = None


def get_event_store(db_path: str | Path | None = None) -> EventStore:
    global _event_store
    if _event_store is None:
        _event_store = EventStore(db_path=db_path)
    return _event_store
