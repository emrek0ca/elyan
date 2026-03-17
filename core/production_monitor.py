"""
Production Monitoring - Real-time system monitoring with Prometheus/Grafana integration
Provides metrics collection, health checks, alerting, and performance tracking
"""

import time
import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from collections import defaultdict, deque
from dataclasses import dataclass, field, asdict
import threading

logger = logging.getLogger(__name__)


@dataclass
class MetricPoint:
    """Single metric data point"""
    timestamp: float
    value: float
    labels: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "value": self.value,
            "labels": self.labels
        }


@dataclass
class HealthCheck:
    """System health check result"""
    component: str
    status: str  # 'healthy', 'degraded', 'critical'
    message: str
    timestamp: float = field(default_factory=time.time)
    metrics: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Alert:
    """Alert notification"""
    severity: str  # 'info', 'warning', 'critical'
    message: str
    component: str
    timestamp: float = field(default_factory=time.time)
    resolved: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class PrometheusMetrics:
    """Prometheus-compatible metrics collector"""

    def __init__(self):
        self.metrics: Dict[str, List[MetricPoint]] = defaultdict(list)
        self.lock = threading.RLock()
        self.retention_period = 3600  # 1 hour default

    def record_metric(self, name: str, value: float, labels: Optional[Dict[str, str]] = None):
        """Record a metric point"""
        with self.lock:
            metric_point = MetricPoint(
                timestamp=time.time(),
                value=value,
                labels=labels or {}
            )
            self.metrics[name].append(metric_point)
            self._cleanup_old_metrics(name)

    def get_metric(self, name: str, label_filter: Optional[Dict[str, str]] = None) -> List[MetricPoint]:
        """Get metric points, optionally filtered by labels"""
        with self.lock:
            if name not in self.metrics:
                return []

            points = self.metrics[name]
            if not label_filter:
                return points

            # Filter by labels
            filtered = []
            for point in points:
                if all(point.labels.get(k) == v for k, v in label_filter.items()):
                    filtered.append(point)
            return filtered

    def get_metric_summary(self, name: str) -> Dict[str, Any]:
        """Get summary statistics for a metric"""
        with self.lock:
            points = self.metrics.get(name, [])
            if not points:
                return {"error": "No data"}

            values = [p.value for p in points]
            return {
                "count": len(values),
                "min": min(values),
                "max": max(values),
                "avg": sum(values) / len(values),
                "latest": values[-1],
                "latest_timestamp": points[-1].timestamp
            }

    def _cleanup_old_metrics(self, name: str):
        """Remove metrics older than retention period"""
        cutoff_time = time.time() - self.retention_period
        if name in self.metrics:
            self.metrics[name] = [
                p for p in self.metrics[name] if p.timestamp > cutoff_time
            ]


class HealthMonitor:
    """System health monitoring"""

    def __init__(self):
        self.health_checks: Dict[str, HealthCheck] = {}
        self.lock = threading.RLock()

    def record_health(self, check: HealthCheck):
        """Record a health check result"""
        with self.lock:
            self.health_checks[check.component] = check

    def get_health_status(self, component: Optional[str] = None) -> Dict[str, Any]:
        """Get current health status"""
        with self.lock:
            if component:
                check = self.health_checks.get(component)
                return check.to_dict() if check else {"error": "Component not found"}

            # Overall health
            all_checks = list(self.health_checks.values())
            if not all_checks:
                return {"status": "unknown", "checks": []}

            statuses = [c.status for c in all_checks]
            if "critical" in statuses:
                overall = "critical"
            elif "degraded" in statuses:
                overall = "degraded"
            else:
                overall = "healthy"

            return {
                "status": overall,
                "timestamp": time.time(),
                "checks": [c.to_dict() for c in all_checks]
            }

    def run_health_checks(self, check_functions: Dict[str, callable]) -> Dict[str, Any]:
        """Run a set of health check functions"""
        results = {}
        for name, func in check_functions.items():
            try:
                check = func()
                if isinstance(check, HealthCheck):
                    self.record_health(check)
                    results[name] = check.to_dict()
            except Exception as e:
                logger.error(f"Health check failed for {name}: {e}")
                results[name] = {
                    "status": "critical",
                    "message": str(e)
                }
        return results


class AlertManager:
    """Alert management and notification"""

    def __init__(self, max_alerts: int = 1000):
        self.alerts: deque = deque(maxlen=max_alerts)
        self.lock = threading.RLock()
        self.alert_handlers: List[callable] = []

    def register_alert_handler(self, handler: callable):
        """Register a handler to receive alerts"""
        self.alert_handlers.append(handler)

    def create_alert(self, severity: str, message: str, component: str):
        """Create and dispatch an alert"""
        alert = Alert(severity=severity, message=message, component=component)

        with self.lock:
            self.alerts.append(alert)

        # Dispatch to handlers
        for handler in self.alert_handlers:
            try:
                handler(alert)
            except Exception as e:
                logger.error(f"Alert handler error: {e}")

    def get_alerts(self, severity: Optional[str] = None, limit: int = 100) -> List[Dict]:
        """Get recent alerts, optionally filtered by severity"""
        with self.lock:
            alerts = list(self.alerts)
            if severity:
                alerts = [a for a in alerts if a.severity == severity]
            return [a.to_dict() for a in alerts[-limit:]]

    def resolve_alert(self, alert_index: int):
        """Mark an alert as resolved"""
        with self.lock:
            alerts = list(self.alerts)
            if 0 <= alert_index < len(alerts):
                alerts[alert_index].resolved = True


