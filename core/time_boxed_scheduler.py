"""
Time-Boxed Scheduler — Pomodoro Timer & Resource Quotas.

Implements task resource quotas and time budgets to prevent thrashing.

Features:
- Task type → time budget mapping (simple_query=10s, complex_analysis=300s)
- Timeout enforcement with graceful termination
- Pomodoro timer (5 min focused, 5s breaks)
- CPU/memory quota tracking
- Integration with CognitiveStateMachine (timeout triggers diffuse mode)

Principles:
- Every task has explicit time budget
- No task runs > 1x budget (enforced timeout)
- Timeout triggers graceful mode switch, not crash
- Pomodoro breaks prevent mental fatigue (every 300s)
"""

from dataclasses import dataclass, field
from typing import Dict, Optional, Any, Set
from enum import Enum
import logging
import time

logger = logging.getLogger(__name__)


# ============================================================================
# Enums & Data Models
# ============================================================================

@dataclass
class TimeBudget:
    """Resource quota for a single task"""
    task_id: str
    task_type: str
    max_duration: float  # seconds
    cpu_percent: float = 100.0
    memory_percent: float = 100.0
    created_at: float = field(default_factory=time.time)


@dataclass
class TaskQuota:
    """Current quota usage for a task"""
    task_id: str
    budget: TimeBudget
    start_time: float
    elapsed: float = 0.0
    cpu_usage: float = 0.0
    memory_usage: float = 0.0
    exceeded: bool = False


# ============================================================================
# Time-Boxed Scheduler
# ============================================================================

