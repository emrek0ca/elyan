"""
Alerting System for elyan Bot Production
========================================
Real-time alerts for critical issues with multiple notification channels.

Features:
- Threshold-based alerting
- Multiple notification channels (log, email, Slack, PagerDuty)
- Alert deduplication
- Escalation policies
- Alert history and statistics
"""

import logging
import time
import sqlite3
import json
from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass, asdict
from enum import Enum
from datetime import datetime, timedelta
from pathlib import Path
import threading

logger = logging.getLogger(__name__)


class AlertSeverity(Enum):
    """Alert severity levels."""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    EMERGENCY = "emergency"


class AlertChannel(Enum):
    """Alert notification channels."""
    LOG = "log"
    EMAIL = "email"
    SLACK = "slack"
    PAGERDUTY = "pagerduty"


@dataclass
class AlertThreshold:
    """Alert threshold configuration."""
    metric_name: str
    operator: str  # ">", "<", "==", "!="
    threshold_value: float
    severity: str
    message_template: str
    enabled: bool = True
    cooldown_minutes: int = 5  # Min time between alerts

    def check(self, value: float) -> bool:
        """Check if metric exceeds threshold."""
        if self.operator == ">":
            return value > self.threshold_value
        elif self.operator == "<":
            return value < self.threshold_value
        elif self.operator == "==":
            return value == self.threshold_value
        elif self.operator == "!=":
            return value != self.threshold_value
        return False


@dataclass
class Alert:
    """Alert instance."""
    alert_id: str
    metric_name: str
    severity: str
    message: str
    value: float
    threshold: float
    timestamp: float
    resolved: bool = False
    resolved_at: Optional[float] = None
    acknowledgments: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


