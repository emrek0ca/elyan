from __future__ import annotations

from typing import Any, Dict, List

from core.observability.dora_metrics import MetricsCollector


class CapacityPlanner:
    def __init__(self, metrics_collector: MetricsCollector):
        self.metrics_collector = metrics_collector

    def recommended_concurrent_tasks(self, target_lead_time_ms: int = 3000) -> int:
        snapshot = self.metrics_collector.compute_snapshot(period_hours=1.0)
        avg_time = snapshot.avg_time_to_first_result_ms
        if avg_time > target_lead_time_ms * 1.5:
            return 2
        if avg_time < target_lead_time_ms * 0.5:
            return 5
        return 3

    def should_spawn_new_agent(self, current_queue_depth: int) -> bool:
        snapshot = self.metrics_collector.compute_snapshot(period_hours=1.0)
        return current_queue_depth > 5 and snapshot.avg_time_to_first_result_ms > 4000

    def get_toil_report(self) -> Dict[str, Any]:
        return {
            "task_categories": [],
            "frequent_questions": [],
            "frequent_approvals": [],
        }
