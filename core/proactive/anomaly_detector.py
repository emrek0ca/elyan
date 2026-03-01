"""
Elyan Anomaly Detector — System health anomaly detection

Monitors CPU, RAM, disk usage patterns and detects anomalies.
"""

import os
import time
from typing import Any, Dict, List
from utils.logger import get_logger

logger = get_logger("anomaly_detector")


class AnomalyDetector:
    """Detect system anomalies based on resource metrics."""

    def __init__(self):
        self.history: List[Dict[str, float]] = []
        self.thresholds = {
            "cpu_percent": 90.0,
            "memory_percent": 85.0,
            "disk_percent": 95.0,
        }
        self.alerts: List[Dict[str, Any]] = []

    async def check(self) -> Dict[str, Any]:
        """Run anomaly detection on current system state."""
        try:
            import psutil
        except ImportError:
            return {"success": False, "error": "psutil not installed"}

        metrics = {
            "cpu_percent": psutil.cpu_percent(interval=1),
            "memory_percent": psutil.virtual_memory().percent,
            "disk_percent": psutil.disk_usage("/").percent,
            "timestamp": time.time(),
        }

        self.history.append(metrics)
        if len(self.history) > 100:
            self.history = self.history[-100:]

        anomalies = []
        for key, threshold in self.thresholds.items():
            if metrics.get(key, 0) > threshold:
                anomaly = {
                    "type": key,
                    "value": metrics[key],
                    "threshold": threshold,
                    "severity": "critical" if metrics[key] > threshold + 5 else "warning",
                    "timestamp": metrics["timestamp"],
                }
                anomalies.append(anomaly)
                self.alerts.append(anomaly)
                logger.warning(f"Anomaly: {key}={metrics[key]}% (threshold={threshold}%)")

        # Check for high process count
        proc_count = len(psutil.pids())
        if proc_count > 500:
            anomalies.append({
                "type": "high_process_count",
                "value": proc_count,
                "threshold": 500,
                "severity": "warning",
            })

        return {
            "success": True,
            "metrics": metrics,
            "anomalies": anomalies,
            "anomaly_count": len(anomalies),
            "healthy": len(anomalies) == 0,
        }

    def get_alert_history(self, last_n: int = 20) -> List[Dict[str, Any]]:
        return self.alerts[-last_n:]


# Global instance
anomaly_detector = AnomalyDetector()
