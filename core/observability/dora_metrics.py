from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from core.events.event_store import EventStore, EventType, get_event_store


@dataclass(slots=True)
class DORASnapshot:
    period_start: float
    period_end: float
    task_completion_rate: float
    avg_time_to_first_result_ms: float
    task_failure_rate: float
    avg_recovery_time_ms: float
    approval_rate: float
    autonomous_decision_rate: float
    cache_hit_rate: float
    avg_tool_selection_confidence: float

    def performance_level(self) -> str:
        score = (
            self.task_completion_rate * 0.3
            + (1 - self.task_failure_rate) * 0.3
            + self.autonomous_decision_rate * 0.2
            + self.cache_hit_rate * 0.2
        )
        if score >= 0.85:
            return "Elite"
        if score >= 0.7:
            return "High"
        if score >= 0.5:
            return "Medium"
        return "Low"

    def improvement_suggestions(self) -> List[str]:
        suggestions: List[str] = []
        if self.approval_rate > 0.3:
            suggestions.append("UncertaintyEngine eşiğini düşür")
        if self.cache_hit_rate < 0.4:
            suggestions.append("HTN method_library'yi genişlet")
        if self.avg_time_to_first_result_ms > 5000:
            suggestions.append("AsyncExecutor priority'yi optimize et")
        if self.task_failure_rate > 0.15:
            suggestions.append("CircuitBreaker loglarına bak")
        return suggestions


class MetricsCollector:
    def __init__(self, event_store: EventStore | None = None):
        self.event_store = event_store or get_event_store()

    def compute_snapshot(self, period_hours: float = 24.0) -> DORASnapshot:
        import time as _time

        period_end = _time.time()
        period_start = period_end - (period_hours * 3600.0)
        received = self.event_store.query_by_type(EventType.TASK_RECEIVED, since=period_start, limit=10000)
        completed = self.event_store.query_by_type(EventType.TASK_COMPLETED, since=period_start, limit=10000)
        failed = self.event_store.query_by_type(EventType.TASK_FAILED, since=period_start, limit=10000)
        approval_requested = self.event_store.query_by_type(EventType.APPROVAL_REQUESTED, since=period_start, limit=10000)
        tool_succeeded = self.event_store.query_by_type(EventType.TOOL_SUCCEEDED, since=period_start, limit=10000)

        completion_rate = len(completed) / max(len(received), 1)
        failure_rate = len(failed) / max(len(received), 1)
        approval_rate = len(approval_requested) / max(len(received), 1)
        autonomous_rate = max(0.0, 1.0 - approval_rate)
        cache_hit_rate = 0.0
        tool_confidence = 0.0

        first_result_latencies: List[float] = []
        recovery_times: List[float] = []
        received_by_aggregate = {event.aggregate_id: event for event in received}
        for event in completed:
            start = received_by_aggregate.get(event.aggregate_id)
            if start:
                first_result_latencies.append(max(0.0, (event.timestamp - start.timestamp) * 1000.0))
        for event in failed:
            start = received_by_aggregate.get(event.aggregate_id)
            if start:
                recovery_times.append(max(0.0, (event.timestamp - start.timestamp) * 1000.0))

        if tool_succeeded:
            tool_confidence = min(1.0, sum(1.0 for _ in tool_succeeded) / max(len(received), 1))

        return DORASnapshot(
            period_start=period_start,
            period_end=period_end,
            task_completion_rate=completion_rate,
            avg_time_to_first_result_ms=(sum(first_result_latencies) / len(first_result_latencies)) if first_result_latencies else 0.0,
            task_failure_rate=failure_rate,
            avg_recovery_time_ms=(sum(recovery_times) / len(recovery_times)) if recovery_times else 0.0,
            approval_rate=approval_rate,
            autonomous_decision_rate=autonomous_rate,
            cache_hit_rate=cache_hit_rate,
            avg_tool_selection_confidence=tool_confidence,
        )
