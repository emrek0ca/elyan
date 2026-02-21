"""
core/monitoring.py
─────────────────────────────────────────────────────────────────────────────
Centralized system resource monitoring for Elyan.
Provides health checks for CPU, RAM, Disk, and Battery.
"""

from __future__ import annotations
import psutil
import platform
import time
from dataclasses import dataclass
from typing import Dict, Any, Optional
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

_monitor = ResourceMonitor()

def get_resource_monitor() -> ResourceMonitor:
    return _monitor
