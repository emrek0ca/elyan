"""
Phase 5-4: Adaptive Tuning System

Automatically optimizes Elyan's cognitive behavior based on:
- Time budget effectiveness (success rate vs budget accuracy)
- Mode preference learning (FOCUSED vs DIFFUSE performance)
- Deadlock prediction and prevention
- Consolidation scheduling optimization
"""

import logging
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from threading import Lock, RLock
import json

logger = logging.getLogger(__name__)


@dataclass
class TaskPerformanceMetric:
    """Record of a task's performance"""
    task_type: str
    actual_duration: float
    budgeted_duration: float
    mode: str
    success: bool
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    deadlock_detected: bool = False


@dataclass
class ModePreference:
    """Learning state for mode optimization"""
    focused_successes: int = 0
    focused_attempts: int = 0
    diffuse_successes: int = 0
    diffuse_attempts: int = 0
    last_updated: str = field(default_factory=lambda: datetime.now().isoformat())

    def get_success_rate(self, mode: str) -> float:
        """Get success rate for a mode"""
        if mode == "FOCUSED":
            if self.focused_attempts == 0:
                return 0.0
            return (self.focused_successes / self.focused_attempts) * 100
        else:  # DIFFUSE
            if self.diffuse_attempts == 0:
                return 0.0
            return (self.diffuse_successes / self.diffuse_attempts) * 100

    def recommend_mode(self) -> str:
        """Recommend the best mode based on learning"""
        focused_rate = self.get_success_rate("FOCUSED")
        diffuse_rate = self.get_success_rate("DIFFUSE")

        # If we have enough data, recommend based on success rate
        if self.focused_attempts >= 5 and self.diffuse_attempts >= 5:
            if focused_rate > diffuse_rate + 10:
                return "FOCUSED"
            elif diffuse_rate > focused_rate + 10:
                return "DIFFUSE"

        # Default: prefer FOCUSED if we haven't tested DIFFUSE much
        return "FOCUSED" if self.focused_attempts > self.diffuse_attempts else "DIFFUSE"


class BudgetOptimizer:
    """Optimizes time budgets based on actual performance"""

    def __init__(self):
        """Initialize budget optimizer"""
        self.performance_history: Dict[str, List[TaskPerformanceMetric]] = {}
        self._lock = RLock()
        self.min_samples = 5  # Min samples before recommending change

    def record_performance(self, metric: TaskPerformanceMetric) -> None:
        """Record a task's performance"""
        with self._lock:
            if metric.task_type not in self.performance_history:
                self.performance_history[metric.task_type] = []

            self.performance_history[metric.task_type].append(metric)

    def calculate_budget_adjustment(self, task_type: str) -> Optional[float]:
        """
        Calculate recommended budget adjustment for a task type.

        Returns:
        - Adjustment multiplier (e.g., 1.2 = increase by 20%)
        - None if insufficient data
        """
        with self._lock:
            if task_type not in self.performance_history:
                return None

            history = self.performance_history[task_type]
            if len(history) < self.min_samples:
                return None

            # Analyze recent performance (last 10 tasks)
            recent = history[-10:]

            # Calculate average actual vs budgeted ratio
            ratios = []
            for metric in recent:
                if metric.budgeted_duration > 0:
                    ratio = metric.actual_duration / metric.budgeted_duration
                    ratios.append(ratio)

            if not ratios:
                return None

            avg_ratio = sum(ratios) / len(ratios)

            # Calculate success rate
            successes = sum(1 for m in recent if m.success)
            success_rate = (successes / len(recent)) * 100

            # Recommendation logic:
            # - If consistently exceeding budget and success rate is good (>75%), increase budget
            # - If consistently under budget and success rate is great (>90%), decrease budget
            # - Otherwise, keep current budget

            if avg_ratio > 1.2 and success_rate > 75:
                # Tasks are using 20%+ more than budgeted, increase budget by 1.2x
                return 1.2
            elif avg_ratio < 0.7 and success_rate > 90:
                # Tasks are using 30%+ less than budgeted, decrease budget by 0.85x
                return 0.85
            else:
                # Budget seems appropriate
                return None

    def get_budget_stats(self, task_type: str) -> Dict[str, Any]:
        """Get budget statistics for a task type"""
        with self._lock:
            if task_type not in self.performance_history:
                return {"task_type": task_type, "samples": 0}

            history = self.performance_history[task_type]
            if not history:
                return {"task_type": task_type, "samples": 0}

            recent = history[-20:]
            actual_durations = [m.actual_duration for m in recent]
            budgeted_durations = [m.budgeted_duration for m in recent]

            successes = sum(1 for m in recent if m.success)
            success_rate = (successes / len(recent)) * 100

            return {
                "task_type": task_type,
                "samples": len(history),
                "recent_samples": len(recent),
                "avg_actual_duration": sum(actual_durations) / len(actual_durations),
                "avg_budgeted_duration": sum(budgeted_durations) / len(budgeted_durations),
                "success_rate": success_rate,
                "min_actual": min(actual_durations),
                "max_actual": max(actual_durations)
            }


