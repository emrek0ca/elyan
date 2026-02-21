"""
Comprehensive Logging and Monitoring System
Tracks performance metrics, operations, and system health
"""

import asyncio
import json
import time
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from collections import defaultdict, deque
from dataclasses import dataclass, asdict
from enum import Enum
from utils.logger import get_logger
from threading import Lock

logger = get_logger("monitoring")


class MetricType(Enum):
    """Types of metrics"""
    OPERATION = "operation"
    TOOL_EXECUTION = "tool_execution"
    LLM_CALL = "llm_call"
    MEMORY_USAGE = "memory_usage"
    ERROR = "error"


@dataclass
class Metric:
    """Performance metric data point"""
    timestamp: float
    metric_type: str
    name: str
    value: float
    metadata: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class MetricsCollector:
    """Collects and aggregates performance metrics"""

    def __init__(self, window_size: int = 1000):
        self.metrics: deque = deque(maxlen=window_size)
        self.lock = Lock()

    def record(self, metric_type: MetricType, name: str, value: float, metadata: Optional[Dict] = None):
        """Record a single metric"""
        with self.lock:
            metric = Metric(
                timestamp=time.time(),
                metric_type=metric_type.value,
                name=name,
                value=value,
                metadata=metadata or {}
            )
            self.metrics.append(metric)

    def get_statistics(self, metric_name: str, time_window_seconds: int = 3600) -> Dict[str, Any]:
        """Get statistics for a metric over a time window"""
        now = time.time()
        cutoff = now - time_window_seconds

        with self.lock:
            relevant = [m for m in self.metrics if m.name == metric_name and m.timestamp > cutoff]

        if not relevant:
            return {"count": 0, "avg": 0, "min": 0, "max": 0}

        values = [m.value for m in relevant]

        return {
            "count": len(values),
            "avg": sum(values) / len(values),
            "min": min(values),
            "max": max(values),
            "total": sum(values),
            "latest": values[-1] if values else 0,
        }

    def get_all_metrics(self) -> List[Dict[str, Any]]:
        """Get all recorded metrics"""
        with self.lock:
            return [m.to_dict() for m in self.metrics]


class OperationTracker:
    """Tracks operations and their outcomes"""

    def __init__(self):
        self.operations: Dict[str, List[Dict]] = defaultdict(list)
        self.lock = Lock()

    def record_operation(self, tool_name: str, success: bool, duration_ms: float, metadata: Optional[Dict] = None):
        """Record a tool operation"""
        with self.lock:
            self.operations[tool_name].append({
                "timestamp": datetime.now().isoformat(),
                "success": success,
                "duration_ms": duration_ms,
                "metadata": metadata or {},
            })

    def get_tool_stats(self, tool_name: str) -> Dict[str, Any]:
        """Get statistics for a specific tool"""
        with self.lock:
            ops = self.operations.get(tool_name, [])

        if not ops:
            return {"total": 0, "success": 0, "failed": 0, "success_rate": 0, "avg_duration_ms": 0}

        successful = sum(1 for op in ops if op["success"])
        total = len(ops)
        avg_duration = sum(op["duration_ms"] for op in ops) / total

        return {
            "total": total,
            "success": successful,
            "failed": total - successful,
            "success_rate": f"{successful / total * 100:.1f}%",
            "avg_duration_ms": f"{avg_duration:.1f}",
            "latest_ops": ops[-10:],  # Last 10 operations
        }

    def get_overall_stats(self) -> Dict[str, Any]:
        """Get overall statistics across all tools"""
        with self.lock:
            all_ops = [op for ops in self.operations.values() for op in ops]

        if not all_ops:
            return {
                "total_operations": 0,
                "successful": 0,
                "failed": 0,
                "success_rate": "0%",
                "avg_duration_ms": "0",
                "tools_used": 0,
            }

        successful = sum(1 for op in all_ops if op["success"])
        total = len(all_ops)
        avg_duration = sum(op["duration_ms"] for op in all_ops) / total

        return {
            "total_operations": total,
            "successful": successful,
            "failed": total - successful,
            "success_rate": f"{successful / total * 100:.1f}%",
            "avg_duration_ms": f"{avg_duration:.1f}",
            "tools_used": len(self.operations),
        }


