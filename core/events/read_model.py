from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path
from threading import RLock
from typing import Any, Dict, List, Optional

from core.events.event_store import Event, EventStore, EventType, get_event_store
from core.observability.logger import get_structured_logger

slog = get_structured_logger("read_model")


def _default_db_path() -> Path:
    return Path(os.path.expanduser("~/.elyan/events.db")).expanduser()


class RunReadModel:
    def __init__(self, event_store: EventStore | None = None, db_path: str | Path | None = None):
        self.event_store = event_store or get_event_store(db_path)
        self.db_path = Path(db_path or self.event_store.db_path or _default_db_path()).expanduser()
        self._lock = RLock()
        self._conn = self.event_store.connection
        self._conn.row_factory = sqlite3.Row
        self._init_db()
        self.event_store.add_append_listener(self.on_event)

    def _init_db(self) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS runs_summary (
                    run_id TEXT PRIMARY KEY,
                    session_id TEXT,
                    status TEXT,
                    intent TEXT,
                    started_at REAL,
                    completed_at REAL,
                    step_count INTEGER DEFAULT 0,
                    tool_call_count INTEGER DEFAULT 0,
                    approval_required INTEGER DEFAULT 0,
                    error_message TEXT
                )
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_runs_summary_session ON runs_summary(session_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_runs_summary_status ON runs_summary(status)")
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS tool_stats (
                    tool_name TEXT PRIMARY KEY,
                    total_calls INTEGER DEFAULT 0,
                    success_count INTEGER DEFAULT 0,
                    failure_count INTEGER DEFAULT 0,
                    avg_latency_ms REAL DEFAULT 0,
                    last_used REAL
                )
                """
            )
            self._conn.commit()

    def on_event(self, event: Event) -> None:
        with self._lock:
            cur = self._conn.cursor()
            payload = event.payload or {}
            if event.event_type == EventType.TASK_RECEIVED:
                cur.execute(
                    """
                    INSERT OR IGNORE INTO runs_summary (
                        run_id, session_id, status, intent, started_at, approval_required
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.aggregate_id,
                        payload.get("session_id"),
                        "pending",
                        payload.get("intent"),
                        payload.get("started_at", event.timestamp),
                        int(bool(payload.get("approval_required", False))),
                    ),
                )
            elif event.event_type == EventType.TASK_PLANNED:
                steps = payload.get("steps")
                step_count = len(steps) if isinstance(steps, list) else int(payload.get("step_count", 0) or 0)
                cur.execute(
                    """
                    UPDATE runs_summary
                    SET status = COALESCE(?, status),
                        step_count = MAX(step_count, ?)
                    WHERE run_id = ?
                    """,
                    (payload.get("status"), step_count, event.aggregate_id),
                )
            elif event.event_type == EventType.TASK_STEP_COMPLETED:
                cur.execute(
                    """
                    UPDATE runs_summary
                    SET step_count = step_count + 1,
                        tool_call_count = tool_call_count + ?
                    WHERE run_id = ?
                    """,
                    (int(payload.get("tool_calls", 0) or 0), event.aggregate_id),
                )
            elif event.event_type == EventType.TASK_COMPLETED:
                cur.execute(
                    """
                    UPDATE runs_summary
                    SET status = ?,
                        completed_at = ?,
                        error_message = NULL
                    WHERE run_id = ?
                    """,
                    ("completed", event.timestamp, event.aggregate_id),
                )
            elif event.event_type == EventType.TASK_FAILED:
                cur.execute(
                    """
                    UPDATE runs_summary
                    SET status = ?, completed_at = ?, error_message = ?
                    WHERE run_id = ?
                    """,
                    ("failed", event.timestamp, payload.get("error"), event.aggregate_id),
                )
            elif event.event_type == EventType.TASK_CANCELLED:
                cur.execute(
                    """
                    UPDATE runs_summary
                    SET status = ?, completed_at = ?, error_message = ?
                    WHERE run_id = ?
                    """,
                    ("cancelled", event.timestamp, payload.get("reason"), event.aggregate_id),
                )
            elif event.event_type == EventType.TASK_STEP_FAILED or event.event_type == EventType.TASK_COMPLETED:
                if payload.get("error"):
                    cur.execute(
                        """
                        UPDATE runs_summary
                        SET error_message = ?
                        WHERE run_id = ?
                        """,
                        (payload.get("error"), event.aggregate_id),
                    )
            elif event.event_type in {EventType.TOOL_SUCCEEDED, EventType.TOOL_FAILED}:
                tool_name = str(payload.get("tool_name") or payload.get("tool") or "").strip()
                if tool_name:
                    latency = float(payload.get("latency_ms") or 0.0)
                    self._update_tool_stats(cur, tool_name, success=event.event_type == EventType.TOOL_SUCCEEDED, latency_ms=latency)
                    cur.execute(
                        """
                        UPDATE runs_summary
                        SET tool_call_count = tool_call_count + 1
                        WHERE run_id = ?
                        """,
                        (event.aggregate_id,),
                    )
            elif event.event_type == EventType.APPROVAL_REQUESTED:
                cur.execute(
                    """
                    UPDATE runs_summary
                    SET approval_required = 1
                    WHERE run_id = ?
                    """,
                    (event.aggregate_id,),
                )
            self._conn.commit()

    def _update_tool_stats(self, cur: sqlite3.Cursor, tool_name: str, *, success: bool, latency_ms: float) -> None:
        cur.execute("SELECT total_calls, success_count, failure_count, avg_latency_ms, last_used FROM tool_stats WHERE tool_name = ?", (tool_name,))
        row = cur.fetchone()
        now = time.time()
        if row is None:
            cur.execute(
                """
                INSERT INTO tool_stats (
                    tool_name, total_calls, success_count, failure_count, avg_latency_ms, last_used
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    tool_name,
                    1,
                    1 if success else 0,
                    0 if success else 1,
                    float(latency_ms or 0.0),
                    now,
                ),
            )
            return
        total = int(row["total_calls"] or 0) + 1
        success_count = int(row["success_count"] or 0) + (1 if success else 0)
        failure_count = int(row["failure_count"] or 0) + (0 if success else 1)
        avg_latency = float(row["avg_latency_ms"] or 0.0)
        avg_latency = (avg_latency * (total - 1) + float(latency_ms or 0.0)) / max(total, 1)
        cur.execute(
            """
            UPDATE tool_stats
            SET total_calls = ?, success_count = ?, failure_count = ?, avg_latency_ms = ?, last_used = ?
            WHERE tool_name = ?
            """,
            (total, success_count, failure_count, avg_latency, now, tool_name),
        )

    def get_recent_runs(self, limit: int = 20, status: str | None = None) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM runs_summary"
        params: list[Any] = []
        if status:
            sql += " WHERE status = ?"
            params.append(status)
        sql += " ORDER BY COALESCE(completed_at, started_at) DESC, started_at DESC LIMIT ?"
        params.append(int(limit))
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(sql, params)
            rows = cur.fetchall()
        return [dict(row) for row in rows]

    def get_tool_performance(self) -> List[Dict[str, Any]]:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                SELECT tool_name, total_calls, success_count, failure_count, avg_latency_ms, last_used
                FROM tool_stats
                WHERE total_calls > 5
                ORDER BY (CAST(success_count AS REAL) / CASE WHEN total_calls = 0 THEN 1 ELSE total_calls END) DESC,
                         total_calls DESC
                """
            )
            rows = cur.fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            total = max(int(row["total_calls"] or 0), 1)
            success_count = int(row["success_count"] or 0)
            result.append(
                {
                    "tool_name": row["tool_name"],
                    "total_calls": int(row["total_calls"] or 0),
                    "success_count": success_count,
                    "failure_count": int(row["failure_count"] or 0),
                    "success_rate": success_count / total,
                    "avg_latency_ms": float(row["avg_latency_ms"] or 0.0),
                    "last_used": float(row["last_used"] or 0.0),
                }
            )
        return result

    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("SELECT * FROM runs_summary WHERE run_id = ?", (run_id,))
            row = cur.fetchone()
        return dict(row) if row else None


_run_read_model: Optional[RunReadModel] = None


def get_run_read_model(event_store: EventStore | None = None) -> RunReadModel:
    global _run_read_model
    if _run_read_model is None:
        _run_read_model = RunReadModel(event_store=event_store)
    return _run_read_model
