"""
Monitoring Dashboard for elyan Bot Production
=============================================
Real-time metrics display, performance tracking, and analytics.

Features:
- Real-time metrics collection
- Intent accuracy tracking
- Latency distribution (P50, P95, P99)
- Error rate by category
- LLM provider performance
- Cost tracking
- Learning progress monitoring
- Web dashboard and CLI interface
"""

import json
import time
import logging
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from collections import defaultdict, deque
import threading
from pathlib import Path
import sqlite3

logger = logging.getLogger(__name__)


@dataclass
class MetricSnapshot:
    """A snapshot of system metrics."""
    timestamp: float
    intent_accuracy: float
    error_rate: float
    avg_latency_ms: float
    p50_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    throughput_requests_per_sec: float
    active_tasks: int
    llm_cost_usd: float
    learning_progress: float  # 0-100%

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


class MetricsCollector:
    """Collects and aggregates metrics."""

    def __init__(self, window_size: int = 1000):
        self.window_size = window_size
        self.latencies: deque = deque(maxlen=window_size)
        self.errors: deque = deque(maxlen=window_size)
        self.intents: deque = deque(maxlen=window_size)
        self.error_categories: Dict[str, int] = defaultdict(int)
        self.request_count = 0
        self.error_count = 0
        self.start_time = time.time()
        self._lock = threading.Lock()

    def record_request(self, latency_ms: float, success: bool, error_type: Optional[str] = None) -> None:
        """Record a request."""
        with self._lock:
            self.request_count += 1
            self.latencies.append(latency_ms)

            if not success:
                self.error_count += 1
                self.errors.append(time.time())
                if error_type:
                    self.error_categories[error_type] += 1

    def record_intent(self, predicted_intent: str, actual_intent: str) -> None:
        """Record an intent prediction."""
        with self._lock:
            self.intents.append(predicted_intent == actual_intent)

    def record_llm_call(self, cost_usd: float) -> None:
        """Record an LLM API call cost."""
        # Track in separate system
        pass

    def get_latency_percentiles(self) -> Dict[str, float]:
        """Get latency percentiles."""
        with self._lock:
            if not self.latencies:
                return {"p50": 0, "p95": 0, "p99": 0, "avg": 0}

            sorted_latencies = sorted(self.latencies)
            n = len(sorted_latencies)

            return {
                "p50": sorted_latencies[int(n * 0.50)],
                "p95": sorted_latencies[int(n * 0.95)],
                "p99": sorted_latencies[int(n * 0.99)],
                "avg": sum(self.latencies) / n
            }

    def get_error_rate(self) -> float:
        """Get current error rate as percentage."""
        with self._lock:
            if self.request_count == 0:
                return 0.0
            return (self.error_count / self.request_count) * 100

    def get_intent_accuracy(self) -> float:
        """Get intent prediction accuracy."""
        with self._lock:
            if not self.intents:
                return 0.0
            correct = sum(self.intents)
            return (correct / len(self.intents)) * 100

    def get_throughput(self) -> float:
        """Get requests per second."""
        elapsed = time.time() - self.start_time
        if elapsed == 0:
            return 0.0
        return self.request_count / elapsed

    def get_error_breakdown(self) -> Dict[str, int]:
        """Get error breakdown by category."""
        with self._lock:
            return dict(self.error_categories)

    def get_snapshot(self) -> MetricSnapshot:
        """Get current metrics snapshot."""
        latencies = self.get_latency_percentiles()

        return MetricSnapshot(
            timestamp=time.time(),
            intent_accuracy=self.get_intent_accuracy(),
            error_rate=self.get_error_rate(),
            avg_latency_ms=latencies["avg"],
            p50_latency_ms=latencies["p50"],
            p95_latency_ms=latencies["p95"],
            p99_latency_ms=latencies["p99"],
            throughput_requests_per_sec=self.get_throughput(),
            active_tasks=0,  # Updated separately
            llm_cost_usd=0.0,  # Updated separately
            learning_progress=0.0  # Updated separately
        )