class MonitoringSystem:
    """Central monitoring system"""

    def __init__(self):
        self.metrics = MetricsCollector()
        self.operations = OperationTracker()
        self.errors: deque = deque(maxlen=100)
        self.lock = Lock()

    def record_tool_execution(self, tool_name: str, success: bool, duration_ms: float, metadata: Optional[Dict] = None):
        """Record tool execution for monitoring"""
        self.operations.record_operation(tool_name, success, duration_ms, metadata)
        self.metrics.record(
            MetricType.TOOL_EXECUTION,
            tool_name,
            duration_ms,
            metadata or {}
        )

        if not success and metadata and metadata.get("error"):
            self.record_error(tool_name, metadata["error"], "tool_execution")

    def record_llm_call(self, prompt_tokens: int, response_tokens: int, duration_ms: float, model: str = "ollama"):
        """Record LLM API call for monitoring"""
        self.metrics.record(
            MetricType.LLM_CALL,
            f"{model}_latency",
            duration_ms,
            {"prompt_tokens": prompt_tokens, "response_tokens": response_tokens}
        )

    def record_operation(self, operation: str, success: bool, duration_ms: float, metadata: Optional[Dict] = None):
        """Record a higher-level operation"""
        self.metrics.record(
            MetricType.OPERATION,
            operation,
            duration_ms,
            metadata or {}
        )

        if not success:
            self.record_error(operation, metadata and metadata.get("error", "Unknown"), "operation")

    def record_error(self, component: str, error_msg: str, error_type: str = "general"):
        """Record an error"""
        with self.lock:
            self.errors.append({
                "timestamp": datetime.now().isoformat(),
                "component": component,
                "error": error_msg,
                "type": error_type,
            })

        self.metrics.record(
            MetricType.ERROR,
            f"error_{error_type}",
            1.0,
            {"component": component, "error": error_msg[:100]}
        )

    def get_dashboard(self) -> Dict[str, Any]:
        """Get comprehensive monitoring dashboard"""
        return {
            "timestamp": datetime.now().isoformat(),
            "operations": self.operations.get_overall_stats(),
            "tool_stats": {name: self.operations.get_tool_stats(name)
                          for name in list(self.operations.operations.keys())[:10]},
            "errors": list(self.errors)[-10:],
            "metrics_summary": {
                "llm_latency": self.metrics.get_statistics("ollama_latency"),
                "tool_execution": self.metrics.get_statistics("tool_execution"),
            },
        }

    def get_health_status(self) -> Dict[str, Any]:
        """Get health status summary"""
        stats = self.operations.get_overall_stats()
        recent_errors = len([e for e in self.errors if
                            (datetime.now() - datetime.fromisoformat(e["timestamp"])).total_seconds() < 300])

        success_rate = float(stats["success_rate"].rstrip("%"))

        if success_rate >= 95 and recent_errors == 0:
            health = "HEALTHY"
            status_code = ""
        elif success_rate >= 80:
            health = "DEGRADED"
            status_code = ""
        else:
            health = "UNHEALTHY"
            status_code = ""

        return {
            "status": health,
            "status_code": status_code,
            "success_rate": stats["success_rate"],
            "recent_errors_5min": recent_errors,
            "total_operations": stats["total_operations"],
        }

    def export_metrics(self) -> Dict[str, Any]:
        """Export all metrics and statistics"""
        return {
            "exported_at": datetime.now().isoformat(),
            "dashboard": self.get_dashboard(),
            "health": self.get_health_status(),
            "raw_metrics": self.metrics.get_all_metrics(),
        }


# Global instance
_monitoring_system: Optional[MonitoringSystem] = None


def get_monitoring() -> MonitoringSystem:
    """Get or create monitoring system"""
    global _monitoring_system
    if _monitoring_system is None:
        _monitoring_system = MonitoringSystem()
    return _monitoring_system


# Helper functions for integration
def record_tool_execution(tool_name: str, success: bool, duration_ms: float, **metadata):
    """Record tool execution (convenience function)"""
    get_monitoring().record_tool_execution(tool_name, success, duration_ms, metadata)


def record_operation(operation: str, success: bool, duration_ms: float, **metadata):
    """Record operation (convenience function)"""
    get_monitoring().record_operation(operation, success, duration_ms, metadata)


def record_error(component: str, error_msg: str, error_type: str = "general"):
    """Record error (convenience function)"""
    get_monitoring().record_error(component, error_msg, error_type)