class DeadlockPredictor:
    """Predicts deadlocks based on historical patterns"""

    def __init__(self, lookback_hours: int = 24):
        """Initialize deadlock predictor"""
        self.lookback_hours = lookback_hours
        self.deadlock_patterns: Dict[str, List[datetime]] = {}
        self._lock = RLock()

    def record_deadlock(self, task_type: str) -> None:
        """Record a deadlock event"""
        with self._lock:
            if task_type not in self.deadlock_patterns:
                self.deadlock_patterns[task_type] = []

            self.deadlock_patterns[task_type].append(datetime.now())

    def predict_risk(self, task_type: str) -> Tuple[float, str]:
        """
        Predict deadlock risk for a task type.

        Returns:
        - Risk score (0.0-1.0)
        - Risk level ("low", "medium", "high")
        """
        with self._lock:
            if task_type not in self.deadlock_patterns:
                return 0.0, "low"

            events = self.deadlock_patterns[task_type]
            cutoff = datetime.now() - timedelta(hours=self.lookback_hours)

            # Count recent deadlocks
            recent_events = [e for e in events if e > cutoff]

            if not recent_events:
                return 0.0, "low"

            # Risk calculation:
            # 1-2 events in 24h = low (0.2)
            # 3-5 events in 24h = medium (0.5)
            # 6+ events in 24h = high (0.8)

            count = len(recent_events)
            if count <= 2:
                return 0.2, "low"
            elif count <= 5:
                return 0.5, "medium"
            else:
                return 0.8, "high"

    def get_risk_summary(self) -> Dict[str, Any]:
        """Get summary of deadlock risks"""
        with self._lock:
            cutoff = datetime.now() - timedelta(hours=self.lookback_hours)
            summary = {}

            for task_type, events in self.deadlock_patterns.items():
                recent = [e for e in events if e > cutoff]
                if recent:
                    risk_score, risk_level = self.predict_risk(task_type)
                    summary[task_type] = {
                        "count": len(recent),
                        "risk_score": risk_score,
                        "risk_level": risk_level
                    }

            return summary


class ConsolidationScheduler:
    """Intelligently schedules sleep consolidation based on learning needs"""

    def __init__(self):
        """Initialize consolidation scheduler"""
        self.daily_patterns: Dict[str, int] = {}  # task_type -> pattern_count
        self.last_consolidation: Optional[datetime] = None
        self.consolidations_since_startup: int = 0
        self._lock = RLock()

    def record_pattern(self, pattern_type: str) -> None:
        """Record a learned pattern"""
        with self._lock:
            self.daily_patterns[pattern_type] = self.daily_patterns.get(pattern_type, 0) + 1

    def should_consolidate_now(self) -> bool:
        """Determine if consolidation should happen now"""
        with self._lock:
            if not self.last_consolidation:
                # First consolidation: always do it
                return True

            # Check if enough time has passed (min 6 hours between consolidations)
            time_since_last = datetime.now() - self.last_consolidation
            if time_since_last < timedelta(hours=6):
                return False

            # Check if we've learned enough patterns (at least 50)
            total_patterns = sum(self.daily_patterns.values())
            if total_patterns >= 50:
                return True

            return False

    def recommend_consolidation_time(self) -> str:
        """Recommend optimal consolidation time based on patterns"""
        with self._lock:
            # Analyze pattern distribution to find quiet time
            if not self.daily_patterns:
                # Default: 2 AM
                return "02:00"

            # Count patterns per hour (simplified)
            # In real implementation, would analyze hourly distribution
            total = sum(self.daily_patterns.values())
            if total < 10:
                return "02:00"  # Very light load, early morning is fine

            # For moderate/high load, suggest late night
            return "03:00"

    def mark_consolidation(self) -> None:
        """Mark that consolidation just happened"""
        with self._lock:
            self.last_consolidation = datetime.now()
            self.consolidations_since_startup += 1
            self.daily_patterns.clear()

    def get_consolidation_stats(self) -> Dict[str, Any]:
        """Get consolidation statistics"""
        with self._lock:
            return {
                "consolidations_since_startup": self.consolidations_since_startup,
                "last_consolidation": self.last_consolidation.isoformat() if self.last_consolidation else None,
                "patterns_since_last": sum(self.daily_patterns.values()),
                "recommended_time": self.recommend_consolidation_time(),
                "should_consolidate": self.should_consolidate_now()
            }