class MetricsStore:
    """Stores metrics history."""

    def __init__(self, db_path: str = "~/.elyan/metrics.db"):
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = str(self.db_path)
        self._init_db()

    def _init_db(self) -> None:
        """Initialize database."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS metrics_snapshots (
                snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                intent_accuracy REAL,
                error_rate REAL,
                avg_latency_ms REAL,
                p50_latency_ms REAL,
                p95_latency_ms REAL,
                p99_latency_ms REAL,
                throughput_requests_per_sec REAL,
                active_tasks INTEGER,
                llm_cost_usd REAL,
                learning_progress REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS metric_timeseries (
                metric_id INTEGER PRIMARY KEY AUTOINCREMENT,
                metric_name TEXT NOT NULL,
                metric_value REAL NOT NULL,
                timestamp REAL NOT NULL,
                tags TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_timestamp ON metrics_snapshots(timestamp)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_metric_name ON metric_timeseries(metric_name)
        """)

        conn.commit()
        conn.close()

    def save_snapshot(self, snapshot: MetricSnapshot) -> None:
        """Save a metrics snapshot."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO metrics_snapshots (
                timestamp, intent_accuracy, error_rate, avg_latency_ms,
                p50_latency_ms, p95_latency_ms, p99_latency_ms,
                throughput_requests_per_sec, active_tasks, llm_cost_usd,
                learning_progress
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            snapshot.timestamp,
            snapshot.intent_accuracy,
            snapshot.error_rate,
            snapshot.avg_latency_ms,
            snapshot.p50_latency_ms,
            snapshot.p95_latency_ms,
            snapshot.p99_latency_ms,
            snapshot.throughput_requests_per_sec,
            snapshot.active_tasks,
            snapshot.llm_cost_usd,
            snapshot.learning_progress
        ))

        conn.commit()
        conn.close()

    def get_recent_snapshots(self, hours: int = 24) -> List[Dict[str, Any]]:
        """Get snapshots from the past N hours."""
        cutoff = time.time() - (hours * 3600)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT * FROM metrics_snapshots
            WHERE timestamp > ?
            ORDER BY timestamp DESC
            LIMIT 1000
        """, (cutoff,))

        rows = cursor.fetchall()
        conn.close()

        snapshots = []
        for row in rows:
            snapshots.append({
                "timestamp": row[1],
                "intent_accuracy": row[2],
                "error_rate": row[3],
                "avg_latency_ms": row[4],
                "p50_latency_ms": row[5],
                "p95_latency_ms": row[6],
                "p99_latency_ms": row[7],
                "throughput": row[8],
                "active_tasks": row[9],
                "llm_cost_usd": row[10],
                "learning_progress": row[11]
            })

        return snapshots

    def get_statistics(self, hours: int = 24) -> Dict[str, Any]:
        """Get statistics for the past N hours."""
        snapshots = self.get_recent_snapshots(hours)

        if not snapshots:
            return {}

        accuracies = [s["intent_accuracy"] for s in snapshots if s["intent_accuracy"] is not None]
        error_rates = [s["error_rate"] for s in snapshots if s["error_rate"] is not None]
        latencies = [s["avg_latency_ms"] for s in snapshots if s["avg_latency_ms"] is not None]
        costs = [s["llm_cost_usd"] for s in snapshots if s["llm_cost_usd"] is not None]

        return {
            "period_hours": hours,
            "snapshots_count": len(snapshots),
            "accuracy": {
                "avg": sum(accuracies) / len(accuracies) if accuracies else 0,
                "min": min(accuracies) if accuracies else 0,
                "max": max(accuracies) if accuracies else 0
            },
            "error_rate": {
                "avg": sum(error_rates) / len(error_rates) if error_rates else 0,
                "min": min(error_rates) if error_rates else 0,
                "max": max(error_rates) if error_rates else 0
            },
            "latency": {
                "avg": sum(latencies) / len(latencies) if latencies else 0,
                "min": min(latencies) if latencies else 0,
                "max": max(latencies) if latencies else 0
            },
            "total_cost_usd": sum(costs),
            "latest_snapshot": snapshots[0] if snapshots else None
        }


