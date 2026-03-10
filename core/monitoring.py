"""
core/monitoring.py
─────────────────────────────────────────────────────────────────────────────
Centralized system resource monitoring for Elyan.
Provides health checks for CPU, RAM, Disk, and Battery.
"""

from __future__ import annotations
import psutil
import time
from dataclasses import dataclass
from typing import Dict, Any, Optional, List
from collections import Counter
from utils.logger import get_logger

logger = get_logger("monitoring")

@dataclass
class SystemHealth:
    cpu_percent: float
    ram_percent: float
    disk_percent: float
    battery_percent: Optional[float]
    is_on_ac: bool
    status: str  # healthy | warning | critical
    issues: list[str]

class ResourceMonitor:
    def __init__(self):
        self.thresholds = {
            "cpu": {"warning": 80.0, "critical": 95.0},
            "ram": {"warning": 85.0, "critical": 95.0},
            "disk": {"warning": 90.0, "critical": 98.0},
            "battery": {"warning": 15.0, "critical": 5.0}
        }

    def get_health_snapshot(self) -> SystemHealth:
        cpu = psutil.cpu_percent(interval=0.1)
        ram = psutil.virtual_memory().percent
        disk = psutil.disk_usage('/').percent
        
        battery = psutil.sensors_battery()
        batt_pct = battery.percent if battery else None
        is_on_ac = battery.power_plugged if battery else True
        
        issues = []
        status = "healthy"
        
        # Check CPU
        if cpu > self.thresholds["cpu"]["critical"]:
            status = "critical"
            issues.append(f"Kritik CPU kullanımı: %{cpu}")
        elif cpu > self.thresholds["cpu"]["warning"]:
            status = "warning" if status != "critical" else "critical"
            issues.append(f"Yüksek CPU kullanımı: %{cpu}")
            
        # Check RAM
        if ram > self.thresholds["ram"]["critical"]:
            status = "critical"
            issues.append(f"Kritik Bellek kullanımı: %{ram}")
        elif ram > self.thresholds["ram"]["warning"]:
            status = "warning" if status != "critical" else "critical"
            issues.append(f"Yüksek Bellek kullanımı: %{ram}")
            
        # Check Battery
        if batt_pct is not None and not is_on_ac:
            if batt_pct < self.thresholds["battery"]["critical"]:
                status = "critical"
                issues.append(f"Kritik Pil seviyesi: %{batt_pct}")
            elif batt_pct < self.thresholds["battery"]["warning"]:
                status = "warning" if status != "critical" else "critical"
                issues.append(f"Düşük Pil seviyesi: %{batt_pct}")
                
        return SystemHealth(
            cpu_percent=cpu,
            ram_percent=ram,
            disk_percent=disk,
            battery_percent=batt_pct,
            is_on_ac=is_on_ac,
            status=status,
            issues=issues
        )


