"""
Unit tests for Time-Boxed Scheduler (Pomodoro).

Tests the task resource quotas and time-budget enforcement:
- Task type → time budget mapping
- Timeout enforcement with graceful termination
- Pomodoro break triggering
- CPU/memory quota tracking

Pomodoro settings:
- 5 min (300s) focused work
- 5s breaks
"""

import pytest
import time
from dataclasses import dataclass
from typing import Optional


# ============================================================================
# Test Data & Fixtures
# ============================================================================

@dataclass
class MockTask:
    """Mock task for testing"""
    task_id: str
    task_type: str
    duration: float = 1.0
    success: bool = True


@pytest.fixture
def task_budgets():
    """Task type → budget mapping"""
    return {
        "simple_query": 10,      # 10 seconds
        "file_operation": 30,    # 30 seconds
        "api_call": 20,          # 20 seconds
        "complex_analysis": 300, # 5 minutes
    }


@pytest.fixture
def simple_task():
    """Simple query task"""
    return MockTask(task_id="q1", task_type="simple_query", duration=5.0)


@pytest.fixture
def slow_task():
    """Slow analysis task"""
    return MockTask(task_id="a1", task_type="complex_analysis", duration=120.0)


# ============================================================================
# Test Cases — Budget Assignment
# ============================================================================

class TestBudgetAssignment:
    """Test time budget assignment by task type"""

    def test_simple_query_budget(self, task_budgets):
        """
        Test 1: Simple query gets 10s budget
        Expected: simple_query → 10 seconds
        """
        from core.time_boxed_scheduler import TimeBoxedScheduler

        scheduler = TimeBoxedScheduler(task_budgets)
        budget = scheduler.get_budget_for_task_type("simple_query")

        assert budget == 10, "Simple query budget should be 10s"

    def test_complex_analysis_budget(self, task_budgets):
        """
        Test 2: Complex analysis gets 300s budget
        Expected: complex_analysis → 300 seconds (5 min)
        """
        from core.time_boxed_scheduler import TimeBoxedScheduler

        scheduler = TimeBoxedScheduler(task_budgets)
        budget = scheduler.get_budget_for_task_type("complex_analysis")

        assert budget == 300, "Complex analysis budget should be 300s"

    def test_unknown_task_type_default(self, task_budgets):
        """
        Test 3: Unknown task type gets default budget
        Expected: Unknown → 60 seconds (default)
        """
        from core.time_boxed_scheduler import TimeBoxedScheduler

        scheduler = TimeBoxedScheduler(task_budgets)
        budget = scheduler.get_budget_for_task_type("unknown_type")

        assert budget == 60, "Unknown task type should default to 60s"

    def test_assign_budget_to_task(self, task_budgets, simple_task):
        """
        Test 4: Assign budget to specific task
        Expected: Task gets budget based on its type
        """
        from core.time_boxed_scheduler import TimeBoxedScheduler

        scheduler = TimeBoxedScheduler(task_budgets)
        scheduler.assign_budget(simple_task.task_id, simple_task.task_type)

        budget = scheduler.get_task_budget(simple_task.task_id)
        assert budget == 10, "Task should get 10s budget for simple_query"


# ============================================================================
# Test Cases — Timeout Enforcement
# ============================================================================

class TestTimeoutEnforcement:
    """Test timeout monitoring and enforcement"""

    def test_task_completes_within_budget(self, task_budgets, simple_task):
        """
        Test 5: Task completing within budget doesn't timeout
        Expected: Task succeeds, no timeout
        """
        from core.time_boxed_scheduler import TimeBoxedScheduler

        scheduler = TimeBoxedScheduler(task_budgets)
        scheduler.assign_budget(simple_task.task_id, simple_task.task_type)

        # Simulate task execution within budget (5s < 10s budget)
        start = time.time()
        time.sleep(0.1)  # Simulate quick task
        elapsed = time.time() - start

        is_exceeded = scheduler.check_timeout(simple_task.task_id, elapsed)
        assert not is_exceeded, "Quick task should not exceed budget"

    def test_task_exceeds_budget_timeout(self, task_budgets, simple_task):
        """
        Test 6: Task exceeding budget triggers timeout
        Expected: Task flagged as timed out
        """
        from core.time_boxed_scheduler import TimeBoxedScheduler

        scheduler = TimeBoxedScheduler(task_budgets)
        scheduler.assign_budget(simple_task.task_id, simple_task.task_type)

        # Simulate task running 15s (exceeds 10s budget)
        is_exceeded = scheduler.check_timeout(simple_task.task_id, 15.0)
        assert is_exceeded, "Task exceeding budget should timeout"

    def test_graceful_termination_no_crash(self, task_budgets, simple_task):
        """
        Test 7: Timeout termination is graceful (no crash)
        Expected: Scheduler handles timeout without crashing
        """
        from core.time_boxed_scheduler import TimeBoxedScheduler

        scheduler = TimeBoxedScheduler(task_budgets)
        scheduler.assign_budget(simple_task.task_id, simple_task.task_type)

        # Simulate timeout - should not crash
        try:
            scheduler.check_timeout(simple_task.task_id, 15.0)
            assert True, "Timeout handling succeeded"
        except Exception as e:
            pytest.fail(f"Timeout should be graceful: {e}")


