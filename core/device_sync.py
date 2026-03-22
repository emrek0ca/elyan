from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from core.storage_paths import resolve_elyan_data_dir


def _now() -> float:
    return time.time()


def _safe_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


class DeviceSyncStore:
    def __init__(self, storage_root: Path | None = None):
        self.storage_root = Path(storage_root or (resolve_elyan_data_dir() / "device_sync")).expanduser()
        self.storage_root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.storage_root / "device_sync.sqlite3"
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS device_sessions (
                    session_key TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    device_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    active_request_id TEXT NOT NULL,
                    active_task_id TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    last_seen REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_device_sessions_user
                    ON device_sessions(user_id, updated_at DESC);

                CREATE TABLE IF NOT EXISTS sync_requests (
                    request_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    device_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    request_text TEXT NOT NULL,
                    request_class TEXT NOT NULL,
                    execution_path TEXT NOT NULL,
                    state TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_sync_requests_user
                    ON sync_requests(user_id, updated_at DESC);
                """
            )
            conn.commit()

    @staticmethod
    def _session_key(user_id: str, channel: str, device_id: str, session_id: str) -> str:
        return "::".join(
            [
                str(user_id or "local"),
                str(channel or "cli"),
                str(device_id or "primary"),
                str(session_id or "default"),
            ]
        )

    def touch_session(
        self,
        *,
        user_id: str,
        channel: str,
        device_id: str = "",
        session_id: str = "",
        status: str = "online",
        active_request_id: str = "",
        active_task_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        uid = str(user_id or "local")
        session_key = self._session_key(uid, channel, device_id, session_id)
        payload = {
            "session_key": session_key,
            "user_id": uid,
            "channel": str(channel or "cli"),
            "device_id": str(device_id or "primary"),
            "session_id": str(session_id or "default"),
            "status": str(status or "online"),
            "active_request_id": str(active_request_id or ""),
            "active_task_id": str(active_task_id or ""),
            "metadata": dict(metadata or {}),
            "last_seen": _now(),
            "updated_at": _now(),
        }
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO device_sessions(
                    session_key, user_id, channel, device_id, session_id, status,
                    active_request_id, active_task_id, metadata_json, last_seen, updated_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_key) DO UPDATE SET
                    status = excluded.status,
                    active_request_id = excluded.active_request_id,
                    active_task_id = excluded.active_task_id,
                    metadata_json = excluded.metadata_json,
                    last_seen = excluded.last_seen,
                    updated_at = excluded.updated_at
                """,
                (
                    payload["session_key"],
                    payload["user_id"],
                    payload["channel"],
                    payload["device_id"],
                    payload["session_id"],
                    payload["status"],
                    payload["active_request_id"],
                    payload["active_task_id"],
                    _safe_json(payload["metadata"]),
                    payload["last_seen"],
                    payload["updated_at"],
                ),
            )
            conn.commit()
        return payload

    def record_request(
        self,
        *,
        request_id: str,
        user_id: str,
        channel: str,
        request_text: str,
        request_class: str,
        execution_path: str,
        device_id: str = "",
        session_id: str = "",
        state: str = "routing",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = {
            "request_id": str(request_id or ""),
            "user_id": str(user_id or "local"),
            "channel": str(channel or "cli"),
            "device_id": str(device_id or "primary"),
            "session_id": str(session_id or "default"),
            "request_text": str(request_text or "").strip(),
            "request_class": str(request_class or "unknown"),
            "execution_path": str(execution_path or "deep"),
            "state": str(state or "routing"),
            "outcome": "",
            "metadata": dict(metadata or {}),
            "created_at": _now(),
            "updated_at": _now(),
        }
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sync_requests(
                    request_id, user_id, channel, device_id, session_id,
                    request_text, request_class, execution_path, state, outcome,
                    metadata_json, created_at, updated_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(request_id) DO UPDATE SET
                    request_class = excluded.request_class,
                    execution_path = excluded.execution_path,
                    state = excluded.state,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                (
                    payload["request_id"],
                    payload["user_id"],
                    payload["channel"],
                    payload["device_id"],
                    payload["session_id"],
                    payload["request_text"],
                    payload["request_class"],
                    payload["execution_path"],
                    payload["state"],
                    payload["outcome"],
                    _safe_json(payload["metadata"]),
                    payload["created_at"],
                    payload["updated_at"],
                ),
            )
            conn.commit()
        self.touch_session(
            user_id=payload["user_id"],
            channel=payload["channel"],
            device_id=payload["device_id"],
            session_id=payload["session_id"],
            status="online",
            active_request_id=payload["request_id"],
            active_task_id=str(payload["metadata"].get("task_id") or payload["metadata"].get("mission_id") or ""),
            metadata={"last_request_class": payload["request_class"], **payload["metadata"]},
        )
        return payload

    def record_stage(
        self,
        *,
        request_id: str,
        user_id: str,
        channel: str,
        state: str,
        device_id: str = "",
        session_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE sync_requests
                SET state = ?, metadata_json = ?, updated_at = ?
                WHERE request_id = ?
                """,
                (
                    str(state or "running"),
                    _safe_json(dict(metadata or {})),
                    _now(),
                    str(request_id or ""),
                ),
            )
            conn.commit()
        return self.touch_session(
            user_id=user_id,
            channel=channel,
            device_id=device_id,
            session_id=session_id,
            status="online",
            active_request_id=str(request_id or ""),
            active_task_id=str((metadata or {}).get("task_id") or (metadata or {}).get("mission_id") or ""),
            metadata={"state": str(state or "running"), **dict(metadata or {})},
        )

    def record_outcome(
        self,
        *,
        request_id: str,
        user_id: str,
        channel: str,
        final_outcome: str,
        success: bool,
        device_id: str = "",
        session_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        outcome = str(final_outcome or ("success" if success else "failed"))
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE sync_requests
                SET state = ?, outcome = ?, metadata_json = ?, updated_at = ?
                WHERE request_id = ?
                """,
                (
                    "completed" if success else "failed",
                    outcome,
                    _safe_json(dict(metadata or {})),
                    _now(),
                    str(request_id or ""),
                ),
            )
            conn.commit()
        return self.touch_session(
            user_id=user_id,
            channel=channel,
            device_id=device_id,
            session_id=session_id,
            status="online",
            active_request_id="",
            active_task_id="",
            metadata={"last_outcome": outcome, **dict(metadata or {})},
        )

    def get_user_snapshot(self, user_id: str, *, limit: int = 20) -> dict[str, Any]:
        uid = str(user_id or "local")
        with self._connect() as conn:
            session_rows = conn.execute(
                """
                SELECT * FROM device_sessions
                WHERE user_id = ?
                ORDER BY updated_at DESC
                """,
                (uid,),
            ).fetchall()
            request_rows = conn.execute(
                """
                SELECT * FROM sync_requests
                WHERE user_id = ?
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (uid, max(1, int(limit or 20))),
            ).fetchall()
        return {
            "user_id": uid,
            "devices": [self._load_session(row) for row in session_rows],
            "requests": [self._load_request(row) for row in request_rows],
        }

    def stats(self) -> dict[str, Any]:
        with self._connect() as conn:
            session_row = conn.execute("SELECT COUNT(*) AS cnt FROM device_sessions").fetchone()
            request_row = conn.execute("SELECT COUNT(*) AS cnt FROM sync_requests").fetchone()
            active_row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM sync_requests WHERE state IN ('routing', 'running', 'verifying', 'waiting_approval')"
            ).fetchone()
            user_row = conn.execute("SELECT COUNT(DISTINCT user_id) AS cnt FROM device_sessions").fetchone()
        return {
            "db_path": str(self.db_path),
            "sessions": int((session_row["cnt"] if session_row else 0) or 0),
            "tracked_requests": int((request_row["cnt"] if request_row else 0) or 0),
            "active_requests": int((active_row["cnt"] if active_row else 0) or 0),
            "users": int((user_row["cnt"] if user_row else 0) or 0),
        }

    def list_recent_sessions(self, *, limit: int = 10) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM device_sessions
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (max(1, int(limit or 10)),),
            ).fetchall()
        return [self._load_session(row) for row in rows]

    def list_recent_users(self, *, limit: int = 10) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT user_id, MAX(updated_at) AS updated_at, COUNT(*) AS session_count
                FROM device_sessions
                GROUP BY user_id
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (max(1, int(limit or 10)),),
            ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            uid = str(row["user_id"] or "").strip()
            if not uid:
                continue
            out.append(
                {
                    "user_id": uid,
                    "updated_at": float(row["updated_at"] or 0.0),
                    "session_count": int(row["session_count"] or 0),
                }
            )
        return out

    def delete_user(self, user_id: str) -> dict[str, Any]:
        uid = str(user_id or "local")
        with self._connect() as conn:
            session_row = conn.execute("SELECT COUNT(*) AS cnt FROM device_sessions WHERE user_id = ?", (uid,)).fetchone()
            request_row = conn.execute("SELECT COUNT(*) AS cnt FROM sync_requests WHERE user_id = ?", (uid,)).fetchone()
            conn.execute("DELETE FROM device_sessions WHERE user_id = ?", (uid,))
            conn.execute("DELETE FROM sync_requests WHERE user_id = ?", (uid,))
            conn.commit()
        return {
            "user_id": uid,
            "deleted_sessions": int((session_row["cnt"] if session_row else 0) or 0),
            "deleted_requests": int((request_row["cnt"] if request_row else 0) or 0),
        }

    @staticmethod
    def _load_session(row: sqlite3.Row) -> dict[str, Any]:
        try:
            metadata = json.loads(str(row["metadata_json"] or "{}"))
        except Exception:
            metadata = {}
        return {
            "session_key": str(row["session_key"] or ""),
            "user_id": str(row["user_id"] or ""),
            "channel": str(row["channel"] or ""),
            "device_id": str(row["device_id"] or ""),
            "session_id": str(row["session_id"] or ""),
            "status": str(row["status"] or ""),
            "active_request_id": str(row["active_request_id"] or ""),
            "active_task_id": str(row["active_task_id"] or ""),
            "metadata": metadata,
            "last_seen": float(row["last_seen"] or 0.0),
            "updated_at": float(row["updated_at"] or 0.0),
        }

    @staticmethod
    def _load_request(row: sqlite3.Row) -> dict[str, Any]:
        try:
            metadata = json.loads(str(row["metadata_json"] or "{}"))
        except Exception:
            metadata = {}
        return {
            "request_id": str(row["request_id"] or ""),
            "user_id": str(row["user_id"] or ""),
            "channel": str(row["channel"] or ""),
            "device_id": str(row["device_id"] or ""),
            "session_id": str(row["session_id"] or ""),
            "request_text": str(row["request_text"] or ""),
            "request_class": str(row["request_class"] or ""),
            "execution_path": str(row["execution_path"] or ""),
            "state": str(row["state"] or ""),
            "outcome": str(row["outcome"] or ""),
            "metadata": metadata,
            "created_at": float(row["created_at"] or 0.0),
            "updated_at": float(row["updated_at"] or 0.0),
        }


_store: DeviceSyncStore | None = None


def get_device_sync_store() -> DeviceSyncStore:
    global _store
    if _store is None:
        _store = DeviceSyncStore()
    return _store
