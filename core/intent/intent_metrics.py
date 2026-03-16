"""
Intent Metrics Tracker

Tracks per-tier performance, latency, confidence distributions, accuracy.
For analytics and optimization.
"""

from typing import Dict, Any, List
from collections import defaultdict, deque
from datetime import datetime
from utils.logger import get_logger
from .models import IntentResult

logger = get_logger("intent_metrics")


class IntentMetricsTracker:
    """Track intent system performance metrics."""

    def __init__(self, window_size: int = 1000):
        self.window_size = window_size

        # Tier performance
        self.tier_counts: Dict[str, int] = defaultdict(int)
        self.tier_latencies: Dict[str, deque] = defaultdict(lambda: deque(maxlen=window_size))
        self.tier_confidences: Dict[str, deque] = defaultdict(lambda: deque(maxlen=window_size))

        # Overall metrics
        self.total_routes: int = 0
        self.total_latencies: deque = deque(maxlen=window_size)
        self.confidence_distribution: Dict[str, int] = defaultdict(int)

        # Action performance
        self.action_counts: Dict[str, int] = defaultdict(int)
        self.action_confidence: Dict[str, float] = defaultdict(float)
        self.action_success: Dict[str, int] = defaultdict(int)

        # Error tracking
        self.error_counts: int = 0
        self.clarification_counts: int = 0

    def record_routing(self, result: IntentResult) -> None:
        """Record routing decision."""
        try:
            # Update tier stats
            tier = result.source_tier or "unknown"
            self.tier_counts[tier] += 1
            self.tier_latencies[tier].append(result.execution_time_ms)
            self.tier_confidences[tier].append(result.confidence)

            # Update overall stats
            self.total_routes += 1
            self.total_latencies.append(result.execution_time_ms)

            # Update action stats
            action = result.action
            self.action_counts[action] += 1
            self.action_confidence[action] = (
                self.action_confidence[action] * 0.9 + result.confidence * 0.1
            )

            # Track confidence bins
            conf_bin = f"{int(result.confidence * 10) * 10}%"
            self.confidence_distribution[conf_bin] += 1

            # Track clarifications
            if result.action == "clarify":
                self.clarification_counts += 1

        except Exception as e:
            logger.error(f"Failed to record routing metric: {e}")

    def record_success(self, action: str) -> None:
        """Record successful action execution."""
        self.action_success[action] += 1

    def record_error(self) -> None:
        """Record routing error."""
        self.error_counts += 1

    def get_summary(self) -> Dict[str, Any]:
        """Get summary metrics."""
        return {
            "total_routes": self.total_routes,
            "error_count": self.error_counts,
            "clarification_count": self.clarification_counts,
            "avg_latency_ms": sum(self.total_latencies) / len(self.total_latencies) if self.total_latencies else 0,
            "p99_latency_ms": self._percentile(self.total_latencies, 99),
            "tier_distribution": dict(self.tier_counts),
            "action_distribution": dict(self.action_counts),
            "confidence_distribution": dict(self.confidence_distribution)
        }

    def get_tier_stats(self, tier: str) -> Dict[str, Any]:
        """Get statistics for specific tier."""
        latencies = self.tier_latencies.get(tier, deque())
        confidences = self.tier_confidences.get(tier, deque())

        return {
            "tier": tier,
            "count": self.tier_counts.get(tier, 0),
            "avg_latency_ms": sum(latencies) / len(latencies) if latencies else 0,
            "max_latency_ms": max(latencies) if latencies else 0,
            "avg_confidence": sum(confidences) / len(confidences) if confidences else 0,
            "min_confidence": min(confidences) if confidences else 0
        }

    def get_action_stats(self, action: str) -> Dict[str, Any]:
        """Get statistics for specific action."""
        return {
            "action": action,
            "count": self.action_counts.get(action, 0),
            "success_count": self.action_success.get(action, 0),
            "avg_confidence": self.action_confidence.get(action, 0),
            "success_rate": (
                self.action_success.get(action, 0) / max(1, self.action_counts.get(action, 1))
            )
        }

    def get_top_actions(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get top actions by frequency."""
        sorted_actions = sorted(
            self.action_counts.items(),
            key=lambda x: x[1],
            reverse=True
        )
        return [
            self.get_action_stats(action)
            for action, _count in sorted_actions[:limit]
        ]

    def get_confidence_stats(self) -> Dict[str, Any]:
        """Get confidence distribution statistics."""
        confidences = list(self.total_latencies)
        if not confidences:
            return {}

        return {
            "avg_confidence": sum(confidences) / len(confidences),
            "min_confidence": min(confidences),
            "max_confidence": max(confidences),
            "distribution": dict(self.confidence_distribution)
        }

    def get_latency_stats(self) -> Dict[str, float]:
        """Get latency percentiles."""
        latencies = list(self.total_latencies)
        if not latencies:
            return {}

        return {
            "p50_ms": self._percentile(latencies, 50),
            "p75_ms": self._percentile(latencies, 75),
            "p90_ms": self._percentile(latencies, 90),
            "p99_ms": self._percentile(latencies, 99),
            "max_ms": max(latencies) if latencies else 0,
            "avg_ms": sum(latencies) / len(latencies) if latencies else 0
        }

    @staticmethod
    def _percentile(data: List[float], percentile: int) -> float:
        """Calculate percentile value."""
        if not data:
            return 0.0
        sorted_data = sorted(data)
        idx = (percentile / 100.0) * len(sorted_data)
        if idx % 1 == 0:
            return sorted_data[int(idx)]
        else:
            lower = sorted_data[int(idx)]
            upper = sorted_data[int(idx) + 1] if int(idx) + 1 < len(sorted_data) else lower
            return lower + (upper - lower) * (idx % 1)

    def reset(self) -> None:
        """Reset all metrics."""
        self.tier_counts.clear()
        self.tier_latencies.clear()
        self.tier_confidences.clear()
        self.total_routes = 0
        self.total_latencies.clear()
        self.confidence_distribution.clear()
        self.action_counts.clear()
        self.action_confidence.clear()
        self.action_success.clear()
        self.error_counts = 0
        self.clarification_counts = 0
        logger.info("Intent metrics reset")
