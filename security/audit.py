"""
Operation Auditing and Logging

Provides comprehensive audit trail for all operations:
- Detailed operation logging
- Success/failure tracking
- Resource usage monitoring
- Security event logging
"""

import sqlite3
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List
from utils.logger import get_logger

logger = get_logger("security.audit")


class AuditLogger:
    """
    Comprehensive audit logging system
    """
    
    def __init__(self, db_path: str = None):
        if db_path is None:
            config_dir = Path.home() / ".config" / "cdacs-bot"
            try:
                config_dir.mkdir(parents=True, exist_ok=True)
                db_path = str(config_dir / "audit.db")
            except Exception:
                fallback_dir = Path.cwd() / ".elyan_audit"
                fallback_dir.mkdir(parents=True, exist_ok=True)
                db_path = str(fallback_dir / "audit.db")
        
        self.db_path = db_path
        self.conn = None
        self._initialize_db()
    
    def _initialize_db(self):
        """Initialize audit database"""
        try:
            self.conn = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
            try:
                self.conn.execute("PRAGMA journal_mode=WAL")
            except sqlite3.OperationalError:
                pass  # WAL mode not available if DB is in use, timeout handles concurrency
            
            cursor = self.conn.cursor()
            
            # Operations audit table
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
            
            # Security events table
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
            
            # Resource usage table
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
            
            # Create indexes
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_user_time ON audit_log(user_id, timestamp)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_operation ON audit_log(operation)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_security_time ON security_events(timestamp)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_security_severity ON security_events(severity)")
            
            self.conn.commit()
            logger.info(f"Audit database initialized at {self.db_path}")
        
        except Exception as e:
            logger.error(f"Error initializing audit database: {e}")
            raise
    
    def log_action(self, user_id: int = None, action: str = None,
                   details: Dict[str, Any] = None, success: bool = True):
        """
        Simple action logging (wrapper for log_operation)

        Args:
            user_id: User ID
            action: Action type
            details: Action details
            success: Success status
        """
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
        """
        Log an operation

        Args:
            user_id: User ID
            operation: Operation type
            action: Specific action
            params: Operation parameters
            result: Operation result
            success: Success status
            duration: Duration in seconds
            risk_level: Risk level
            approved: Whether operation was approved

        Returns:
            Log entry ID
        """
        try:
            cursor = self.conn.cursor()

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

            self.conn.commit()
            return cursor.lastrowid

        except Exception as e:
            logger.error(f"Error logging operation: {e}")
            return -1
    
    def log_security_event(self, event_type: str, severity: str,
                          description: str, user_id: int = None,
                          details: Dict[str, Any] = None, source: str = None):
        """
        Log a security event
        
        Args:
            event_type: Type of event (e.g., "unauthorized_access", "dangerous_operation")
            severity: Severity level (low, medium, high, critical)
            description: Event description
            user_id: User ID (if applicable)
            details: Additional details
            source: Event source
        """
        try:
            cursor = self.conn.cursor()
            
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
            
            self.conn.commit()
            logger.warning(f"Security event: {severity.upper()} - {event_type} - {description}")
        
        except Exception as e:
            logger.error(f"Error logging security event: {e}")
    
    def get_operation_history(self, user_id: int = None, operation: str = None,
                             limit: int = 100) -> List[Dict]:
        """Get operation history"""
        try:
            cursor = self.conn.cursor()
            
            query = "SELECT * FROM audit_log WHERE 1=1"
            params = []
            
            if user_id:
                query += " AND user_id = ?"
                params.append(user_id)
            
            if operation:
                query += " AND operation = ?"
                params.append(operation)
            
            query += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            
            return [dict(row) for row in rows]
        
        except Exception as e:
            logger.error(f"Error getting operation history: {e}")
            return []
    
    def get_security_events(self, severity: str = None, limit: int = 100) -> List[Dict]:
        """Get security events"""
        try:
            cursor = self.conn.cursor()
            
            query = "SELECT * FROM security_events WHERE 1=1"
            params = []
            
            if severity:
                query += " AND severity = ?"
                params.append(severity)
            
            query += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            
            return [dict(row) for row in rows]
        
        except Exception as e:
            logger.error(f"Error getting security events: {e}")
            return []
    
    def get_statistics(self, user_id: int = None) -> Dict[str, Any]:
        """Get audit statistics"""
        try:
            cursor = self.conn.cursor()
            
            stats = {}
            
            # Total operations
            query = "SELECT COUNT(*) as count FROM audit_log"
            params = []
            if user_id:
                query += " WHERE user_id = ?"
                params.append(user_id)
            
            cursor.execute(query, params)
            stats["total_operations"] = cursor.fetchone()["count"]
            
            # Success rate
            query = "SELECT COUNT(*) as count FROM audit_log WHERE success = 1"
            if user_id:
                query += " AND user_id = ?"
            
            cursor.execute(query, params)
            stats["successful_operations"] = cursor.fetchone()["count"]
            
            stats["success_rate"] = (
                stats["successful_operations"] / stats["total_operations"] * 100
                if stats["total_operations"] > 0 else 0
            )
            
            # Security events by severity
            cursor.execute("""
                SELECT severity, COUNT(*) as count
                FROM security_events
                GROUP BY severity
            """)
            stats["security_events_by_severity"] = {
                row["severity"]: row["count"]
                for row in cursor.fetchall()
            }
            
            # Most common operations
            query = """
                SELECT operation, COUNT(*) as count
                FROM audit_log
            """
            if user_id:
                query += " WHERE user_id = ?"
            query += " GROUP BY operation ORDER BY count DESC LIMIT 10"
            
            cursor.execute(query, params)
            stats["most_common_operations"] = [
                {"operation": row["operation"], "count": row["count"]}
                for row in cursor.fetchall()
            ]
            
            return stats
        
        except Exception as e:
            logger.error(f"Error getting statistics: {e}")
            return {}
    
    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()


# Global instance
_audit_logger = None


def get_audit_logger() -> AuditLogger:
    """Get or create global audit logger"""
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = AuditLogger()
    return _audit_logger