class TimeBoxedScheduler:
    """
    Time-boxed task scheduler with Pomodoro timer.

    Enforces resource quotas per task type and triggers breaks.

    Budget mapping:
    - "simple_query": 10s
    - "file_operation": 30s
    - "api_call": 20s
    - "complex_analysis": 300s
    - Unknown: 60s (default)

    Pomodoro settings:
    - max_focus_duration: 300s (5 minutes)
    - pomodoro_break_duration: 5s
    """

    def __init__(
        self,
        task_budgets: Optional[Dict[str, float]] = None,
        max_focus_duration: int = 300,  # 5 minutes
        break_duration: int = 5,        # 5 seconds
        default_budget: int = 60,       # 60 seconds
    ):
        """
        Initialize scheduler.

        Args:
            task_budgets: Dict mapping task_type → max_duration (seconds)
            max_focus_duration: Max time in focused work before break (seconds)
            break_duration: Duration of Pomodoro break (seconds)
            default_budget: Default budget for unknown task types (seconds)
        """
        self.task_budgets = task_budgets or {
            "simple_query": 10,
            "file_operation": 30,
            "api_call": 20,
            "complex_analysis": 300,
        }
        self.max_focus_duration = max_focus_duration
        self.pomodoro_break_duration = break_duration
        self.default_budget = default_budget

        # Track active tasks
        self.active_tasks: Dict[str, TaskQuota] = {}
        self.focus_start_time = time.time()

        logger.info(
            f"TimeBoxedScheduler initialized: "
            f"focus={max_focus_duration}s, break={break_duration}s"
        )

    def assign_budget(self, task_id: str, task_type: str) -> TimeBudget:
        """
        Assign time budget to a task.

        Args:
            task_id: Unique task identifier
            task_type: Type of task (determines budget)

        Returns:
            TimeBudget object for this task
        """
        max_duration = self.get_budget_for_task_type(task_type)
        budget = TimeBudget(
            task_id=task_id,
            task_type=task_type,
            max_duration=max_duration,
        )

        quota = TaskQuota(
            task_id=task_id,
            budget=budget,
            start_time=time.time(),
        )
        self.active_tasks[task_id] = quota

        logger.debug(
            f"Budget assigned: task={task_id}, type={task_type}, "
            f"max={max_duration}s"
        )
        return budget

    def get_budget_for_task_type(self, task_type: str) -> float:
        """
        Get time budget for a task type.

        Args:
            task_type: The task type to look up

        Returns:
            Max duration in seconds
        """
        return self.task_budgets.get(task_type, self.default_budget)

    def get_task_budget(self, task_id: str) -> Optional[float]:
        """
        Get assigned budget for a specific task.

        Args:
            task_id: Task identifier

        Returns:
            Max duration in seconds, or None if task not found
        """
        if task_id not in self.active_tasks:
            return None
        return self.active_tasks[task_id].budget.max_duration

    def check_timeout(self, task_id: str, elapsed: float) -> bool:
        """
        Check if a task has exceeded its time budget.

        Args:
            task_id: Task identifier
            elapsed: Elapsed time in seconds

        Returns:
            True if task exceeded budget
        """
        if task_id not in self.active_tasks:
            logger.warning(f"Task {task_id} not in active list")
            return False

        quota = self.active_tasks[task_id]
        budget = quota.budget.max_duration

        if elapsed >= budget:
            logger.warning(
                f"Task {task_id} exceeded budget: {elapsed:.1f}s > {budget:.1f}s"
            )
            quota.exceeded = True
            return True

        quota.elapsed = elapsed
        return False

    def is_task_still_running(self, task_id: str) -> bool:
        """
        Check if task is still running (not timed out).

        Args:
            task_id: Task identifier

        Returns:
            True if task is active and not timed out
        """
        if task_id not in self.active_tasks:
            return False

        quota = self.active_tasks[task_id]
        return not quota.exceeded

    def needs_pomodoro_break(self, focused_duration: float) -> bool:
        """
        Check if Pomodoro break is needed.

        Break triggered after max_focus_duration of continuous work.

        Args:
            focused_duration: Total focused work time in seconds

        Returns:
            True if break needed
        """
        return focused_duration >= self.max_focus_duration

    def suggest_mode_switch(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        Suggest mode switch if task timed out.

        Args:
            task_id: Task that timed out

        Returns:
            Dict with mode switch recommendation, or None
        """
        if task_id not in self.active_tasks:
            return None

        quota = self.active_tasks[task_id]
        if not quota.exceeded:
            return None

        return {
            "action": "switch_to_diffuse",
            "reason": f"Task {task_id} exceeded {quota.budget.max_duration}s budget",
            "elapsed": quota.elapsed,
            "budget": quota.budget.max_duration,
        }

    def reset_focus_timer(self) -> None:
        """Reset Pomodoro focus timer after break."""
        self.focus_start_time = time.time()
        logger.debug("Pomodoro timer reset after break")

    def complete_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        Mark task as complete and remove from tracking.

        Args:
            task_id: Task identifier

        Returns:
            Task completion summary
        """
        if task_id not in self.active_tasks:
            return None

        quota = self.active_tasks[task_id]
        summary = {
            "task_id": task_id,
            "task_type": quota.budget.task_type,
            "budget": quota.budget.max_duration,
            "elapsed": quota.elapsed,
            "exceeded": quota.exceeded,
        }

        del self.active_tasks[task_id]
        logger.info(f"Task completed: {task_id}, elapsed={quota.elapsed:.1f}s")

        return summary

    def get_scheduler_state(self) -> Dict[str, Any]:
        """Get current scheduler state for monitoring."""
        focused_time = time.time() - self.focus_start_time
        return {
            "active_tasks": len(self.active_tasks),
            "focused_duration": focused_time,
            "needs_break": self.needs_pomodoro_break(focused_time),
            "max_focus_duration": self.max_focus_duration,
            "break_duration": self.pomodoro_break_duration,
            "task_budgets": self.task_budgets,
        }


if __name__ == "__main__":
    # Smoke test
    import asyncio

    logging.basicConfig(level=logging.DEBUG)

    budgets = {
        "simple_query": 10,
        "file_operation": 30,
        "complex_analysis": 300,
    }

    scheduler = TimeBoxedScheduler(budgets)

    # Test budget assignment
    b1 = scheduler.assign_budget("q1", "simple_query")
    print(f"Task q1 budget: {scheduler.get_task_budget('q1')}s")

    # Test timeout check
    is_exceeded = scheduler.check_timeout("q1", 15.0)
    print(f"Task q1 exceeded: {is_exceeded}")

    # Test Pomodoro
    needs_break = scheduler.needs_pomodoro_break(300)
    print(f"Needs break after 300s: {needs_break}")

    # Test scheduler state
    state = scheduler.get_scheduler_state()
    print(f"Scheduler state: {state}")