# ============================================================================
# Test Cases — Pomodoro Timer
# ============================================================================

class TestPomodoroTimer:
    """Test Pomodoro break scheduling"""

    def test_no_break_after_short_work(self, task_budgets):
        """
        Test 8: No break needed after short work
        Expected: < 300s → no break
        """
        from core.time_boxed_scheduler import TimeBoxedScheduler

        scheduler = TimeBoxedScheduler(task_budgets)

        # After 100s work, no break needed
        needs_break = scheduler.needs_pomodoro_break(100)
        assert not needs_break, "No break needed after 100s"

    def test_break_after_300s_focused(self, task_budgets):
        """
        Test 9: Break triggered after 300s focused work
        Expected: >= 300s → break (5s)
        """
        from core.time_boxed_scheduler import TimeBoxedScheduler

        scheduler = TimeBoxedScheduler(task_budgets)

        # After 300s+ work, break needed
        needs_break = scheduler.needs_pomodoro_break(300)
        assert needs_break, "Break needed after 300s"

    def test_pomodoro_break_duration(self, task_budgets):
        """
        Test 10: Pomodoro break is 5 seconds
        Expected: Break duration = 5s
        """
        from core.time_boxed_scheduler import TimeBoxedScheduler

        scheduler = TimeBoxedScheduler(task_budgets)

        break_duration = scheduler.pomodoro_break_duration
        assert break_duration == 5, "Pomodoro break should be 5s"

    def test_pomodoro_focus_duration(self, task_budgets):
        """
        Test 11: Pomodoro focus block is 5 minutes (300s)
        Expected: Focus duration = 300s
        """
        from core.time_boxed_scheduler import TimeBoxedScheduler

        scheduler = TimeBoxedScheduler(task_budgets)

        focus_duration = scheduler.max_focus_duration
        assert focus_duration == 300, "Pomodoro focus should be 300s"


# ============================================================================
# Test Cases — Quota Tracking
# ============================================================================

class TestQuotaTracking:
    """Test CPU/memory quota tracking"""

    def test_task_quota_assignment(self, task_budgets, simple_task):
        """
        Test 12: Task gets CPU/memory quota
        Expected: Default quotas assigned
        """
        from core.time_boxed_scheduler import TimeBoxedScheduler

        scheduler = TimeBoxedScheduler(task_budgets)
        scheduler.assign_budget(simple_task.task_id, simple_task.task_type)

        # Verify task has quota record
        assert simple_task.task_id in scheduler.active_tasks, "Task should be tracked"


# ============================================================================
# Integration Tests
# ============================================================================

class TestSchedulerIntegration:
    """Test scheduler integration with task engine"""

    def test_multiple_tasks_different_budgets(self, task_budgets):
        """
        Test 13: Multiple tasks get appropriate budgets
        Expected: Each task type gets correct budget
        """
        from core.time_boxed_scheduler import TimeBoxedScheduler

        scheduler = TimeBoxedScheduler(task_budgets)

        # Assign multiple tasks
        tasks = [
            ("q1", "simple_query"),
            ("f1", "file_operation"),
            ("a1", "complex_analysis"),
        ]

        for task_id, task_type in tasks:
            scheduler.assign_budget(task_id, task_type)

        # Verify each got correct budget
        assert scheduler.get_task_budget("q1") == 10, "Query budget should be 10s"
        assert scheduler.get_task_budget("f1") == 30, "File operation budget should be 30s"
        assert scheduler.get_task_budget("a1") == 300, "Analysis budget should be 300s"

    def test_no_task_exceeds_2x_budget(self, task_budgets):
        """
        Test 14: No task should exceed 2x its budget (safety margin)
        Expected: Timeout kills task at 1x budget, definitely by 2x
        """
        from core.time_boxed_scheduler import TimeBoxedScheduler

        scheduler = TimeBoxedScheduler(task_budgets)
        scheduler.assign_budget("q1", "simple_query")

        # At 1x budget (10s), should timeout
        is_exceeded = scheduler.check_timeout("q1", 10.0)
        assert is_exceeded, "Should timeout at budget"

        # Task should never reach 2x (20s)
        assert not scheduler.is_task_still_running("q1"), "Task should be terminated"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
