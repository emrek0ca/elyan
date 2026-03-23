"""
Phase 5-3: Real-time Dashboard API

Provides REST endpoints for dashboard widgets with:
- Real-time metrics via WebSocket
- Historical analytics
- Performance trend tracking
- Widget-specific data endpoints
"""

import json
import logging
from typing import Dict, Any, List, Optional, Callable
from datetime import datetime, timedelta
from threading import Thread, Lock, Event
from dataclasses import dataclass, asdict
from collections import deque

logger = logging.getLogger(__name__)


@dataclass
class MetricSnapshot:
    """Single point in time metric snapshot"""
    timestamp: str
    metric_name: str
    value: float
    tags: Dict[str, str]


class MetricsStore:
    """In-memory time-series metrics storage with sliding window"""

    def __init__(self, max_history: int = 1000):
        """Initialize metrics store"""
        self.max_history = max_history
        self._metrics: Dict[str, deque] = {}
        self._lock = Lock()

    def record(self, metric_name: str, value: float, tags: Optional[Dict[str, str]] = None) -> None:
        """Record a metric value"""
        with self._lock:
            if metric_name not in self._metrics:
                self._metrics[metric_name] = deque(maxlen=self.max_history)

            snapshot = MetricSnapshot(
                timestamp=datetime.now().isoformat(),
                metric_name=metric_name,
                value=value,
                tags=tags or {}
            )
            self._metrics[metric_name].append(snapshot)

    def get_metrics(self, metric_name: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Get recent metric values"""
        with self._lock:
            if metric_name not in self._metrics:
                return []

            metrics = list(self._metrics[metric_name])[-limit:]
            return [asdict(m) for m in metrics]

    def get_latest(self, metric_name: str) -> Optional[Dict[str, Any]]:
        """Get latest metric value"""
        with self._lock:
            if metric_name not in self._metrics or not self._metrics[metric_name]:
                return None

            latest = self._metrics[metric_name][-1]
            return asdict(latest)

    def get_summary(self, metric_name: str) -> Optional[Dict[str, Any]]:
        """Get metric summary (min, max, avg, count)"""
        with self._lock:
            if metric_name not in self._metrics or not self._metrics[metric_name]:
                return None

            values = [m.value for m in self._metrics[metric_name]]
            return {
                "metric_name": metric_name,
                "count": len(values),
                "min": min(values),
                "max": max(values),
                "avg": sum(values) / len(values),
                "latest": values[-1] if values else None
            }


class WebSocketManager:
    """Manages WebSocket connections for real-time updates"""

    def __init__(self):
        """Initialize WebSocket manager"""
        self._connections: List[Any] = []
        self._lock = Lock()
        self._subscribers: Dict[str, List[Callable]] = {}

    def register(self, connection: Any) -> None:
        """Register a new WebSocket connection"""
        with self._lock:
            self._connections.append(connection)
            logger.debug(f"WebSocket registered, total: {len(self._connections)}")

    def unregister(self, connection: Any) -> None:
        """Unregister a WebSocket connection"""
        with self._lock:
            if connection in self._connections:
                self._connections.remove(connection)
                logger.debug(f"WebSocket unregistered, total: {len(self._connections)}")

    def subscribe(self, topic: str, callback: Callable) -> None:
        """Subscribe to a topic"""
        with self._lock:
            if topic not in self._subscribers:
                self._subscribers[topic] = []
            self._subscribers[topic].append(callback)

    def broadcast(self, topic: str, data: Dict[str, Any]) -> None:
        """Broadcast data to all subscribers"""
        with self._lock:
            callbacks = self._subscribers.get(topic, [])

        message = json.dumps({
            "topic": topic,
            "timestamp": datetime.now().isoformat(),
            "data": data
        })

        for callback in callbacks:
            try:
                callback(message)
            except Exception as e:
                logger.error(f"Error in subscriber callback: {e}")

    def send_all(self, message: Dict[str, Any]) -> None:
        """Send message to all connected clients"""
        data = json.dumps(message)
        with self._lock:
            for connection in self._connections:
                try:
                    connection.send(data)
                except Exception as e:
                    logger.error(f"Error sending WebSocket message: {e}")


class DashboardAPIv1:
    """Dashboard API endpoints - v1.0"""

    def __init__(self):
        """Initialize API"""
        self.metrics = MetricsStore()
        self.ws = WebSocketManager()
        self._start_metrics_collector()

    def _start_metrics_collector(self) -> None:
        """Start background metrics collection thread"""
        def collector():
            while True:
                try:
                    self._collect_metrics()
                    # Sleep 5 seconds between collections
                    import time
                    time.sleep(5)
                except Exception as e:
                    logger.error(f"Metrics collection error: {e}")

        thread = Thread(target=collector, daemon=True)
        thread.start()

    def _collect_metrics(self) -> None:
        """Collect current system metrics"""
        try:
            from core.performance_cache import get_all_cache_stats
            from core.cognitive_layer_integrator import get_cognitive_integrator

            # Cache hit rate
            cache_stats = get_all_cache_stats()
            total_hits = sum(s.get("hits", 0) for s in cache_stats.values())
            total_misses = sum(s.get("misses", 0) for s in cache_stats.values())

            if total_hits + total_misses > 0:
                hit_rate = (total_hits / (total_hits + total_misses)) * 100
                self.metrics.record("cache_hit_rate", hit_rate, {"unit": "percent"})

            # Cognitive metrics
            integrator = get_cognitive_integrator()
            success_rate = integrator.calculate_success_rate()
            self.metrics.record("task_success_rate", success_rate, {"unit": "percent"})

            mode = integrator.current_mode
            self.metrics.record("cognitive_mode", 1.0 if mode == "FOCUSED" else 0.0, {"mode": mode})

            # Broadcast to WebSocket subscribers
            self.ws.broadcast("metrics", {
                "cache_hit_rate": hit_rate if total_hits + total_misses > 0 else 0,
                "task_success_rate": success_rate,
                "cognitive_mode": mode
            })

        except Exception as e:
            logger.error(f"Metric collection failed: {e}")

    def get_cognitive_state(self) -> Dict[str, Any]:
        """GET /api/v1/cognitive/state"""
        try:
            from ui.widgets.cognitive_state_widget import CognitiveStateWidget

            widget = CognitiveStateWidget()
            return {
                "success": True,
                "data": widget.render_json()
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    def get_error_predictions(self) -> Dict[str, Any]:
        """GET /api/v1/predictions/errors"""
        try:
            from ui.widgets.cognitive_state_widget import ErrorPredictionWidget

            widget = ErrorPredictionWidget()
            return {
                "success": True,
                "data": widget.render_json()
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    def get_deadlock_stats(self) -> Dict[str, Any]:
        """GET /api/v1/deadlock/stats"""
        try:
            from ui.widgets.deadlock_prevention_widget import DeadlockPreventionWidget

            widget = DeadlockPreventionWidget()
            return {
                "success": True,
                "data": widget.render_json()
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    def get_deadlock_timeline(self, hours: int = 24) -> Dict[str, Any]:
        """GET /api/v1/deadlock/timeline?hours=24"""
        try:
            from ui.widgets.deadlock_prevention_widget import DeadlockTimeline

            data = DeadlockTimeline.get_timeline_data(hours)
            return {
                "success": True,
                "data": data
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    def get_sleep_consolidation(self) -> Dict[str, Any]:
        """GET /api/v1/sleep/consolidation"""
        try:
            from ui.widgets.sleep_consolidation_widget import SleepConsolidationWidget

            widget = SleepConsolidationWidget()
            return {
                "success": True,
                "data": widget.render_json()
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    def get_cache_performance(self) -> Dict[str, Any]:
        """GET /api/v1/cache/performance"""
        try:
            from core.performance_cache import get_all_cache_stats

            stats = get_all_cache_stats()

            # Calculate aggregate
            total_hits = sum(s.get("hits", 0) for s in stats.values())
            total_misses = sum(s.get("misses", 0) for s in stats.values())
            total_entries = sum(s.get("entries", 0) for s in stats.values())
            hit_rate = (total_hits / (total_hits + total_misses) * 100) if (total_hits + total_misses) > 0 else 0

            return {
                "success": True,
                "aggregate": {
                    "hit_rate_pct": round(hit_rate, 1),
                    "total_hits": total_hits,
                    "total_misses": total_misses,
                    "total_entries": total_entries
                },
                "caches": stats
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    def get_metrics_history(self, metric_name: str, limit: int = 100) -> Dict[str, Any]:
        """GET /api/v1/metrics/history?name=cache_hit_rate&limit=100"""
        try:
            data = self.metrics.get_metrics(metric_name, limit)
            return {
                "success": True,
                "metric_name": metric_name,
                "count": len(data),
                "data": data
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    def get_metrics_summary(self, metric_name: str) -> Dict[str, Any]:
        """GET /api/v1/metrics/summary?name=cache_hit_rate"""
        try:
            summary = self.metrics.get_summary(metric_name)
            if not summary:
                return {
                    "success": False,
                    "error": f"Metric {metric_name} not found"
                }

            return {
                "success": True,
                "data": summary
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    def list_available_metrics(self) -> Dict[str, Any]:
        """GET /api/v1/metrics/available"""
        try:
            with self.metrics._lock:
                metric_names = list(self.metrics._metrics.keys())

            return {
                "success": True,
                "metrics": metric_names,
                "count": len(metric_names)
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }


# Global API instance
_dashboard_api: Optional[DashboardAPIv1] = None


def get_dashboard_api() -> DashboardAPIv1:
    """Get or create global dashboard API instance"""
    global _dashboard_api
    if _dashboard_api is None:
        _dashboard_api = DashboardAPIv1()
    return _dashboard_api


def reset_dashboard_api() -> None:
    """Reset API instance (for testing)"""
    global _dashboard_api
    _dashboard_api = None
