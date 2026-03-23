"""
Cognitive State Widget - Dashboard visualization for Phase 5

Shows:
- Current execution mode (FOCUSED/DIFFUSE/SLEEP)
- Success rate with trend
- Time budget usage
- Recent mode switches
- Daily metrics
"""

from typing import Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


@dataclass
class CognitiveMetrics:
    """Real-time cognitive metrics for dashboard"""
    mode: str
    success_rate: float
    tasks_today: int
    errors_today: int
    budget_used_pct: float
    mode_switches_today: int
    next_break_seconds: int
    sleep_scheduled: bool
    sleep_time: Optional[str] = None


class CognitiveStateWidget:
    """Widget for cognitive state dashboard card"""

    def __init__(self):
        """Initialize widget"""
        self.last_update = None
        self.cached_metrics = None
        self.cache_ttl_seconds = 5

    def _is_cache_valid(self) -> bool:
        """Check if cached metrics are still valid"""
        if not self.cached_metrics or not self.last_update:
            return False

        age = (datetime.now() - self.last_update).total_seconds()
        return age < self.cache_ttl_seconds

    def get_metrics(self) -> Optional[CognitiveMetrics]:
        """Get current cognitive metrics"""
        if self._is_cache_valid():
            return self.cached_metrics

        try:
            from core.cognitive_layer_integrator import get_cognitive_integrator
            integrator = get_cognitive_integrator()

            # Build metrics
            state = integrator.state_machine
            mode = str(state.current_mode)

            # Calculate success rate from recent traces
            from cli.commands.cognitive import _calculate_success_rate, _read_cognitive_traces
            success_rate = _calculate_success_rate()

            # Get budget usage
            traces = _read_cognitive_traces(limit=1)
            budget_used_pct = 0.0
            if traces:
                last = traces[0]
                if last.get("assigned_budget_seconds") and last.get("execution_duration_ms"):
                    actual_seconds = last.get("execution_duration_ms", 0) / 1000
                    budget = last.get("assigned_budget_seconds", 1)
                    budget_used_pct = min(100.0, (actual_seconds / budget) * 100)

            # Count daily activity
            all_traces = _read_cognitive_traces(limit=100)
            tasks_today = len(all_traces)
            errors_today = sum(1 for t in all_traces if not t.get("execution_success"))

            # Count mode switches today
            mode_switches = sum(1 for t in all_traces if t.get("mode_switched"))

            # Calculate next break
            next_break = state.get_time_until_break() if hasattr(state, 'get_time_until_break') else 0

            # Check if sleep is scheduled
            from config.settings_manager import SettingsPanel
            settings = SettingsPanel()
            sleep_enabled = settings.get("sleep_consolidation_enabled", False)
            sleep_time = settings.get("sleep_consolidation_time") if sleep_enabled else None

            metrics = CognitiveMetrics(
                mode=mode,
                success_rate=success_rate,
                tasks_today=tasks_today,
                errors_today=errors_today,
                budget_used_pct=budget_used_pct,
                mode_switches_today=mode_switches,
                next_break_seconds=int(next_break),
                sleep_scheduled=sleep_enabled,
                sleep_time=sleep_time
            )

            # Cache results
            self.cached_metrics = metrics
            self.last_update = datetime.now()

            return metrics

        except Exception as e:
            logger.error(f"Failed to get cognitive metrics: {e}")
            return None

    def render_card(self, width: int = 80) -> str:
        """Render widget as text card"""
        metrics = self.get_metrics()
        if not metrics:
            return "Bilişsel katman bilgileri alınamadı"

        # Mode indicator
        mode_icon = "⚡" if metrics.mode == "FOCUSED" else "🧠" if metrics.mode == "DIFFUSE" else "😴"

        # Success rate color (simple)
        rate_indicator = "✓" if metrics.success_rate >= 80 else "⚠" if metrics.success_rate >= 50 else "✗"

        lines = []
        lines.append("┌" + "─" * (width - 2) + "┐")
        lines.append("│ Bilişsel Durum " + " " * (width - 17) + "│")
        lines.append("├" + "─" * (width - 2) + "┤")

        # Status line
        status = f"  {mode_icon} {metrics.mode} | {rate_indicator} %{metrics.success_rate:.0f} başarı | Bütçe: {metrics.budget_used_pct:.0f}%"
        lines.append(f"│{status:<{width - 2}}│")

        # Activity line
        activity = f"  Görev: {metrics.tasks_today} | Hata: {metrics.errors_today} | Mod Değişimi: {metrics.mode_switches_today}"
        lines.append(f"│{activity:<{width - 2}}│")

        # Break line
        if metrics.next_break_seconds > 0:
            mins = metrics.next_break_seconds // 60
            secs = metrics.next_break_seconds % 60
            break_line = f"  Sonraki Mola: {mins}m {secs}s"
        else:
            break_line = "  Sonraki Mola: Şimdi (Pomodoro tamamlandı)"
        lines.append(f"│{break_line:<{width - 2}}│")

        # Sleep line
        if metrics.sleep_scheduled:
            sleep_line = f"  Uyku: Planlandı ({metrics.sleep_time})"
        else:
            sleep_line = "  Uyku: Devre dışı"
        lines.append(f"│{sleep_line:<{width - 2}}│")

        lines.append("└" + "─" * (width - 2) + "┘")

        return "\n".join(lines)

    def render_json(self) -> Dict[str, Any]:
        """Render widget as JSON for API"""
        metrics = self.get_metrics()
        if not metrics:
            return {"error": "Failed to retrieve metrics"}

        return {
            "mode": metrics.mode,
            "success_rate_pct": metrics.success_rate,
            "tasks_today": metrics.tasks_today,
            "errors_today": metrics.errors_today,
            "budget_used_pct": metrics.budget_used_pct,
            "mode_switches_today": metrics.mode_switches_today,
            "next_break_seconds": metrics.next_break_seconds,
            "sleep": {
                "scheduled": metrics.sleep_scheduled,
                "time": metrics.sleep_time
            }
        }