class AdaptiveTuningEngine:
    """Main adaptive tuning engine coordinating all optimization"""

    def __init__(self):
        """Initialize adaptive tuning engine"""
        self.budget_optimizer = BudgetOptimizer()
        self.deadlock_predictor = DeadlockPredictor()
        self.consolidation_scheduler = ConsolidationScheduler()
        self.mode_preferences: Dict[str, ModePreference] = {}
        self._lock = RLock()
        self.enabled = True

    def record_task_outcome(
        self,
        task_type: str,
        actual_duration: float,
        budgeted_duration: float,
        mode: str,
        success: bool,
        deadlock_detected: bool = False
    ) -> None:
        """Record task outcome for learning"""
        if not self.enabled:
            return

        metric = TaskPerformanceMetric(
            task_type=task_type,
            actual_duration=actual_duration,
            budgeted_duration=budgeted_duration,
            mode=mode,
            success=success,
            timestamp=datetime.now().isoformat(),
            deadlock_detected=deadlock_detected
        )

        self.budget_optimizer.record_performance(metric)

        # Update mode preferences
        with self._lock:
            if task_type not in self.mode_preferences:
                self.mode_preferences[task_type] = ModePreference()

            pref = self.mode_preferences[task_type]
            if mode == "FOCUSED":
                pref.focused_attempts += 1
                if success:
                    pref.focused_successes += 1
            else:
                pref.diffuse_attempts += 1
                if success:
                    pref.diffuse_successes += 1
            pref.last_updated = datetime.now().isoformat()

        if deadlock_detected:
            self.deadlock_predictor.record_deadlock(task_type)

    def get_recommended_budget(self, task_type: str, current_budget: float) -> float:
        """Get recommended budget for a task type"""
        adjustment = self.budget_optimizer.calculate_budget_adjustment(task_type)

        if adjustment is None:
            return current_budget

        new_budget = current_budget * adjustment
        logger.info(f"Budget adjustment for {task_type}: {current_budget}s → {new_budget:.1f}s")

        return new_budget

    def get_preferred_mode(self, task_type: str) -> str:
        """Get recommended execution mode for task type"""
        with self._lock:
            if task_type not in self.mode_preferences:
                return "FOCUSED"  # Default

            return self.mode_preferences[task_type].recommend_mode()

    def get_deadlock_risk(self, task_type: str) -> Tuple[float, str]:
        """Get deadlock risk for task type"""
        return self.deadlock_predictor.predict_risk(task_type)

    def should_consolidate(self) -> bool:
        """Check if consolidation should happen now"""
        return self.consolidation_scheduler.should_consolidate_now()

    def mark_consolidation_done(self) -> None:
        """Mark consolidation as complete"""
        self.consolidation_scheduler.mark_consolidation()

    def get_optimization_summary(self) -> Dict[str, Any]:
        """Get complete optimization summary"""
        with self._lock:
            return {
                "enabled": self.enabled,
                "budget_optimizations": {
                    task_type: self.budget_optimizer.get_budget_stats(task_type)
                    for task_type in self.budget_optimizer.performance_history.keys()
                },
                "mode_preferences": {
                    task_type: {
                        "focused_rate": pref.get_success_rate("FOCUSED"),
                        "diffuse_rate": pref.get_success_rate("DIFFUSE"),
                        "recommended": pref.recommend_mode(),
                        "focused_attempts": pref.focused_attempts,
                        "diffuse_attempts": pref.diffuse_attempts
                    }
                    for task_type, pref in self.mode_preferences.items()
                },
                "deadlock_risks": self.deadlock_predictor.get_risk_summary(),
                "consolidation_stats": self.consolidation_scheduler.get_consolidation_stats()
            }


# Global adaptive tuning instance
_adaptive_tuning: Optional[AdaptiveTuningEngine] = None


def get_adaptive_tuning() -> AdaptiveTuningEngine:
    """Get or create global adaptive tuning engine"""
    global _adaptive_tuning
    if _adaptive_tuning is None:
        _adaptive_tuning = AdaptiveTuningEngine()
    return _adaptive_tuning


def reset_adaptive_tuning() -> None:
    """Reset adaptive tuning (for testing)"""
    global _adaptive_tuning
    _adaptive_tuning = None
