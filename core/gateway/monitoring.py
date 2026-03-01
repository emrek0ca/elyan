import time
import asyncio
from typing import Dict, Any, Optional
from utils.logger import get_logger

logger = get_logger("adapter_monitoring")

class AdapterHealthMonitor:
    def __init__(self):
        self.stats: Dict[str, Dict[str, Any]] = {}

    def record_heartbeat(self, adapter_name: str):
        if adapter_name not in self.stats:
            self.stats[adapter_name] = {
                "status": "online",
                "last_heartbeat": time.time(),
                "error_count": 0,
                "latencies": []
            }
        else:
            self.stats[adapter_name]["last_heartbeat"] = time.time()
            self.stats[adapter_name]["status"] = "online"

    def record_error(self, adapter_name: str, error: str):
        if adapter_name not in self.stats:
            self.record_heartbeat(adapter_name)
        
        self.stats[adapter_name]["error_count"] += 1
        self.stats[adapter_name]["last_error"] = error
        self.stats[adapter_name]["status"] = "degraded" if self.stats[adapter_name]["error_count"] < 5 else "offline"
        logger.warning(f"Adapter {adapter_name} error: {error}")

    def get_status_report(self) -> Dict[str, Any]:
        now = time.time()
        report = {}
        for name, data in self.stats.items():
            # Auto-offline if no heartbeat for 5 mins
            if now - data["last_heartbeat"] > 300:
                data["status"] = "offline"
            report[name] = data
        return report

# Global instance
adapter_monitor = AdapterHealthMonitor()