class MonitoringTracker:
    """Lightweight operational telemetry tracker for legacy task engine hooks."""

    def __init__(self):
        self._operations_total = 0
        self._operations_failed = 0
        self._errors_total = 0
        self._last_operation: Dict[str, Any] = {}
        self._last_error: Dict[str, Any] = {}
        self._recent_errors: List[Dict[str, Any]] = []
        self._orchestration_total = 0
        self._orchestration_selected: Counter[str] = Counter()
        self._orchestration_reasons: Counter[str] = Counter()
        self._recent_orchestration: List[Dict[str, Any]] = []
        self._recent_pipeline_jobs: List[Dict[str, Any]] = []

    def record_operation(
        self,
        *,
        operation: str,
        success: bool,
        duration_ms: int,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._operations_total += 1
        if not success:
            self._operations_failed += 1
        self._last_operation = {
            "operation": str(operation or "unknown"),
            "success": bool(success),
            "duration_ms": int(duration_ms or 0),
            "metadata": dict(metadata or {}),
            "timestamp": time.time(),
        }

    def record_error(
        self,
        *,
        component: str,
        error_msg: str,
        error_type: str = "runtime_error",
    ) -> None:
        self._errors_total += 1
        payload = {
            "component": str(component or "unknown"),
            "error_msg": str(error_msg or ""),
            "error_type": str(error_type or "runtime_error"),
            "timestamp": time.time(),
        }
        self._last_error = payload
        self._recent_errors.append(payload)
        if len(self._recent_errors) > 50:
            self._recent_errors.pop(0)

    def get_snapshot(self) -> Dict[str, Any]:
        return {
            "operations_total": self._operations_total,
            "operations_failed": self._operations_failed,
            "errors_total": self._errors_total,
            "last_operation": dict(self._last_operation),
            "last_error": dict(self._last_error),
            "recent_errors": list(self._recent_errors[-10:]),
            "orchestration": self.get_orchestration_summary(),
            "pipeline_jobs": self.get_pipeline_job_summary(),
        }

    def get_health_status(self) -> Dict[str, Any]:
        """Dashboard-compatible health status summary."""
        total = self._operations_total or 1
        success = total - self._operations_failed
        rate = f"{(success / total) * 100:.0f}%"
        return {
            "total_operations": self._operations_total,
            "failed_operations": self._operations_failed,
            "success_rate": rate,
            "errors_total": self._errors_total,
            "status": "healthy" if self._operations_failed < total * 0.1 else "degraded",
        }

    def get_dashboard(self) -> Dict[str, Any]:
        """Dashboard-compatible metrics summary."""
        last_latency = self._last_operation.get("duration_ms", 0)
        return {
            "metrics_summary": {
                "llm_latency": {"avg": last_latency, "max": last_latency, "min": last_latency},
            },
            "operations": self.get_snapshot(),
        }

    def record_orchestration_decision(
        self,
        *,
        mode: str,
        selected: bool,
        reason: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._orchestration_total += 1
        mode_key = str(mode or "single_agent").strip().lower() or "single_agent"
        if selected:
            self._orchestration_selected[mode_key] += 1
        reason_key = str(reason or "unspecified").strip().lower() or "unspecified"
        self._orchestration_reasons[reason_key] += 1
        event = {
            "timestamp": time.time(),
            "mode": mode_key,
            "selected": bool(selected),
            "reason": reason_key,
            "metadata": dict(metadata or {}),
        }
        self._recent_orchestration.append(event)
        if len(self._recent_orchestration) > 50:
            self._recent_orchestration.pop(0)

    def get_orchestration_summary(self) -> Dict[str, Any]:
        total = max(1, int(self._orchestration_total))
        selected_total = sum(self._orchestration_selected.values())
        return {
            "decisions_total": int(self._orchestration_total),
            "selected_total": int(selected_total),
            "selection_rate_pct": round((selected_total / total) * 100, 1),
            "selected_by_mode": dict(self._orchestration_selected),
            "reason_counts": dict(self._orchestration_reasons),
            "recent": list(self._recent_orchestration[-10:]),
        }

    def record_pipeline_job(self, *, payload: Dict[str, Any]) -> None:
        item = dict(payload or {})
        item["timestamp"] = time.time()
        self._recent_pipeline_jobs.append(item)
        if len(self._recent_pipeline_jobs) > 100:
            self._recent_pipeline_jobs.pop(0)

    def get_pipeline_job_summary(self) -> Dict[str, Any]:
        rows = list(self._recent_pipeline_jobs[-20:])
        if not rows:
            return {
                "jobs_total": 0,
                "avg_tool_success_rate": 0.0,
                "avg_verify_pass_rate": 0.0,
                "avg_ttfa_ms": 0,
                "recent": [],
            }
        def _avg(key: str) -> float:
            vals = [float(r.get(key, 0.0) or 0.0) for r in rows]
            return sum(vals) / max(1, len(vals))
        return {
            "jobs_total": len(rows),
            "avg_tool_success_rate": round(_avg("tool_success_rate"), 3),
            "avg_verify_pass_rate": round(_avg("verify_pass_rate"), 3),
            "avg_ttfa_ms": int(_avg("ttfa_ms")),
            "recent": rows[-10:],
        }


_monitor = ResourceMonitor()
_telemetry = MonitoringTracker()

def get_resource_monitor() -> ResourceMonitor:
    return _monitor


def get_monitoring() -> MonitoringTracker:
    """Legacy compatibility: returns process-level telemetry tracker."""
    return _telemetry


def record_operation(
    *,
    operation: str,
    success: bool,
    duration_ms: int,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Legacy compatibility wrapper for task_engine metrics recording."""
    _telemetry.record_operation(
        operation=operation,
        success=success,
        duration_ms=duration_ms,
        metadata=metadata,
    )


def record_error(
    *,
    component: str,
    error_msg: str,
    error_type: str = "runtime_error",
) -> None:
    """Legacy compatibility wrapper for task_engine error recording."""
    _telemetry.record_error(
        component=component,
        error_msg=error_msg,
        error_type=error_type,
    )


def record_orchestration_decision(
    *,
    mode: str,
    selected: bool,
    reason: str = "",
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    _telemetry.record_orchestration_decision(
        mode=mode,
        selected=selected,
        reason=reason,
        metadata=metadata,
    )


def record_pipeline_job(payload: Dict[str, Any]) -> None:
    _telemetry.record_pipeline_job(payload=payload)
