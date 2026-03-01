"""
core/reasoning/stage_profiler.py
─────────────────────────────────────────────────────────────────────────────
Decorator-based profiler for measuring stage performance and resource usage.
"""

import time
import functools
from typing import Any, Dict, List
from utils.logger import get_logger

logger = get_logger("stage_profiler")

class StageProfiler:
    """
    Tracks execution metrics for pipeline stages.
    """
    def __init__(self):
        self.metrics: Dict[str, List[Dict[str, Any]]] = {}

    def profile_stage(self, stage_name: str):
        """Decorator to profile a stage run."""
        def decorator(func):
            @functools.wraps(func)
            async def wrapper(*args, **kwargs):
                start_time = time.time()
                try:
                    result = await func(*args, **kwargs)
                    duration = time.time() - start_time
                    
                    self.record_metric(stage_name, {
                        "duration_s": duration,
                        "status": "success"
                    })
                    return result
                except Exception as e:
                    duration = time.time() - start_time
                    self.record_metric(stage_name, {
                        "duration_s": duration,
                        "status": "error",
                        "error": str(e)
                    })
                    raise e
            return wrapper
        return decorator

    def record_metric(self, stage_name: str, data: Dict[str, Any]):
        """Records a single metric entry."""
        if stage_name not in self.metrics:
            self.metrics[stage_name] = []
        
        data["timestamp"] = time.time()
        self.metrics[stage_name].append(data)
        
        logger.info(f"📊 [Profiler] Stage '{stage_name}': {data['duration_s']:.3f}s ({data['status']})")
        
        # Optionally broadcast to dashboard if needed
        try:
            from core.gateway.server import broadcast_to_dashboard
            broadcast_to_dashboard("telemetry", {"profiler": {stage_name: data}})
        except:
            pass

    def get_averages(self) -> Dict[str, float]:
        """Calculates average duration per stage."""
        averages = {}
        for stage, entries in self.metrics.items():
            durations = [e["duration_s"] for e in entries if e["status"] == "success"]
            if durations:
                averages[stage] = sum(durations) / len(durations)
        return averages

# Global instance
stage_profiler = StageProfiler()
