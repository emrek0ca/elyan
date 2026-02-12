"""
Advanced Analytics Engine
Metrics collection, trend analysis, insights generation
"""

import time
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from collections import defaultdict, deque
from dataclasses import dataclass, asdict
import statistics

from utils.logger import get_logger

logger = get_logger("analytics")


@dataclass
class Metric:
    """Represents a metric data point"""
    name: str
    value: float
    timestamp: float
    tags: Dict[str, str]


@dataclass
class Trend:
    """Represents a trend analysis"""
    metric_name: str
    direction: str  # up, down, stable
    change_percent: float
    current_value: float
    previous_value: float
    period: str  # hour, day, week


class AdvancedAnalytics:
    """
    Advanced Analytics Engine
    - Real-time metrics collection
    - Trend analysis
    - Insight generation
    - Performance profiling
    """

    def __init__(self):
        self.metrics: Dict[str, deque] = defaultdict(lambda: deque(maxlen=1000))
        self.counters: Dict[str, int] = defaultdict(int)
        self.timers: Dict[str, List[float]] = defaultdict(list)
        self.trends: List[Trend] = []

        # Time windows for analysis
        self.windows = {
            "1min": 60,
            "5min": 300,
            "15min": 900,
            "1hour": 3600,
            "1day": 86400,
            "1week": 604800
        }

        logger.info("Advanced Analytics Engine initialized")

    def record_metric(
        self,
        name: str,
        value: float,
        tags: Optional[Dict[str, str]] = None
    ):
        """Record a metric data point"""
        metric = Metric(
            name=name,
            value=value,
            timestamp=time.time(),
            tags=tags or {}
        )

        self.metrics[name].append(metric)

    def increment_counter(self, name: str, amount: int = 1):
        """Increment a counter"""
        self.counters[name] += amount

    def record_timing(self, name: str, duration_ms: float):
        """Record timing information"""
        self.timers[name].append(duration_ms)

        # Keep only last 1000 timings
        if len(self.timers[name]) > 1000:
            self.timers[name] = self.timers[name][-1000:]

    def get_metric_stats(
        self,
        name: str,
        window: str = "1hour"
    ) -> Optional[Dict[str, Any]]:
        """Get statistics for a metric"""
        if name not in self.metrics:
            return None

        window_seconds = self.windows.get(window, 3600)
        cutoff_time = time.time() - window_seconds

        # Filter metrics within window
        recent_metrics = [
            m for m in self.metrics[name]
            if m.timestamp >= cutoff_time
        ]

        if not recent_metrics:
            return None

        values = [m.value for m in recent_metrics]

        return {
            "count": len(values),
            "min": min(values),
            "max": max(values),
            "mean": statistics.mean(values),
            "median": statistics.median(values),
            "stdev": statistics.stdev(values) if len(values) > 1 else 0,
            "current": values[-1],
            "window": window
        }

    def get_timing_stats(self, name: str) -> Optional[Dict[str, Any]]:
        """Get timing statistics"""
        if name not in self.timers or not self.timers[name]:
            return None

        timings = self.timers[name]

        return {
            "count": len(timings),
            "min": min(timings),
            "max": max(timings),
            "mean": statistics.mean(timings),
            "median": statistics.median(timings),
            "p95": statistics.quantiles(timings, n=20)[18] if len(timings) > 20 else max(timings),
            "p99": statistics.quantiles(timings, n=100)[98] if len(timings) > 100 else max(timings)
        }

    def analyze_trends(self) -> List[Trend]:
        """Analyze trends for all metrics"""
        trends = []

        for name in self.metrics.keys():
            # Hourly trend
            hour_trend = self._calculate_trend(name, "1hour")
            if hour_trend:
                trends.append(hour_trend)

            # Daily trend
            day_trend = self._calculate_trend(name, "1day")
            if day_trend:
                trends.append(day_trend)

        self.trends = trends
        return trends

    def _calculate_trend(
        self,
        metric_name: str,
        period: str
    ) -> Optional[Trend]:
        """Calculate trend for a specific period"""
        window_seconds = self.windows.get(period, 3600)
        now = time.time()

        # Split period in half
        half_window = window_seconds / 2
        midpoint = now - half_window
        cutoff = now - window_seconds

        # Get metrics for each half
        recent_half = [
            m.value for m in self.metrics[metric_name]
            if m.timestamp >= midpoint
        ]

        older_half = [
            m.value for m in self.metrics[metric_name]
            if cutoff <= m.timestamp < midpoint
        ]

        if not recent_half or not older_half:
            return None

        current_avg = statistics.mean(recent_half)
        previous_avg = statistics.mean(older_half)

        # Calculate change
        if previous_avg == 0:
            change_percent = 0
        else:
            change_percent = ((current_avg - previous_avg) / previous_avg) * 100

        # Determine direction
        if abs(change_percent) < 5:  # Less than 5% change is stable
            direction = "stable"
        elif change_percent > 0:
            direction = "up"
        else:
            direction = "down"

        return Trend(
            metric_name=metric_name,
            direction=direction,
            change_percent=change_percent,
            current_value=current_avg,
            previous_value=previous_avg,
            period=period
        )

    def generate_insights(self) -> List[str]:
        """Generate insights from metrics and trends"""
        insights = []

        # Performance insights
        for name, timings in self.timers.items():
            if timings:
                avg_time = statistics.mean(timings)
                if avg_time > 5000:  # >5 seconds
                    insights.append(f"Yavaş işlem tespit edildi: {name} ({avg_time:.0f}ms ortalama)")
                elif avg_time > 1000:  # >1 second
                    insights.append(f"Optimizasyon fırsatı: {name} ({avg_time:.0f}ms)")

        # Trend insights
        for trend in self.trends:
            if trend.period == "1hour" and abs(trend.change_percent) > 50:
                direction_text = "arttı" if trend.direction == "up" else "azaldı"
                insights.append(
                    f"{trend.metric_name} son 1 saatte %{abs(trend.change_percent):.0f} {direction_text}"
                )

        # Counter insights
        for name, count in self.counters.items():
            if "error" in name.lower() and count > 10:
                insights.append(f"Yüksek hata sayısı: {name} ({count} kez)")

        return insights

    def get_dashboard_data(self) -> Dict[str, Any]:
        """Get comprehensive dashboard data"""
        # Top metrics
        top_metrics = {}
        for name in list(self.metrics.keys())[:10]:
            stats = self.get_metric_stats(name, "1hour")
            if stats:
                top_metrics[name] = stats

        # Top timers
        top_timers = {}
        for name in list(self.timers.keys())[:10]:
            stats = self.get_timing_stats(name)
            if stats:
                top_timers[name] = stats

        # Recent trends
        recent_trends = [
            {
                "metric": t.metric_name,
                "direction": t.direction,
                "change": f"{t.change_percent:+.1f}%",
                "period": t.period
            }
            for t in self.trends[-10:]
        ]

        return {
            "metrics": top_metrics,
            "timings": top_timers,
            "trends": recent_trends,
            "counters": dict(self.counters),
            "insights": self.generate_insights(),
            "timestamp": datetime.now().isoformat()
        }

    def get_summary(self) -> Dict[str, Any]:
        """Get analytics summary"""
        return {
            "total_metrics": len(self.metrics),
            "total_counters": len(self.counters),
            "total_timers": len(self.timers),
            "active_trends": len(self.trends),
            "data_points": sum(len(m) for m in self.metrics.values())
        }


# Global instance
_analytics: Optional[AdvancedAnalytics] = None


def get_analytics() -> AdvancedAnalytics:
    """Get or create global analytics instance"""
    global _analytics
    if _analytics is None:
        _analytics = AdvancedAnalytics()
    return _analytics
