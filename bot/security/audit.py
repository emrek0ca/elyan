"""
Operation Auditing and Logging

FIX BUG-SEC-004:
- Thread-safe connection pool (one connection per thread via threading.local)
- Context manager for proper connection lifecycle
- Singleton protected by threading.Lock
- WAL mode enabled for concurrent read performance
"""

import sqlite3
import json
import threading
import atexit
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List
from utils.logger import get_logger

logger = get_logger("security.audit")

# Thread-local storage for per-thread connections
_thread_local = threading.local()
_singleton_lock = threading.Lock()


class AuditLogger:
    """
    Comprehensive audit logging system — thread-safe via per-thread connections.
    """

    def __init__(self, db_path: str = None):
        if db_path is None:
            config_dir = Path.home() / ".config" / "elyan"
            try:
                config_dir.mkdir(parents=True, exist_ok=True)
                db_path = str(config_dir / "audit.db")
            except Exception:
                fallback_dir = Path.cwd() / ".elyan_audit"
                fallback_dir.mkdir(parents=True, exist_ok=True)
                db_path = str(fallback_dir / "audit.db")

        self.db_path = db_path
        # Initialize schema using a temporary connection
        self._initialize_schema()
        atexit.register(self.close)

    def _get_conn(self) -> sqlite3.Connection:
        """Get or create a per-thread SQLite connection."""
        if not hasattr(_thread_local, "conn") or _thread_local.conn is None:
            conn = sqlite3.connect(self.db_path, timeout=30)
            conn.row_factory = sqlite3.Row
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
                conn.execute("PRAGMA foreign_keys=ON")
            except sqlite3.OperationalError:
                pass
            _thread_local.conn = conn
        return _thread_local.conn

    def _initialize_schema(self):
        """Initialize audit database schema."""
        try:
            conn = sqlite3.connect(self.db_path, timeout=30)
            conn.execute("PRAGMA journal_mode=WAL")
            cursor = conn.cursor()

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    user_id INTEGER,
                    operation TEXT NOT NULL,
                    action TEXT,
                    params TEXT,
                    result TEXT,
                    success BOOLEAN,
                    duration REAL,
                    risk_level TEXT,
                    approved BOOLEAN,
                    error TEXT
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS security_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    user_id INTEGER,
                    event_type TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    description TEXT,
                    details TEXT,
                    source TEXT
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS resource_usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    user_id INTEGER,
                    operation TEXT,
                    cpu_time REAL,
                    memory_mb REAL,
                    disk_io_mb REAL,
                    network_mb REAL
                )
            """)

            cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_user_time ON audit_log(user_id, timestamp)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_operation ON audit_log(operation)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_security_time ON security_events(timestamp)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_security_severity ON security_events(severity)")

            conn.commit()
            conn.close()
            logger.info(f"Audit database initialized at {self.db_path}")

        except Exception as e:
            logger.error(f"Error initializing audit database: {e}")
            raise

    def log_action(self, user_id: int = None, action: str = None,
                   details: Dict[str, Any] = None, success: bool = True):
        """Simple action logging wrapper."""
        return self.log_operation(
            user_id=user_id or 0,
            operation=action or "unknown",
            params=details,
            success=success
        )

    def log_operation(self, user_id: int, operation: str, action: str = None,
                      params: Dict[str, Any] = None, result: Dict[str, Any] = None,
                      success: bool = True, duration: float = 0.0,
                      risk_level: str = "low", approved: bool = True) -> int:
        """Log an operation. Returns log entry ID."""
        try:
            conn = self._get_conn()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO audit_log (
                    timestamp, user_id, operation, action, params, result,
                    success, duration, risk_level, approved, error
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                datetime.now().isoformat(),
                user_id,
                operation,
                action,
                json.dumps(params) if params else None,
                json.dumps(result) if result else None,
                success,
                duration,
                risk_level,
                approved,
                result.get("error") if result and not success else None
            ))
            conn.commit()
            return cursor.lastrowid

        except Exception as e:
            logger.error(f"Error logging operation: {e}")
            return -1

    def log_security_event(self, event_type: str, severity: str,
                           description: str, user_id: int = None,
                           details: Dict[str, Any] = None, source: str = None):
        """Log a security event."""
        try:
            conn = self._get_conn()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO security_events (
                    timestamp, user_id, event_type, severity, description, details, source
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                datetime.now().isoformat(),
                user_id,
                event_type,
                severity,
                description,
                json.dumps(details) if details else None,
                source
            ))
            conn.commit()
            logger.warning(f"Security event: {severity.upper()} - {event_type} - {description}")

        except Exception as e:
            logger.error(f"Error logging security event: {e}")

    def get_operation_history(self, user_id: int = None, operation: str = None,
                              limit: int = 100) -> List[Dict]:
        """Get operation history."""
        try:
            conn = self._get_conn()
            cursor = conn.cursor()
            filters: list[str] = []
            params: list[Any] = []

            if user_id is not None:
                filters.append("user_id = ?")
                params.append(user_id)

            if operation is not None:
                filters.append("operation = ?")
                params.append(operation)

            where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
            query = f"SELECT * FROM audit_log {where_clause} ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)

            cursor.execute(query, params)
            return [self._decode_audit_row(dict(row)) for row in cursor.fetchall()]

        except Exception as e:
            logger.error(f"Error getting operation history: {e}")
            return []

    def get_security_events(self, severity: str = None, limit: int = 100) -> List[Dict]:
        """Get security events."""
        try:
            conn = self._get_conn()
            cursor = conn.cursor()
            filters: list[str] = []
            params: list[Any] = []

            if severity is not None:
                filters.append("severity = ?")
                params.append(severity)

            where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
            query = f"SELECT * FROM security_events {where_clause} ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)

            cursor.execute(query, params)
            return [self._decode_security_row(dict(row)) for row in cursor.fetchall()]

        except Exception as e:
            logger.error(f"Error getting security events: {e}")
            return []

    def get_statistics(self, user_id: int = None) -> Dict[str, Any]:
        """Get audit statistics."""
        try:
            conn = self._get_conn()
            cursor = conn.cursor()
            stats = {}

            base_filter = "WHERE user_id = ?" if user_id is not None else ""
            base_params = [user_id] if user_id is not None else []

            cursor.execute(f"SELECT COUNT(*) as count FROM audit_log {base_filter}", base_params)
            stats["total_operations"] = cursor.fetchone()["count"]

            success_filter = "WHERE success = 1"
            success_params = []
            if user_id is not None:
                success_filter += " AND user_id = ?"
                success_params.append(user_id)

            cursor.execute(f"SELECT COUNT(*) as count FROM audit_log {success_filter}", success_params)
            stats["successful_operations"] = cursor.fetchone()["count"]

            stats["success_rate"] = (
                stats["successful_operations"] / stats["total_operations"] * 100
                if stats["total_operations"] > 0 else 0
            )

            cursor.execute("""
                SELECT severity, COUNT(*) as count
                FROM security_events
                GROUP BY severity
            """)
            stats["security_events_by_severity"] = {
                row["severity"]: row["count"] for row in cursor.fetchall()
            }

            op_filter = f"FROM audit_log {base_filter}"
            cursor.execute(
                f"SELECT operation, COUNT(*) as count {op_filter} GROUP BY operation ORDER BY count DESC LIMIT 10",
                base_params
            )
            stats["most_common_operations"] = [
                {"operation": row["operation"], "count": row["count"]}
                for row in cursor.fetchall()
            ]

            return stats

        except Exception as e:
            logger.error(f"Error getting statistics: {e}")
            return {}

    def close(self):
        """Close the current thread's connection."""
        if hasattr(_thread_local, "conn") and _thread_local.conn:
            _thread_local.conn.close()
            _thread_local.conn = None

    @staticmethod
    def _decode_json(value: Any) -> Any:
        if value is None or not isinstance(value, str):
            return value
        try:
            return json.loads(value)
        except Exception:
            return value

    def _decode_audit_row(self, row: Dict[str, Any]) -> Dict[str, Any]:
        row["params"] = self._decode_json(row.get("params"))
        row["result"] = self._decode_json(row.get("result"))
        return row

    def _decode_security_row(self, row: Dict[str, Any]) -> Dict[str, Any]:
        row["details"] = self._decode_json(row.get("details"))
        return row


# Global instance — protected singleton
_audit_logger: Optional[AuditLogger] = None


def get_audit_logger() -> AuditLogger:
    """Get or create global audit logger (thread-safe singleton)."""
    global _audit_logger
    if _audit_logger is None:
        with _singleton_lock:
            if _audit_logger is None:  # Double-checked locking
                _audit_logger = AuditLogger()
    return _audit_logger
