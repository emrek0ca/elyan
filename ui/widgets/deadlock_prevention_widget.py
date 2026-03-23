"""
Deadlock Prevention Widget - Shows deadlock detection and recovery

Displays:
- Recent deadlock detections
- Recovery actions taken
- Success rate of recovery
- Pattern analysis
"""

from typing import Dict, Any, List
from dataclasses import dataclass
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


@dataclass
class DeadlockEvent:
    """Represents a detected deadlock"""
    task_id: str
    action: str
    error_code: str
    recovery_action: str
    timestamp: str
    success: bool


class DeadlockPreventionWidget:
    """Widget showing deadlock detection and prevention"""

    def __init__(self):
        """Initialize widget"""
        self.cache_ttl_seconds = 10
        self.last_update = None
        self.cached_data = None

    def get_deadlock_stats(self) -> Dict[str, Any]:
        """Get deadlock statistics"""
        if self.cached_data and self.last_update:
            age = (datetime.now() - self.last_update).total_seconds()
            if age < self.cache_ttl_seconds:
                return self.cached_data

        try:
            from cli.commands.cognitive import _read_cognitive_traces, _get_recent_deadlocks

            # Get recent deadlocks
            deadlocks = _get_recent_deadlocks()

            # Count by recovery action
            recovery_counts = {}
            for dl in deadlocks:
                recovery = dl.get("recovery", "unknown")
                recovery_counts[recovery] = recovery_counts.get(recovery, 0) + 1

            # Count success (deadlock detected and resolved)
            total_detected = len(deadlocks)

            # Get all traces to find recovery successes
            traces = _read_cognitive_traces(limit=100)
            recovery_successes = sum(1 for t in traces if t.get("deadlock_detected") and t.get("execution_success"))

            recovery_rate = (recovery_successes / total_detected * 100) if total_detected > 0 else 0.0

            stats = {
                "total_detected": total_detected,
                "recovery_successes": recovery_successes,
                "recovery_rate_pct": recovery_rate,
                "recovery_strategies": recovery_counts,
                "recent_deadlocks": deadlocks[:10]
            }

            self.cached_data = stats
            self.last_update = datetime.now()

            return stats

        except Exception as e:
            logger.error(f"Failed to get deadlock stats: {e}")
            return {"error": str(e)}

    def render_card(self, width: int = 80) -> str:
        """Render deadlock prevention card"""
        data = self.get_deadlock_stats()

        if "error" in data:
            return f"Hata: {data['error']}"

        total = data.get("total_detected", 0)
        successes = data.get("recovery_successes", 0)
        rate = data.get("recovery_rate_pct", 0)

        lines = []
        lines.append("┌" + "─" * (width - 2) + "┐")
        lines.append("│ Kilitlenme Önleme " + " " * (width - 21) + "│")
        lines.append("├" + "─" * (width - 2) + "┤")

        # Summary
        summary = f"  Algılanan: {total} | Çözülen: {successes} | Başarı: {rate:.0f}%"
        lines.append(f"│{summary:<{width - 2}}│")

        # Recovery strategies
        strategies = data.get("recovery_strategies", {})
        if strategies:
            lines.append("├" + "─" * (width - 2) + "┤")
            lines.append("│ Kurtarma Stratejileri " + " " * (width - 25) + "│")
            for strategy, count in sorted(strategies.items(), key=lambda x: -x[1])[:3]:
                strategy_line = f"  • {strategy}: {count}x"
                lines.append(f"│{strategy_line:<{width - 2}}│")

        # Recent deadlocks
        deadlocks = data.get("recent_deadlocks", [])
        if deadlocks:
            lines.append("├" + "─" * (width - 2) + "┤")
            lines.append("│ Son Kilitlenmeler " + " " * (width - 21) + "│")
            for dl in deadlocks[:3]:
                task = f"  • {dl.get('task_id')}: {dl.get('action')}"
                task += f" → {dl.get('recovery')}"
                lines.append(f"│{task:<{width - 2}}│")

        lines.append("└" + "─" * (width - 2) + "┘")

        return "\n".join(lines)

    def render_json(self) -> Dict[str, Any]:
        """Render as JSON"""
        return self.get_deadlock_stats()


class DeadlockTimeline:
    """Timeline visualization of deadlocks"""

    @staticmethod
    def get_timeline_data(hours: int = 24) -> Dict[str, Any]:
        """Get deadlock timeline for last N hours"""
        try:
            from cli.commands.cognitive import _read_cognitive_traces
            from datetime import datetime, timedelta

            traces = _read_cognitive_traces(limit=200)
            cutoff = datetime.now() - timedelta(hours=hours)

            timeline = {}
            for trace in traces:
                if not trace.get("deadlock_detected"):
                    continue

                try:
                    timestamp = datetime.fromisoformat(trace.get("timestamp", ""))
                    if timestamp < cutoff:
                        continue

                    hour = timestamp.strftime("%H:00")
                    if hour not in timeline:
                        timeline[hour] = 0
                    timeline[hour] += 1
                except Exception:
                    pass

            return {
                "timeline": dict(sorted(timeline.items())),
                "total": sum(timeline.values()),
                "peak_hour": max(timeline, key=timeline.get) if timeline else "None"
            }

        except Exception as e:
            logger.error(f"Failed to get timeline: {e}")
            return {"error": str(e)}

    @staticmethod
    def render_timeline(hours: int = 24, width: int = 80) -> str:
        """Render timeline as ASCII chart"""
        data = DeadlockTimeline.get_timeline_data(hours)

        if "error" in data:
            return f"Hata: {data['error']}"

        timeline = data.get("timeline", {})
        total = data.get("total", 0)

        lines = []
        lines.append("┌" + "─" * (width - 2) + "┐")
        lines.append("│ Kilitlenme Zaman Çizelgesi " + " " * (width - 30) + "│")
        lines.append("├" + "─" * (width - 2) + "┤")

        if not timeline:
            lines.append(f"│ Son {hours} saatte kilitlenme algılanmadı " + " " * (width - 45) + "│")
        else:
            max_count = max(timeline.values())
            for hour, count in sorted(timeline.items()):
                bar_length = int((count / max_count * 30)) if max_count > 0 else 0
                bar = "█" * bar_length
                hour_line = f"  {hour} {bar} {count}"
                lines.append(f"│{hour_line:<{width - 2}}│")

            summary = f"  Toplam: {total} | En çok: {data.get('peak_hour')}"
            lines.append(f"│{summary:<{width - 2}}│")

        lines.append("└" + "─" * (width - 2) + "┘")

        return "\n".join(lines)