class PerformanceTracker:
    """Track performance metrics"""

    def __init__(self):
        self.operation_times: Dict[str, deque] = defaultdict(lambda: deque(maxlen=1000))
        self.operation_counts: Dict[str, int] = defaultdict(int)
        self.lock = threading.RLock()

    def record_operation(self, operation: str, duration: float):
        """Record an operation execution time"""
        with self.lock:
            self.operation_times[operation].append(duration)
            self.operation_counts[operation] += 1

    def get_operation_stats(self, operation: Optional[str] = None) -> Dict[str, Any]:
        """Get performance statistics for operations"""
        with self.lock:
            if operation:
                times = list(self.operation_times.get(operation, []))
                if not times:
                    return {"error": "No data"}

                times_sorted = sorted(times)
                n = len(times)
                return {
                    "count": n,
                    "total_time": sum(times),
                    "min": min(times),
                    "max": max(times),
                    "avg": sum(times) / n,
                    "p50": times_sorted[n // 2],
                    "p95": times_sorted[int(n * 0.95)],
                    "p99": times_sorted[int(n * 0.99)],
                    "throughput": self.operation_counts[operation] / sum(times) if sum(times) > 0 else 0
                }

            # All operations
            stats = {}
            for op in self.operation_times.keys():
                stats[op] = self.get_operation_stats(op)
            return stats


class ProductionMonitor:
    """Main production monitoring system"""

    def __init__(self):
        self.metrics = PrometheusMetrics()
        self.health = HealthMonitor()
        self.alerts = AlertManager()
        self.performance = PerformanceTracker()
        self.startup_time = time.time()
        self.lock = threading.RLock()

    def get_system_health(self) -> Dict[str, Any]:
        """Get comprehensive system health report"""
        uptime = time.time() - self.startup_time

        return {
            "timestamp": datetime.now().isoformat(),
            "uptime_seconds": uptime,
            "uptime_formatted": self._format_duration(uptime),
            "health_status": self.health.get_health_status(),
            "recent_alerts": self.alerts.get_alerts(limit=10),
            "critical_alerts": self.alerts.get_alerts(severity="critical"),
            "performance_summary": self.performance.get_operation_stats()
        }

    def record_request(self, endpoint: str, duration: float, status: int, size: int):
        """Record an API request"""
        self.metrics.record_metric(
            "http_request_duration_seconds",
            duration,
            {"endpoint": endpoint, "status": str(status)}
        )
        self.metrics.record_metric(
            "http_request_size_bytes",
            size,
            {"endpoint": endpoint}
        )
        self.performance.record_operation(f"http_{endpoint}", duration)

        # Alert on slow requests
        if duration > 5.0:
            self.alerts.create_alert(
                "warning",
                f"Slow request: {endpoint} took {duration:.2f}s",
                "http"
            )

    def get_prometheus_format(self) -> str:
        """Export metrics in Prometheus text format"""
        lines = []
        lines.append("# HELP system_metrics System monitoring metrics")
        lines.append("# TYPE system_metrics gauge")

        for metric_name, points in self.metrics.metrics.items():
            if not points:
                continue
            latest = points[-1]
            label_str = ""
            if latest.labels:
                label_pairs = [f'{k}="{v}"' for k, v in latest.labels.items()]
                label_str = "{" + ",".join(label_pairs) + "}"
            lines.append(f"{metric_name}{label_str} {latest.value}")

        return "\n".join(lines)

    def export_metrics(self) -> Dict[str, Any]:
        """Export all metrics as JSON"""
        return {
            "timestamp": datetime.now().isoformat(),
            "uptime_seconds": time.time() - self.startup_time,
            "metrics": {
                name: [p.to_dict() for p in points]
                for name, points in self.metrics.metrics.items()
            },
            "health": self.health.get_health_status(),
            "alerts": self.alerts.get_alerts(),
            "performance": self.performance.get_operation_stats()
        }

    @staticmethod
    def _format_duration(seconds: float) -> str:
        """Format duration in human-readable format"""
        if seconds < 60:
            return f"{seconds:.1f}s"
        elif seconds < 3600:
            return f"{seconds / 60:.1f}m"
        else:
            return f"{seconds / 3600:.1f}h"

    def __repr__(self) -> str:
        return f"<ProductionMonitor uptime={self._format_duration(time.time() - self.startup_time)}>"