class AlertStore:
    """Stores alert history and state."""

    def __init__(self, db_path: str = "~/.elyan/alerts.db"):
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = str(self.db_path)
        self._init_db()

    def _init_db(self) -> None:
        """Initialize database."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS alerts (
                alert_id TEXT PRIMARY KEY,
                metric_name TEXT NOT NULL,
                severity TEXT NOT NULL,
                message TEXT NOT NULL,
                value REAL NOT NULL,
                threshold REAL NOT NULL,
                timestamp REAL NOT NULL,
                resolved BOOLEAN DEFAULT 0,
                resolved_at REAL,
                acknowledgments INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS alert_events (
                event_id TEXT PRIMARY KEY,
                alert_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                timestamp REAL NOT NULL,
                message TEXT,
                FOREIGN KEY (alert_id) REFERENCES alerts(alert_id)
            )
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_metric_name ON alerts(metric_name)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_severity ON alerts(severity)
        """)

        conn.commit()
        conn.close()

    def save_alert(self, alert: Alert) -> None:
        """Save an alert."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT OR REPLACE INTO alerts (
                alert_id, metric_name, severity, message, value, threshold,
                timestamp, resolved, resolved_at, acknowledgments
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            alert.alert_id,
            alert.metric_name,
            alert.severity,
            alert.message,
            alert.value,
            alert.threshold,
            alert.timestamp,
            alert.resolved,
            alert.resolved_at,
            alert.acknowledgments
        ))

        conn.commit()
        conn.close()

    def get_alert(self, alert_id: str) -> Optional[Alert]:
        """Get an alert by ID."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM alerts WHERE alert_id = ?", (alert_id,))
        row = cursor.fetchone()
        conn.close()

        if not row:
            return None

        return Alert(
            alert_id=row[0],
            metric_name=row[1],
            severity=row[2],
            message=row[3],
            value=row[4],
            threshold=row[5],
            timestamp=row[6],
            resolved=bool(row[7]),
            resolved_at=row[8],
            acknowledgments=row[9]
        )

    def get_active_alerts(self) -> List[Alert]:
        """Get all active (unresolved) alerts."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM alerts WHERE resolved = 0 ORDER BY timestamp DESC")
        rows = cursor.fetchall()
        conn.close()

        alerts = []
        for row in rows:
            alerts.append(Alert(
                alert_id=row[0],
                metric_name=row[1],
                severity=row[2],
                message=row[3],
                value=row[4],
                threshold=row[5],
                timestamp=row[6],
                resolved=bool(row[7]),
                resolved_at=row[8],
                acknowledgments=row[9]
            ))

        return alerts

    def get_recent_alerts(self, hours: int = 24) -> List[Alert]:
        """Get alerts from the past N hours."""
        cutoff = time.time() - (hours * 3600)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT * FROM alerts WHERE timestamp > ? ORDER BY timestamp DESC
        """, (cutoff,))
        rows = cursor.fetchall()
        conn.close()

        alerts = []
        for row in rows:
            alerts.append(Alert(
                alert_id=row[0],
                metric_name=row[1],
                severity=row[2],
                message=row[3],
                value=row[4],
                threshold=row[5],
                timestamp=row[6],
                resolved=bool(row[7]),
                resolved_at=row[8],
                acknowledgments=row[9]
            ))

        return alerts

    def get_alerts_by_metric(self, metric_name: str) -> List[Alert]:
        """Get alerts for a specific metric."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT * FROM alerts WHERE metric_name = ? ORDER BY timestamp DESC
        """, (metric_name,))
        rows = cursor.fetchall()
        conn.close()

        alerts = []
        for row in rows:
            alerts.append(Alert(
                alert_id=row[0],
                metric_name=row[1],
                severity=row[2],
                message=row[3],
                value=row[4],
                threshold=row[5],
                timestamp=row[6],
                resolved=bool(row[7]),
                resolved_at=row[8],
                acknowledgments=row[9]
            ))

        return alerts

    def resolve_alert(self, alert_id: str) -> None:
        """Mark an alert as resolved."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE alerts SET resolved = 1, resolved_at = ? WHERE alert_id = ?
        """, (time.time(), alert_id))

        conn.commit()
        conn.close()

    def get_statistics(self) -> Dict[str, Any]:
        """Get alert statistics."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM alerts WHERE resolved = 0")
        active = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM alerts WHERE resolved = 1")
        resolved = cursor.fetchone()[0]

        cursor.execute("""
            SELECT severity, COUNT(*) FROM alerts
            WHERE resolved = 0 GROUP BY severity
        """)
        by_severity = {row[0]: row[1] for row in cursor.fetchall()}

        cursor.execute("""
            SELECT metric_name, COUNT(*) FROM alerts
            WHERE resolved = 0 GROUP BY metric_name
        """)
        by_metric = {row[0]: row[1] for row in cursor.fetchall()}

        conn.close()

        return {
            "active_alerts": active,
            "resolved_alerts": resolved,
            "by_severity": by_severity,
            "by_metric": by_metric
        }


class AlertNotifier:
    """Base class for alert notification handlers."""

    def __init__(self, name: str):
        self.name = name

    def send(self, alert: Alert) -> bool:
        """Send an alert notification."""
        raise NotImplementedError


class LogNotifier(AlertNotifier):
    """Send alerts to logs."""

    def __init__(self, logger: logging.Logger):
        super().__init__("log")
        self.logger = logger

    def send(self, alert: Alert) -> bool:
        """Log an alert."""
        level_map = {
            AlertSeverity.INFO.value: logging.INFO,
            AlertSeverity.WARNING.value: logging.WARNING,
            AlertSeverity.CRITICAL.value: logging.CRITICAL,
            AlertSeverity.EMERGENCY.value: logging.CRITICAL
        }

        level = level_map.get(alert.severity, logging.WARNING)
        self.logger.log(level, f"[ALERT] {alert.message}")
        return True


class SlackNotifier(AlertNotifier):
    """Send alerts to Slack."""

    def __init__(self, webhook_url: str):
        super().__init__("slack")
        self.webhook_url = webhook_url

    def send(self, alert: Alert) -> bool:
        """Send alert to Slack."""
        try:
            import requests

            color_map = {
                AlertSeverity.INFO.value: "#36a64f",
                AlertSeverity.WARNING.value: "#ffa500",
                AlertSeverity.CRITICAL.value: "#ff0000",
                AlertSeverity.EMERGENCY.value: "#8b0000"
            }

            payload = {
                "attachments": [
                    {
                        "color": color_map.get(alert.severity, "#999999"),
                        "title": f"Alert: {alert.metric_name}",
                        "text": alert.message,
                        "fields": [
                            {
                                "title": "Severity",
                                "value": alert.severity,
                                "short": True
                            },
                            {
                                "title": "Value",
                                "value": f"{alert.value}",
                                "short": True
                            },
                            {
                                "title": "Threshold",
                                "value": f"{alert.threshold}",
                                "short": True
                            }
                        ],
                        "footer": "elyan Bot",
                        "ts": int(alert.timestamp)
                    }
                ]
            }

            response = requests.post(self.webhook_url, json=payload, timeout=5)
            return response.status_code == 200

        except Exception as e:
            logger.error(f"Failed to send Slack notification: {e}")
            return False


class AlertManager:
    """Manages alerts and notifications."""

    def __init__(self, db_path: str = "~/.elyan/alerts.db"):
        self.store = AlertStore(db_path)
        self.notifiers: Dict[str, AlertNotifier] = {}
        self.thresholds: Dict[str, AlertThreshold] = {}
        self.alert_cooldowns: Dict[str, float] = {}  # alert_id -> last_alert_time
        self._lock = threading.Lock()

    def add_notifier(self, notifier: AlertNotifier) -> None:
        """Add a notification channel."""
        self.notifiers[notifier.name] = notifier

    def add_threshold(self, threshold: AlertThreshold) -> None:
        """Add an alert threshold."""
        self.thresholds[threshold.metric_name] = threshold

    def check_metric(self, metric_name: str, value: float) -> Optional[Alert]:
        """Check if a metric exceeds its threshold."""
        if metric_name not in self.thresholds:
            return None

        threshold = self.thresholds[metric_name]

        if not threshold.enabled:
            return None

        # Check if metric exceeds threshold
        exceeds = threshold.check(value)

        if not exceeds:
            # Check if we have an active alert to resolve
            active_alerts = self.store.get_alerts_by_metric(metric_name)
            for alert in active_alerts:
                if not alert.resolved:
                    self.store.resolve_alert(alert.alert_id)
                    logger.info(f"Resolved alert: {alert.alert_id}")
            return None

        # Check cooldown
        alert_id = f"{metric_name}:{threshold.severity}"
        with self._lock:
            now = time.time()
            last_time = self.alert_cooldowns.get(alert_id, 0)
            cooldown_seconds = threshold.cooldown_minutes * 60

            if now - last_time < cooldown_seconds:
                return None

            self.alert_cooldowns[alert_id] = now

        # Create alert
        message = threshold.message_template.format(
            metric=metric_name,
            value=value,
            threshold=threshold.threshold_value
        )

        alert = Alert(
            alert_id=f"{metric_name}_{int(now * 1000)}",
            metric_name=metric_name,
            severity=threshold.severity,
            message=message,
            value=value,
            threshold=threshold.threshold_value,
            timestamp=now
        )

        self.store.save_alert(alert)
        self._notify(alert)

        return alert

    def _notify(self, alert: Alert) -> None:
        """Send alert to all notifiers."""
        for notifier in self.notifiers.values():
            try:
                notifier.send(alert)
            except Exception as e:
                logger.error(f"Failed to send alert via {notifier.name}: {e}")

    def get_active_alerts(self) -> List[Alert]:
        """Get all active alerts."""
        return self.store.get_active_alerts()

    def get_recent_alerts(self, hours: int = 24) -> List[Alert]:
        """Get recent alerts."""
        return self.store.get_recent_alerts(hours)

    def get_statistics(self) -> Dict[str, Any]:
        """Get alert statistics."""
        return self.store.get_statistics()

    def resolve_alert(self, alert_id: str) -> None:
        """Manually resolve an alert."""
        self.store.resolve_alert(alert_id)


def create_default_alerts(alert_manager: AlertManager) -> None:
    """Create default alert thresholds."""
    # Error rate > 5%
    alert_manager.add_threshold(AlertThreshold(
        metric_name="error_rate",
        operator=">",
        threshold_value=5.0,
        severity=AlertSeverity.WARNING.value,
        message_template="Error rate is {value}% (threshold: {threshold}%)"
    ))

    # Latency P99 > 5000ms
    alert_manager.add_threshold(AlertThreshold(
        metric_name="latency_p99",
        operator=">",
        threshold_value=5000.0,
        severity=AlertSeverity.WARNING.value,
        message_template="P99 latency is {value}ms (threshold: {threshold}ms)"
    ))

    # Cost > $10/hour
    alert_manager.add_threshold(AlertThreshold(
        metric_name="hourly_cost",
        operator=">",
        threshold_value=10.0,
        severity=AlertSeverity.CRITICAL.value,
        message_template="Hourly cost is ${value:.2f} (threshold: ${threshold:.2f})"
    ))

    # LLM provider unavailable
    alert_manager.add_threshold(AlertThreshold(
        metric_name="llm_availability",
        operator="<",
        threshold_value=1.0,
        severity=AlertSeverity.CRITICAL.value,
        message_template="LLM provider availability is {value}% (threshold: {threshold}%)"
    ))

    # Memory usage > 85%
    alert_manager.add_threshold(AlertThreshold(
        metric_name="memory_percent",
        operator=">",
        threshold_value=85.0,
        severity=AlertSeverity.WARNING.value,
        message_template="Memory usage is {value}% (threshold: {threshold}%)"
    ))

    # Disk space < 10%
    alert_manager.add_threshold(AlertThreshold(
        metric_name="disk_free_percent",
        operator="<",
        threshold_value=10.0,
        severity=AlertSeverity.CRITICAL.value,
        message_template="Disk space available is {value}% (threshold: {threshold}%)"
    ))
