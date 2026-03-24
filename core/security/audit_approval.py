"""
Approval Action Audit Trail

Logs all approval system actions:
- Request creation
- Request resolution (approval/denial)
- Bulk operations
- Risk assessments
"""

import time
import json
import sqlite3
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict
from core.observability.logger import get_structured_logger
from core.security.encrypted_vault import get_encrypted_vault

slog = get_structured_logger("audit_approval")


@dataclass
class ApprovalAuditEntry:
    """Single audit trail entry for approval action."""
    entry_id: str
    timestamp: float
    action_type: str  # "request_created", "request_resolved", "bulk_resolve"
    request_id: str
    user_id: str
    session_id: str
    action_data: Dict[str, Any]
    risk_level: str
    approved: Optional[bool] = None
    resolver_id: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict."""
        return asdict(self)


class ApprovalAuditLog:
    """Audit trail for approval system actions."""

    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize approval audit log.

        Args:
            db_path: Path to SQLite database. If None, uses ~/.elyan/audit_approval.db
        """
        if db_path is None:
            audit_dir = Path.home() / ".elyan" / "audit"
            audit_dir.mkdir(parents=True, exist_ok=True)
            db_path = str(audit_dir / "approval.db")

        self.db_path = db_path
        self._vault = get_encrypted_vault()
        self._initialize_schema()

    def _get_conn(self) -> sqlite3.Connection:
        """Get database connection."""
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
        except sqlite3.OperationalError:
            pass
        return conn

    def _initialize_schema(self):
        """Initialize database schema."""
        try:
            conn = self._get_conn()
            cursor = conn.cursor()

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS approval_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entry_id TEXT UNIQUE NOT NULL,
                    timestamp REAL NOT NULL,
                    action_type TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    action_data TEXT NOT NULL,
                    risk_level TEXT,
                    approved INTEGER,
                    resolver_id TEXT,
                    error TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Index for fast queries
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_request_id
                ON approval_audit(request_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_timestamp
                ON approval_audit(timestamp DESC)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_user_id
                ON approval_audit(user_id)
            """)

            conn.commit()
            conn.close()

        except Exception as e:
            slog.log_event("schema_init_error", {
                "error": str(e)
            }, level="error")
            raise

    def log_request_created(
        self,
        entry_id: str,
        request_id: str,
        user_id: str,
        session_id: str,
        action_type: str,
        risk_level: str,
        action_data: Dict[str, Any]
    ) -> bool:
        """Log approval request creation."""
        try:
            entry = ApprovalAuditEntry(
                entry_id=entry_id,
                timestamp=time.time(),
                action_type="request_created",
                request_id=request_id,
                user_id=user_id,
                session_id=session_id,
                action_data=action_data,
                risk_level=risk_level
            )

            # Encrypt sensitive data
            encrypted_data = self._vault.encrypt(
                action_data,
                context="approval_action"
            )

            return self._insert_entry(
                entry_id=entry.entry_id,
                timestamp=entry.timestamp,
                action_type=entry.action_type,
                request_id=entry.request_id,
                user_id=entry.user_id,
                session_id=entry.session_id,
                action_data=json.dumps(encrypted_data),
                risk_level=entry.risk_level
            )

        except Exception as e:
            slog.log_event("log_request_error", {
                "error": str(e),
                "request_id": request_id
            }, level="error")
            return False

    def log_request_resolved(
        self,
        entry_id: str,
        request_id: str,
        approved: bool,
        resolver_id: str,
        user_id: str,
        session_id: str,
        risk_level: str
    ) -> bool:
        """Log approval request resolution."""
        try:
            entry = ApprovalAuditEntry(
                entry_id=entry_id,
                timestamp=time.time(),
                action_type="request_resolved",
                request_id=request_id,
                user_id=user_id,
                session_id=session_id,
                action_data={"decision": "approved" if approved else "denied"},
                risk_level=risk_level,
                approved=approved,
                resolver_id=resolver_id
            )

            return self._insert_entry(
                entry_id=entry.entry_id,
                timestamp=entry.timestamp,
                action_type=entry.action_type,
                request_id=entry.request_id,
                user_id=entry.user_id,
                session_id=entry.session_id,
                action_data=json.dumps(entry.action_data),
                risk_level=entry.risk_level,
                approved=1 if approved else 0,
                resolver_id=resolver_id
            )

        except Exception as e:
            slog.log_event("log_resolve_error", {
                "error": str(e),
                "request_id": request_id
            }, level="error")
            return False

    def log_bulk_resolve(
        self,
        entry_id: str,
        request_ids: List[str],
        approved: bool,
        resolver_id: str,
        user_id: str,
        session_id: str
    ) -> bool:
        """Log bulk approval resolution."""
        try:
            action_data = {
                "request_ids": request_ids,
                "count": len(request_ids)
            }

            entry = ApprovalAuditEntry(
                entry_id=entry_id,
                timestamp=time.time(),
                action_type="bulk_resolve",
                request_id=",".join(request_ids[:3]) + ("..." if len(request_ids) > 3 else ""),
                user_id=user_id,
                session_id=session_id,
                action_data=action_data,
                risk_level="high",
                approved=approved,
                resolver_id=resolver_id
            )

            encrypted_data = self._vault.encrypt(
                action_data,
                context="approval_bulk"
            )

            return self._insert_entry(
                entry_id=entry.entry_id,
                timestamp=entry.timestamp,
                action_type=entry.action_type,
                request_id=entry.request_id,
                user_id=entry.user_id,
                session_id=entry.session_id,
                action_data=json.dumps(encrypted_data),
                risk_level="high",
                approved=1 if approved else 0,
                resolver_id=resolver_id
            )

        except Exception as e:
            slog.log_event("log_bulk_resolve_error", {
                "error": str(e),
                "count": len(request_ids)
            }, level="error")
            return False

    def _insert_entry(
        self,
        entry_id: str,
        timestamp: float,
        action_type: str,
        request_id: str,
        user_id: str,
        session_id: str,
        action_data: str,
        risk_level: str,
        approved: Optional[int] = None,
        resolver_id: Optional[str] = None,
        error: Optional[str] = None
    ) -> bool:
        """Insert audit entry into database."""
        try:
            conn = self._get_conn()
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO approval_audit
                (entry_id, timestamp, action_type, request_id, user_id, session_id,
                 action_data, risk_level, approved, resolver_id, error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                entry_id, timestamp, action_type, request_id, user_id, session_id,
                action_data, risk_level, approved, resolver_id, error
            ))

            conn.commit()
            conn.close()
            return True

        except sqlite3.IntegrityError:
            slog.log_event("duplicate_entry", {
                "entry_id": entry_id
            }, level="warning")
            return False
        except Exception as e:
            slog.log_event("insert_error", {
                "error": str(e)
            }, level="error")
            return False

    def get_entries(
        self,
        request_id: Optional[str] = None,
        user_id: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get audit entries with optional filters."""
        try:
            conn = self._get_conn()
            cursor = conn.cursor()

            query = "SELECT * FROM approval_audit WHERE 1=1"
            params = []

            if request_id:
                query += " AND request_id = ?"
                params.append(request_id)

            if user_id:
                query += " AND user_id = ?"
                params.append(user_id)

            query += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)

            cursor.execute(query, params)
            rows = cursor.fetchall()
            conn.close()

            return [dict(row) for row in rows]

        except Exception as e:
            slog.log_event("get_entries_error", {
                "error": str(e)
            }, level="error")
            return []

    def get_stats(self) -> Dict[str, Any]:
        """Get audit trail statistics."""
        try:
            conn = self._get_conn()
            cursor = conn.cursor()

            # Total entries
            cursor.execute("SELECT COUNT(*) as count FROM approval_audit")
            total = cursor.fetchone()["count"]

            # By action type
            cursor.execute("""
                SELECT action_type, COUNT(*) as count
                FROM approval_audit GROUP BY action_type
            """)
            by_action = {row["action_type"]: row["count"] for row in cursor.fetchall()}

            # Approval rate
            cursor.execute("""
                SELECT COUNT(*) as total, SUM(CASE WHEN approved = 1 THEN 1 ELSE 0 END) as approved
                FROM approval_audit WHERE action_type = 'request_resolved'
            """)
            resolution = cursor.fetchone()
            approval_rate = 0
            if resolution["total"] > 0:
                approval_rate = (resolution["approved"] / resolution["total"]) * 100

            conn.close()

            return {
                "total_entries": total,
                "by_action_type": by_action,
                "approval_rate_percent": round(approval_rate, 2)
            }

        except Exception as e:
            slog.log_event("stats_error", {
                "error": str(e)
            }, level="error")
            return {}


# Singleton instance
_audit_log: Optional[ApprovalAuditLog] = None


def get_approval_audit_log(db_path: Optional[str] = None) -> ApprovalAuditLog:
    """Get or create approval audit log singleton."""
    global _audit_log
    if _audit_log is None:
        _audit_log = ApprovalAuditLog(db_path)
    return _audit_log
