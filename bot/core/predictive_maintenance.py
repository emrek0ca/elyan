"""
Predictive System Maintenance Engine
Predicts system issues before they happen, proactive maintenance
"""

import asyncio
import time
import psutil
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from collections import deque
from enum import Enum
import statistics

from utils.logger import get_logger

logger = get_logger("predictive_maintenance")


class PredictionSeverity(Enum):
    """Severity of predicted issues"""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class ResourceMetric:
    """Resource usage metric at a point in time"""
    timestamp: float
    cpu_percent: float
    memory_percent: float
    disk_percent: float
    network_sent: int
    network_recv: int


@dataclass
class Prediction:
    """Predicted system issue"""
    issue_type: str
    severity: PredictionSeverity
    predicted_time: float  # When issue will occur (timestamp)
    confidence: float  # 0-100%
    description: str
    recommendation: str
    prevention_action: Optional[str] = None


class PredictiveMaintenance:
    """
    Predictive System Maintenance Engine
    - Monitors system resources over time
    - Predicts issues before they happen
    - Suggests proactive maintenance
    - Auto-triggers preventive actions
    """

    def __init__(self):
        self.metrics_history: deque = deque(maxlen=1000)  # Last 1000 measurements
        self.predictions: List[Prediction] = []
        self.monitoring_active = False
        self.prediction_interval = 300  # Predict every 5 minutes

        # Thresholds
        self.critical_memory = 95  # %
        self.critical_disk = 95  # %
        self.critical_cpu = 95  # %
        self.warning_memory = 85  # %
        self.warning_disk = 85  # %

        # Prediction models (simple linear extrapolation for now)
        self.prediction_window = 3600  # 1 hour ahead

        logger.info("Predictive Maintenance Engine initialized")

    async def start_monitoring(self):
        """Start continuous resource monitoring"""
        self.monitoring_active = True
        logger.info("Predictive monitoring started")

        while self.monitoring_active:
            try:
                # Collect metrics
                await self._collect_metrics()

                # Run predictions every N seconds
                if len(self.metrics_history) >= 10:  # Need at least 10 data points
                    await self._run_predictions()

                await asyncio.sleep(30)  # Collect every 30 seconds

            except Exception as e:
                logger.error(f"Monitoring error: {e}")
                await asyncio.sleep(30)

    def stop_monitoring(self):
        """Stop monitoring"""
        self.monitoring_active = False
        logger.info("Predictive monitoring stopped")

    async def _collect_metrics(self):
        """Collect system metrics"""
        try:
            cpu = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            network = psutil.net_io_counters()

            metric = ResourceMetric(
                timestamp=time.time(),
                cpu_percent=cpu,
                memory_percent=memory.percent,
                disk_percent=disk.percent,
                network_sent=network.bytes_sent,
                network_recv=network.bytes_recv
            )

            self.metrics_history.append(metric)

        except Exception as e:
            logger.error(f"Metric collection error: {e}")

    async def _run_predictions(self):
        """Run predictive analysis"""
        self.predictions.clear()

        # Predict memory exhaustion
        memory_pred = await self._predict_memory_exhaustion()
        if memory_pred:
            self.predictions.append(memory_pred)

        # Predict disk full
        disk_pred = await self._predict_disk_full()
        if disk_pred:
            self.predictions.append(disk_pred)

        # Predict performance degradation
        perf_pred = await self._predict_performance_degradation()
        if perf_pred:
            self.predictions.append(perf_pred)

        # Predict memory leak
        leak_pred = await self._predict_memory_leak()
        if leak_pred:
            self.predictions.append(leak_pred)

        # Log predictions
        for pred in self.predictions:
            if pred.severity == PredictionSeverity.CRITICAL:
                logger.warning(f"CRITICAL prediction: {pred.description}")

    async def _predict_memory_exhaustion(self) -> Optional[Prediction]:
        """Predict when memory will be exhausted"""
        if len(self.metrics_history) < 20:
            return None

        # Get recent memory trends
        recent = list(self.metrics_history)[-20:]
        memory_values = [m.memory_percent for m in recent]

        # Calculate trend (simple linear regression)
        trend = self._calculate_trend(memory_values)

        if trend > 0.5:  # Memory increasing
            current = memory_values[-1]

            # Extrapolate to critical threshold
            time_to_critical = (self.critical_memory - current) / trend

            if time_to_critical > 0 and time_to_critical < 3600:  # Within 1 hour
                predicted_time = time.time() + time_to_critical

                return Prediction(
                    issue_type="memory_exhaustion",
                    severity=PredictionSeverity.CRITICAL if time_to_critical < 600 else PredictionSeverity.WARNING,
                    predicted_time=predicted_time,
                    confidence=min(80, trend * 10),
                    description=f"Memory exhaustion predicted in {int(time_to_critical/60)} minutes",
                    recommendation="Clear caches, close unused applications, restart services",
                    prevention_action="clear_cache"
                )

        return None

    async def _predict_disk_full(self) -> Optional[Prediction]:
        """Predict when disk will be full"""
        if len(self.metrics_history) < 50:
            return None

        recent = list(self.metrics_history)[-50:]
        disk_values = [m.disk_percent for m in recent]

        trend = self._calculate_trend(disk_values)

        if trend > 0.01:  # Disk usage increasing
            current = disk_values[-1]
            time_to_full = (self.critical_disk - current) / trend

            if time_to_full > 0 and time_to_full < 86400:  # Within 24 hours
                predicted_time = time.time() + time_to_full

                return Prediction(
                    issue_type="disk_full",
                    severity=PredictionSeverity.CRITICAL if time_to_full < 3600 else PredictionSeverity.WARNING,
                    predicted_time=predicted_time,
                    confidence=min(75, trend * 100),
                    description=f"Disk full predicted in {int(time_to_full/3600)} hours",
                    recommendation="Clean up temporary files, delete old logs, move large files",
                    prevention_action="cleanup_temp"
                )

        return None

    async def _predict_performance_degradation(self) -> Optional[Prediction]:
        """Predict performance degradation"""
        if len(self.metrics_history) < 30:
            return None

        recent = list(self.metrics_history)[-30:]
        cpu_values = [m.cpu_percent for m in recent]

        avg_cpu = statistics.mean(cpu_values)
        cpu_stdev = statistics.stdev(cpu_values) if len(cpu_values) > 1 else 0

        # High average CPU with high variance indicates unstable performance
        if avg_cpu > 70 and cpu_stdev > 15:
            return Prediction(
                issue_type="performance_degradation",
                severity=PredictionSeverity.WARNING,
                predicted_time=time.time() + 1800,  # 30 min
                confidence=60,
                description="Performance degradation detected (high CPU variance)",
                recommendation="Check for runaway processes, optimize background tasks",
                prevention_action="optimize_processes"
            )

        return None

    async def _predict_memory_leak(self) -> Optional[Prediction]:
        """Predict memory leak"""
        if len(self.metrics_history) < 100:
            return None

        # Look at long-term memory trend
        all_metrics = list(self.metrics_history)
        memory_values = [m.memory_percent for m in all_metrics]

        # Calculate trend over entire history
        long_term_trend = self._calculate_trend(memory_values)

        # Memory leak: consistent slow increase
        if long_term_trend > 0.1:  # Steady increase
            # Check if it's accelerating
            recent = memory_values[-20:]
            recent_trend = self._calculate_trend(recent)

            if recent_trend > long_term_trend * 1.5:
                return Prediction(
                    issue_type="memory_leak",
                    severity=PredictionSeverity.WARNING,
                    predicted_time=time.time() + 7200,  # 2 hours
                    confidence=70,
                    description="Potential memory leak detected (accelerating memory growth)",
                    recommendation="Restart application, check for memory leaks in code",
                    prevention_action="restart_if_needed"
                )

        return None

    def _calculate_trend(self, values: List[float]) -> float:
        """Calculate trend (slope) using simple linear regression"""
        if len(values) < 2:
            return 0

        n = len(values)
        x = list(range(n))
        y = values

        # Linear regression: y = mx + b
        x_mean = statistics.mean(x)
        y_mean = statistics.mean(y)

        numerator = sum((x[i] - x_mean) * (y[i] - y_mean) for i in range(n))
        denominator = sum((x[i] - x_mean) ** 2 for i in range(n))

        if denominator == 0:
            return 0

        slope = numerator / denominator
        return slope

    async def trigger_preventive_action(self, action: str):
        """Trigger preventive maintenance action"""
        logger.info(f"Triggering preventive action: {action}")

        try:
            if action == "clear_cache":
                from .smart_cache import get_smart_cache
                cache = get_smart_cache()
                cache.clear()
                logger.info("Cache cleared as preventive action")

            elif action == "cleanup_temp":
                import tempfile
                import shutil
                temp_dir = tempfile.gettempdir()
                cleaned = 0
                for item in os.listdir(temp_dir):
                    try:
                        path = os.path.join(temp_dir, item)
                        if os.path.isfile(path):
                            # Only delete files older than 1 day
                            if time.time() - os.path.getmtime(path) > 86400:
                                os.unlink(path)
                                cleaned += 1
                    except:
                        pass
                logger.info(f"Cleaned {cleaned} temp files")

            elif action == "optimize_processes":
                # Run garbage collection
                import gc
                gc.collect()
                logger.info("Garbage collection performed")

            elif action == "restart_if_needed":
                # This would restart the service (implement carefully)
                logger.info("Restart recommendation logged")

        except Exception as e:
            logger.error(f"Preventive action failed: {e}")

    def get_predictions(self) -> List[Dict[str, Any]]:
        """Get current predictions"""
        return [
            {
                "issue_type": p.issue_type,
                "severity": p.severity.value,
                "predicted_time": datetime.fromtimestamp(p.predicted_time).strftime("%Y-%m-%d %H:%M:%S"),
                "time_until": int(p.predicted_time - time.time()),
                "confidence": f"{p.confidence:.0f}%",
                "description": p.description,
                "recommendation": p.recommendation
            }
            for p in self.predictions
        ]

    def get_resource_trends(self) -> Dict[str, Any]:
        """Get resource usage trends"""
        if len(self.metrics_history) < 10:
            return {"error": "Insufficient data"}

        recent = list(self.metrics_history)[-50:]

        cpu_values = [m.cpu_percent for m in recent]
        memory_values = [m.memory_percent for m in recent]
        disk_values = [m.disk_percent for m in recent]

        return {
            "cpu": {
                "current": cpu_values[-1],
                "avg": statistics.mean(cpu_values),
                "max": max(cpu_values),
                "trend": self._calculate_trend(cpu_values)
            },
            "memory": {
                "current": memory_values[-1],
                "avg": statistics.mean(memory_values),
                "max": max(memory_values),
                "trend": self._calculate_trend(memory_values)
            },
            "disk": {
                "current": disk_values[-1],
                "avg": statistics.mean(disk_values),
                "trend": self._calculate_trend(disk_values)
            }
        }

    def get_summary(self) -> Dict[str, Any]:
        """Get maintenance summary"""
        critical = sum(1 for p in self.predictions if p.severity == PredictionSeverity.CRITICAL)
        warnings = sum(1 for p in self.predictions if p.severity == PredictionSeverity.WARNING)

        return {
            "monitoring_active": self.monitoring_active,
            "metrics_collected": len(self.metrics_history),
            "active_predictions": len(self.predictions),
            "critical_predictions": critical,
            "warning_predictions": warnings,
            "data_points": len(self.metrics_history)
        }


# Global instance
_predictive_maintenance: Optional[PredictiveMaintenance] = None


def get_predictive_maintenance() -> PredictiveMaintenance:
    """Get or create global predictive maintenance instance"""
    global _predictive_maintenance
    if _predictive_maintenance is None:
        _predictive_maintenance = PredictiveMaintenance()
    return _predictive_maintenance
