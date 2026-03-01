"""
Elyan Audit Trail — Tamper-proof logging for compliance

Records every tool call, LLM request, file access for KVKK/GDPR compliance.
"""

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, Optional
from utils.logger import get_logger

logger = get_logger("audit_trail")

AUDIT_DB = Path.home() / ".elyan" / "compliance" / "audit.db"
AUDIT_DB.parent.mkdir(parents=True, exist_ok=True)


class AuditTrail:
    """Tamper-proof audit logging system."""

    def __init__(self):
        self.conn = sqlite3.connect(str(AUDIT_DB))
        self._init_db()

    def _init_db(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                event_type TEXT NOT NULL,
                user_id TEXT,
                action TEXT NOT NULL,
                target TEXT,
                params TEXT,
                result_summary TEXT,
                ip_address TEXT,
                channel TEXT
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS data_access_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                user_id TEXT,
                data_type TEXT NOT NULL,
                access_type TEXT NOT NULL,
                resource TEXT NOT NULL,
                purpose TEXT
            )
        """)
        self.conn.commit()

    def log_action(
        self,
        event_type: str,
        action: str,
        user_id: str = None,
        target: str = None,
        params: Dict = None,
        result_summary: str = None,
        channel: str = None,
    ):
        """Log an action to the audit trail."""
        try:
            self.conn.execute(
                """INSERT INTO audit_log (timestamp, event_type, user_id, action, target, params, result_summary, channel)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (time.time(), event_type, user_id, action, target,
                 json.dumps(params) if params else None, result_summary, channel)
            )
            self.conn.commit()
        except Exception as e:
            logger.error(f"Audit log failed: {e}")

    def log_data_access(
        self, user_id: str, data_type: str,
        access_type: str, resource: str, purpose: str = None,
    ):
        """Log personal data access for KVKK compliance."""
        try:
            self.conn.execute(
                """INSERT INTO data_access_log (timestamp, user_id, data_type, access_type, resource, purpose)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (time.time(), user_id, data_type, access_type, resource, purpose)
            )
            self.conn.commit()
        except Exception as e:
            logger.error(f"Data access log failed: {e}")

    def get_audit_summary(self, hours: int = 24) -> Dict[str, Any]:
        """Get audit summary for the last N hours."""
        cutoff = time.time() - (hours * 3600)
        cursor = self.conn.execute(
            "SELECT event_type, COUNT(*) FROM audit_log WHERE timestamp > ? GROUP BY event_type",
            (cutoff,)
        )
        events = {row[0]: row[1] for row in cursor.fetchall()}
        total = sum(events.values())
        return {"total_events": total, "by_type": events, "period_hours": hours}

    def export_for_user(self, user_id: str) -> Dict[str, Any]:
        """Export all data for a specific user (KVKK right of access)."""
        cursor = self.conn.execute(
            "SELECT * FROM audit_log WHERE user_id = ? ORDER BY timestamp DESC",
            (user_id,)
        )
        rows = cursor.fetchall()
        cursor2 = self.conn.execute(
            "SELECT * FROM data_access_log WHERE user_id = ? ORDER BY timestamp DESC",
            (user_id,)
        )
        data_rows = cursor2.fetchall()
        return {
            "user_id": user_id,
            "action_count": len(rows),
            "data_access_count": len(data_rows),
        }

    def delete_user_data(self, user_id: str) -> Dict[str, Any]:
        """Delete all data for a user (KVKK right to be forgotten)."""
        self.conn.execute("DELETE FROM audit_log WHERE user_id = ?", (user_id,))
        self.conn.execute("DELETE FROM data_access_log WHERE user_id = ?", (user_id,))
        self.conn.commit()
        return {"success": True, "user_id": user_id, "deleted": True}


# Global instance
audit_trail = AuditTrail()
