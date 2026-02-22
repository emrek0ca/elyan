"""
core/genesis/self_diagnostic.py
─────────────────────────────────────────────────────────────────────────────
Self Diagnostic Health Monitor (Phase 29).
Elyan monitors its OWN health (CPU, RAM, disk, response latency) and 
proactively warns the user or auto-scales resources if thresholds are breached.
"""

import asyncio
import time
import psutil
from dataclasses import dataclass
from utils.logger import get_logger

logger = get_logger("self_diagnostic")

@dataclass 
class HealthReport:
    cpu_percent: float
    ram_used_mb: float
    ram_total_mb: float
    disk_free_gb: float
    avg_response_ms: float
    uptime_hours: float
    status: str  # healthy, degraded, critical

class SelfDiagnostic:
    def __init__(self):
        self._start_time = time.time()
        self._response_times: list = []
        self._running = False
        
    def record_response_time(self, elapsed_ms: float):
        self._response_times.append(elapsed_ms)
        if len(self._response_times) > 100:
            self._response_times = self._response_times[-100:]
    
    def get_health_report(self) -> HealthReport:
        cpu = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        
        avg_resp = sum(self._response_times) / max(len(self._response_times), 1)
        uptime = (time.time() - self._start_time) / 3600.0
        
        # Determine status
        if cpu > 90 or mem.percent > 90:
            status = "critical"
        elif cpu > 70 or mem.percent > 75 or avg_resp > 5000:
            status = "degraded"
        else:
            status = "healthy"
        
        return HealthReport(
            cpu_percent=cpu,
            ram_used_mb=mem.used / (1024**2),
            ram_total_mb=mem.total / (1024**2),
            disk_free_gb=disk.free / (1024**3),
            avg_response_ms=avg_resp,
            uptime_hours=round(uptime, 2),
            status=status
        )
    
    async def _monitor_loop(self):
        self._running = True
        logger.info("💊 SelfDiagnostic Online — Monitoring Elyan's vitals...")
        
        while self._running:
            report = self.get_health_report()
            
            if report.status == "critical":
                logger.error(
                    f"🚨 CRITICAL: CPU={report.cpu_percent}% RAM={report.ram_used_mb:.0f}MB "
                    f"Disk={report.disk_free_gb:.1f}GB Free"
                )
            elif report.status == "degraded":
                logger.warning(
                    f"⚠️ DEGRADED: CPU={report.cpu_percent}% "
                    f"AvgResp={report.avg_response_ms:.0f}ms"
                )
            else:
                logger.debug(
                    f"✅ HEALTHY: CPU={report.cpu_percent}% "
                    f"RAM={report.ram_used_mb:.0f}MB "
                    f"Uptime={report.uptime_hours}h"
                )
            
            await asyncio.sleep(30.0)
    
    def start(self):
        if not self._running:
            asyncio.create_task(self._monitor_loop())
    
    def stop(self):
        self._running = False

# Global singleton
diagnostics = SelfDiagnostic()
