"""
Sleep Consolidation Widget - Shows offline learning progress

Displays:
- Last consolidation run
- Patterns learned
- Q-learning updates
- Next scheduled run
- Memory optimization results
"""

from typing import Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


@dataclass
class SleepMetrics:
    """Metrics from sleep consolidation"""
    last_run: Optional[str]
    patterns_learned: int
    q_values_updated: int
    memory_freed_mb: float
    next_scheduled: Optional[str]
    enabled: bool


class SleepConsolidationWidget:
    """Widget showing sleep consolidation progress"""

    def __init__(self):
        """Initialize widget"""
        self.cache_ttl_seconds = 30
        self.last_update = None
        self.cached_metrics = None

    def get_sleep_metrics(self) -> SleepMetrics:
        """Get current sleep consolidation metrics"""
        if self.cached_metrics and self.last_update:
            age = (datetime.now() - self.last_update).total_seconds()
            if age < self.cache_ttl_seconds:
                return self.cached_metrics

        try:
            from config.settings_manager import SettingsPanel
            from core.cognitive_layer_integrator import get_cognitive_integrator

            settings = SettingsPanel()
            integrator = get_cognitive_integrator()

            enabled = settings.get("sleep_consolidation_enabled", False)
            next_scheduled = settings.get("sleep_consolidation_time") if enabled else None

            # Get daily data
            daily_errors = len(integrator.daily_errors)
            daily_patterns = len(integrator.daily_patterns)
            q_table_size = len(integrator.execution_q_table)

            # Estimate memory freed (simplified)
            # Each error ~100 bytes, each pattern ~200 bytes
            memory_freed = (daily_errors * 100 + daily_patterns * 200) / (1024 * 1024)

            # Read last consolidation report (if available)
            last_run = None
            try:
                from pathlib import Path
                report_dir = Path.home() / ".elyan" / "logs" / "sleep_reports"
                if report_dir.exists():
                    reports = sorted(report_dir.glob("*.json"), reverse=True)
                    if reports:
                        # Parse timestamp from filename or content
                        last_run = reports[0].stem  # Use filename as timestamp
            except Exception:
                pass

            metrics = SleepMetrics(
                last_run=last_run,
                patterns_learned=daily_patterns,
                q_values_updated=q_table_size,
                memory_freed_mb=memory_freed,
                next_scheduled=next_scheduled,
                enabled=enabled
            )

            self.cached_metrics = metrics
            self.last_update = datetime.now()

            return metrics

        except Exception as e:
            logger.error(f"Failed to get sleep metrics: {e}")
            return SleepMetrics(
                last_run=None,
                patterns_learned=0,
                q_values_updated=0,
                memory_freed_mb=0.0,
                next_scheduled=None,
                enabled=False
            )

    def render_card(self, width: int = 80) -> str:
        """Render sleep consolidation card"""
        metrics = self.get_sleep_metrics()

        lines = []
        lines.append("┌" + "─" * (width - 2) + "┐")
        lines.append("│ Uyku Pekiştirme (Çevrimdışı Öğrenme) " + " " * (width - 40) + "│")
        lines.append("├" + "─" * (width - 2) + "┤")

        # Status line
        status = "✓ Etkin" if metrics.enabled else "✗ Devre dışı"
        status_line = f"  Durum: {status}"
        if metrics.next_scheduled:
            status_line += f" | Sonraki: {metrics.next_scheduled}"
        lines.append(f"│{status_line:<{width - 2}}│")

        # Learning metrics
        metrics_line = f"  Öğrenilen Örüntü: {metrics.patterns_learned} | Q-Değer: {metrics.q_values_updated}"
        lines.append(f"│{metrics_line:<{width - 2}}│")

        # Memory savings
        memory_line = f"  Bellek Boşaltıldı: {metrics.memory_freed_mb:.2f} MB"
        if metrics.last_run:
            memory_line += f" | Son Çalışma: {metrics.last_run}"
        lines.append(f"│{memory_line:<{width - 2}}│")

        lines.append("└" + "─" * (width - 2) + "┘")

        return "\n".join(lines)

    def render_json(self) -> Dict[str, Any]:
        """Render as JSON"""
        metrics = self.get_sleep_metrics()
        return {
            "enabled": metrics.enabled,
            "last_run": metrics.last_run,
            "patterns_learned": metrics.patterns_learned,
            "q_values_updated": metrics.q_values_updated,
            "memory_freed_mb": round(metrics.memory_freed_mb, 2),
            "next_scheduled": metrics.next_scheduled
        }


class SleepScheduleManager:
    """Manages sleep consolidation scheduling"""

    @staticmethod
    def schedule_sleep(time_str: str) -> Dict[str, Any]:
        """Schedule sleep consolidation"""
        try:
            # Validate time format
            parts = time_str.split(":")
            if len(parts) != 2:
                return {"error": "Invalid time format. Use HH:MM"}

            hour = int(parts[0])
            minute = int(parts[1])

            if not (0 <= hour < 24 and 0 <= minute < 60):
                return {"error": "Hour must be 0-23, minute must be 0-59"}

            # Update settings
            from config.settings_manager import SettingsPanel
            settings = SettingsPanel()
            settings._settings["sleep_consolidation_enabled"] = True
            settings._settings["sleep_consolidation_time"] = time_str
            settings.save()

            return {
                "success": True,
                "message": f"Uyku pekiştirme {time_str} için planlandı",
                "scheduled_time": time_str
            }

        except Exception as e:
            return {"error": str(e)}

    @staticmethod
    def get_next_sleep_time() -> Optional[str]:
        """Get next scheduled sleep time"""
        try:
            from config.settings_manager import SettingsPanel
            from datetime import datetime, timedelta

            settings = SettingsPanel()
            if not settings.get("sleep_consolidation_enabled", False):
                return None

            scheduled_time = settings.get("sleep_consolidation_time")
            if not scheduled_time:
                return None

            # Parse scheduled time
            parts = scheduled_time.split(":")
            hour = int(parts[0])
            minute = int(parts[1])

            # Calculate next occurrence
            now = datetime.now()
            next_sleep = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

            if next_sleep <= now:
                # Scheduled time already passed today, schedule for tomorrow
                next_sleep += timedelta(days=1)

            return next_sleep.isoformat()

        except Exception as e:
            logger.error(f"Failed to get next sleep time: {e}")
            return None

    @staticmethod
    def time_until_sleep() -> Optional[Dict[str, int]]:
        """Get time remaining until next sleep consolidation"""
        try:
            from datetime import datetime

            next_time = SleepScheduleManager.get_next_sleep_time()
            if not next_time:
                return None

            next_sleep = datetime.fromisoformat(next_time)
            remaining = next_sleep - datetime.now()

            if remaining.total_seconds() < 0:
                return None

            hours = int(remaining.total_seconds() // 3600)
            minutes = int((remaining.total_seconds() % 3600) // 60)
            seconds = int(remaining.total_seconds() % 60)

            return {
                "hours": hours,
                "minutes": minutes,
                "seconds": seconds,
                "total_seconds": int(remaining.total_seconds())
            }

        except Exception as e:
            logger.error(f"Failed to calculate time until sleep: {e}")
            return None