class ErrorPredictionWidget:
    """Widget for CEO error prediction"""

    def __init__(self):
        """Initialize widget"""
        self.cache_ttl_seconds = 10
        self.last_update = None
        self.cached_data = None

    def get_recent_predictions(self) -> Dict[str, Any]:
        """Get recent CEO predictions"""
        if self.cached_data and self.last_update:
            age = (datetime.now() - self.last_update).total_seconds()
            if age < self.cache_ttl_seconds:
                return self.cached_data

        try:
            from cli.commands.cognitive import _read_cognitive_traces

            traces = _read_cognitive_traces(limit=20)

            predictions = {
                "total_simulated": len(traces),
                "conflicts_detected": 0,
                "error_scenarios": 0,
                "avg_confidence": 0.0,
                "recent_traces": []
            }

            confidences = []
            for trace in traces:
                ceo = trace.get("ceo_simulation_result", {})
                if ceo.get("success"):
                    if ceo.get("conflicts_detected"):
                        predictions["conflicts_detected"] += 1
                    if ceo.get("error_scenarios"):
                        predictions["error_scenarios"] += 1

                    confidence = ceo.get("confidence", 0.5)
                    confidences.append(confidence)

                    predictions["recent_traces"].append({
                        "task_id": trace.get("task_id"),
                        "action": trace.get("action"),
                        "conflicts": ceo.get("conflicts_detected", []),
                        "errors": ceo.get("error_scenarios", []),
                        "confidence": confidence
                    })

            if confidences:
                predictions["avg_confidence"] = sum(confidences) / len(confidences)

            self.cached_data = predictions
            self.last_update = datetime.now()

            return predictions

        except Exception as e:
            logger.error(f"Failed to get error predictions: {e}")
            return {"error": str(e)}

    def render_card(self, width: int = 80) -> str:
        """Render error prediction card"""
        data = self.get_recent_predictions()

        if "error" in data:
            return f"Hata: {data['error']}"

        lines = []
        lines.append("┌" + "─" * (width - 2) + "┐")
        lines.append("│ Hata Tahmini (CEO) " + " " * (width - 22) + "│")
        lines.append("├" + "─" * (width - 2) + "┤")

        # Summary line
        summary = f"  Simüle: {data['total_simulated']} | Çatışma: {data['conflicts_detected']} | Hata Senaryosu: {data['error_scenarios']}"
        lines.append(f"│{summary:<{width - 2}}│")

        # Confidence line
        confidence = f"  Ortalama Güven: {data['avg_confidence']*100:.1f}%"
        lines.append(f"│{confidence:<{width - 2}}│")

        # Recent predictions
        if data.get("recent_traces"):
            lines.append("├" + "─" * (width - 2) + "┤")
            lines.append("│ Son Tahminler " + " " * (width - 16) + "│")
            for trace in data["recent_traces"][:3]:
                task = f"  • {trace['task_id']}: {trace['action']}"
                if trace.get("conflicts"):
                    task += f" [Çatışma]"
                if trace.get("errors"):
                    task += f" [Hata]"
                task += f" ({trace['confidence']*100:.0f}%)"
                lines.append(f"│{task:<{width - 2}}│")

        lines.append("└" + "─" * (width - 2) + "┘")

        return "\n".join(lines)

    def render_json(self) -> Dict[str, Any]:
        """Render as JSON"""
        return self.get_recent_predictions()