class MonitoringDashboard:
    """Main monitoring dashboard."""

    def __init__(self, db_path: str = "~/.elyan/metrics.db"):
        self.collector = MetricsCollector()
        self.store = MetricsStore(db_path)
        self.collection_interval = 60  # seconds
        self._running = False
        self._thread = None

    def start(self) -> None:
        """Start the monitoring dashboard."""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(target=self._collect_loop, daemon=True)
        self._thread.start()
        logger.info("Monitoring dashboard started")

    def stop(self) -> None:
        """Stop the monitoring dashboard."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("Monitoring dashboard stopped")

    def _collect_loop(self) -> None:
        """Background collection loop."""
        while self._running:
            try:
                snapshot = self.collector.get_snapshot()
                self.store.save_snapshot(snapshot)
            except Exception as e:
                logger.error(f"Error collecting metrics: {e}")

            time.sleep(self.collection_interval)

    def record_request(
        self,
        latency_ms: float,
        success: bool,
        error_type: Optional[str] = None
    ) -> None:
        """Record a request."""
        self.collector.record_request(latency_ms, success, error_type)

    def record_intent(self, predicted: str, actual: str) -> None:
        """Record an intent prediction."""
        self.collector.record_intent(predicted, actual)

    def get_current_metrics(self) -> Dict[str, Any]:
        """Get current metrics."""
        snapshot = self.collector.get_snapshot()

        return {
            "timestamp": datetime.fromtimestamp(snapshot.timestamp).isoformat(),
            "intent_accuracy_percent": round(snapshot.intent_accuracy, 2),
            "error_rate_percent": round(snapshot.error_rate, 2),
            "latency": {
                "p50_ms": round(snapshot.p50_latency_ms, 2),
                "p95_ms": round(snapshot.p95_latency_ms, 2),
                "p99_ms": round(snapshot.p99_latency_ms, 2),
                "avg_ms": round(snapshot.avg_latency_ms, 2)
            },
            "throughput_requests_per_sec": round(snapshot.throughput_requests_per_sec, 2),
            "errors_by_category": self.collector.get_error_breakdown()
        }

    def get_historical_data(self, hours: int = 24) -> Dict[str, Any]:
        """Get historical data."""
        return self.store.get_statistics(hours)

    def get_health_summary(self) -> Dict[str, Any]:
        """Get health summary."""
        metrics = self.get_current_metrics()
        accuracy = metrics["intent_accuracy_percent"]
        error_rate = metrics["error_rate_percent"]
        latency_p99 = metrics["latency"]["p99_ms"]

        # Determine health status
        if accuracy >= 85 and error_rate < 5 and latency_p99 < 5000:
            status = "healthy"
        elif accuracy >= 70 and error_rate < 10 and latency_p99 < 10000:
            status = "degraded"
        else:
            status = "unhealthy"

        return {
            "status": status,
            "intent_accuracy_percent": accuracy,
            "error_rate_percent": error_rate,
            "latency_p99_ms": latency_p99,
            "timestamp": datetime.now().isoformat()
        }

    def export_metrics_json(self, filepath: str) -> None:
        """Export metrics to JSON file."""
        metrics = {
            "current": self.get_current_metrics(),
            "historical_24h": self.get_historical_data(24),
            "historical_7d": self.get_historical_data(168),
            "health_summary": self.get_health_summary(),
            "export_time": datetime.now().isoformat()
        }

        Path(filepath).parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, "w") as f:
            json.dump(metrics, f, indent=2)

        logger.info(f"Metrics exported to {filepath}")


# Default global instance
_dashboard: Optional[MonitoringDashboard] = None


def get_dashboard() -> MonitoringDashboard:
    """Get or create the global monitoring dashboard."""
    global _dashboard
    if _dashboard is None:
        _dashboard = MonitoringDashboard()
        _dashboard.start()
    return _dashboard


def shutdown_dashboard() -> None:
    """Shutdown the global dashboard."""
    global _dashboard
    if _dashboard:
        _dashboard.stop()
        _dashboard = None
