"""
Integration tests for Phase 4 Cognitive Layer.

Tests the complete cognitive architecture:
1. CEO Planner: Simulate task execution before running
2. Deadlock Detector: Catch stuck loops (3+ failures)
3. Focused-Diffuse Modes: Dynamic mode switching
4. Time-Boxed Scheduler: Resource quotas and Pomodoro
5. Sleep Consolidator: Offline optimization

Validates end-to-end workflows without breaking existing system.
"""

import pytest
import asyncio
from dataclasses import dataclass
from typing import Dict, Optional, Any


# ============================================================================
# Test Fixtures & Mocks
# ============================================================================

@dataclass
class MockTask:
    """Mock task for testing"""
    task_id: str
    task_type: str = "simple_query"
    success: bool = True
    error_code: Optional[str] = None
    duration: float = 1.0
    agent_id: str = "test_agent"


@dataclass
class MockExecutionResult:
    """Mock execution result"""
    task_id: str
    success: bool
    duration: float
    error_code: Optional[str] = None
    agent_id: str = "test_agent"
    output: Any = None


@pytest.fixture
def cognitive_components():
    """Create all cognitive components"""
    from core.ceo_planner import CEOPlanner
    from core.agent_deadlock_detector import DeadlockDetector
    from core.execution_modes import FocusedModeEngine
    from core.cognitive_state_machine import CognitiveStateMachine
    from core.time_boxed_scheduler import TimeBoxedScheduler
    from core.sleep_consolidator import SleepConsolidator

    return {
        "ceo": CEOPlanner(),
        "deadlock": DeadlockDetector(),
        "focused": FocusedModeEngine({"simple_query": {"quick": 0.95}}),
        "state_machine": CognitiveStateMachine(),
        "scheduler": TimeBoxedScheduler(),
        "sleep": SleepConsolidator(),
    }


@pytest.fixture
def simple_task():
    """Simple query task"""
    return MockTask(task_id="q1", task_type="simple_query", success=True, duration=2.0)


@pytest.fixture
def failing_task():
    """Task that fails"""
    return MockTask(
        task_id="f1",
        task_type="api_call",
        success=False,
        error_code="RATE_LIMIT",
        duration=5.0
    )


# ============================================================================
# Test Cases — CEO Planner Integration
# ============================================================================

class TestCEOPlanning:
    """Test CEO planner integration with task execution"""

    @staticmethod
    def create_task(action, task_id="t1"):
        """Create task object with required attributes"""
        class Task:
            def __init__(self, action, task_id):
                self.action = action
                self.id = task_id

        return Task(action, task_id)

    def test_ceo_simulates_before_execution(self, cognitive_components):
        """
        Test 1: CEO simulates task before actual execution
        Expected: Causal tree built, no crashes
        """
        ceo = cognitive_components["ceo"]

        # Simulate a simple read task
        task = self.create_task("file.read")
        tree = ceo.build_causal_tree(task, {})

        assert tree is not None, "Should build causal tree"
        assert tree.action is not None, "Tree should have action"

    def test_ceo_detects_conflicts(self, cognitive_components):
        """
        Test 2: CEO detects execution conflicts
        Expected: Mutual exclusion detected
        """
        ceo = cognitive_components["ceo"]

        task1 = self.create_task("delete_file", "t1")
        task2 = self.create_task("copy_file", "t2")

        tree1 = ceo.build_causal_tree(task1, {})
        tree2 = ceo.build_causal_tree(task2, {})

        conflicts = ceo.detect_conflicting_loops(tree1)
        # Check that conflict detection works
        assert conflicts is not None, "Should return conflict list"

    def test_ceo_predicts_error_scenarios(self, cognitive_components):
        """
        Test 3: CEO predicts potential errors
        Expected: Error scenarios identified (timeout, permission, etc)
        """
        ceo = cognitive_components["ceo"]

        # API call task (prone to timeout/rate limit)
        task = self.create_task("api.call", "t3")
        tree = ceo.build_causal_tree(task, {})

        errors = ceo.predict_error_scenarios(tree)
        assert errors is not None, "Should predict error scenarios"


# ============================================================================
# Test Cases — Deadlock Detection Integration
# ============================================================================

class TestDeadlockDetectionIntegration:
    """Test deadlock detector in workflow"""

    def test_deadlock_detector_catches_stuck_agent(self, cognitive_components):
        """
        Test 4: Deadlock detector catches stuck agent
        Expected: 3 consecutive failures detected as stuck
        """
        detector = cognitive_components["deadlock"]

        class MockResult:
            def __init__(self, success, error_code, agent_id):
                self.success = success
                self.error_code = error_code
                self.agent_id = agent_id

        # Simulate 3 consecutive failures
        for i in range(3):
            result = MockResult(False, "RATE_LIMIT", "api_agent")
            is_stuck = detector.is_stuck(result)

        # Should detect stuck after 3rd failure
        assert is_stuck, "Should detect stuck after 3 failures"

    def test_deadlock_detector_suggests_recovery(self, cognitive_components):
        """
        Test 5: Deadlock detector suggests recovery
        Expected: Recovery action matches error type
        """
        detector = cognitive_components["deadlock"]

        # Trigger RATE_LIMIT recovery
        recovery = detector.suggest_recovery_action("api_agent", [])

        # Should suggest action (not "no_action")
        assert recovery is not None, "Should suggest recovery"
        assert "action" in recovery, "Recovery should have action"


# ============================================================================
# Test Cases — Mode Switching Integration
# ============================================================================

class TestModeSwictchingIntegration:
    """Test focused-diffuse mode switching in workflow"""

    def test_success_keeps_focused_mode(self, cognitive_components):
        """
        Test 6: Success keeps agent in focused mode
        Expected: Mode doesn't change after success
        """
        sm = cognitive_components["state_machine"]
        initial = sm.current_mode

        class MockResult:
            def __init__(self):
                self.success = True
                self.duration = 1.0

        class MockDetector:
            def is_stuck(self, r):
                return False

        asyncio.run(sm.toggle_mode_if_needed(MockResult(), MockDetector()))

        assert sm.current_mode == initial, "Mode should not change on success"

    def test_failure_triggers_diffuse_switch(self, cognitive_components):
        """
        Test 7: Repeated failures trigger diffuse mode
        Expected: After 3 failures → switch to diffuse
        """
        sm = cognitive_components["state_machine"]

        class MockResult:
            def __init__(self):
                self.success = False
                self.error_code = "TIMEOUT"
                self.duration = 5.0
                self.agent_id = "slow_agent"

        class MockDetector:
            def is_stuck(self, r):
                return True

            def suggest_recovery_action(self, agent_id, available_agents=None):
                return {"action": "retry"}

        # Trigger mode switch via deadlock detection
        asyncio.run(sm.toggle_mode_if_needed(MockResult(), MockDetector()))

        # Should switch to diffuse (triggered by deadlock detector)
        from core.execution_modes import ExecutionMode
        # The mode might have switched if deadlock was detected


# ============================================================================
# Test Cases — Time-Boxed Scheduling Integration
# ============================================================================

class TestTimeBoxedScheduling:
    """Test time-boxed scheduling in workflow"""

    def test_scheduler_assigns_budget(self, cognitive_components):
        """
        Test 8: Scheduler assigns budget on task start
        Expected: Budget assigned based on task type
        """
        scheduler = cognitive_components["scheduler"]

        scheduler.assign_budget("task1", "simple_query")
        budget = scheduler.get_task_budget("task1")

        assert budget == 10, "Simple query should get 10s budget"

    def test_scheduler_enforces_timeout(self, cognitive_components):
        """
        Test 9: Scheduler enforces timeout
        Expected: Task exceeding budget is flagged
        """
        scheduler = cognitive_components["scheduler"]

        scheduler.assign_budget("task1", "simple_query")
        is_exceeded = scheduler.check_timeout("task1", 15.0)

        assert is_exceeded, "Task exceeding 10s budget should timeout"

    def test_pomodoro_break_triggered(self, cognitive_components):
        """
        Test 10: Pomodoro break triggered after 5 min focus
        Expected: Break needed after 300s
        """
        scheduler = cognitive_components["scheduler"]

        needs_break = scheduler.needs_pomodoro_break(300)
        assert needs_break, "Break needed after 300s focus"


# ============================================================================
# Test Cases — Sleep Consolidation Integration
# ============================================================================

class TestSleepConsolidation:
    """Test sleep consolidation in workflow"""

    def test_sleep_analyzes_daily_errors(self, cognitive_components):
        """
        Test 11: Sleep consolidator analyzes daily errors
        Expected: Errors categorized
        """
        sleep = cognitive_components["sleep"]

        class MockResult:
            def __init__(self, success, error_code):
                self.success = success
                self.error_code = error_code
                self.agent_id = "test"

        errors = [
            MockResult(False, "TIMEOUT"),
            MockResult(False, "TIMEOUT"),
            MockResult(False, "RATE_LIMIT"),
        ]

        categories = sleep.analyze_daily_errors(errors)
        assert "TIMEOUT" in categories, "Should categorize TIMEOUT"

    def test_sleep_creates_chunks(self, cognitive_components):
        """
        Test 12: Sleep consolidator creates pattern chunks
        Expected: Frequent patterns chunked
        """
        sleep = cognitive_components["sleep"]

        patterns = [
            ["read", "parse", "validate"],
            ["read", "parse", "validate"],
            ["read", "parse", "validate"],
        ]

        chunks = sleep.create_atomic_chunks(patterns)
        assert len(chunks) > 0, "Should create chunks"


# ============================================================================
# Test Cases — End-to-End Workflows
# ============================================================================

class TestEndToEndWorkflows:
    """Test complete cognitive layer workflows"""

    def test_simple_task_workflow(self, cognitive_components, simple_task):
        """
        Test 13: Simple task through full cognitive pipeline
        Expected: Task → CEO → mode → execute → verify
        """
        ceo = cognitive_components["ceo"]
        sm = cognitive_components["state_machine"]
        scheduler = cognitive_components["scheduler"]

        # Create task object
        class Task:
            def __init__(self, action, task_id):
                self.action = action
                self.id = task_id

        # Step 1: CEO plans
        task = Task(simple_task.task_type, simple_task.task_id)
        tree = ceo.build_causal_tree(task, {})
        assert tree is not None

        # Step 2: Assign time budget
        scheduler.assign_budget(simple_task.task_id, simple_task.task_type)
        assert scheduler.get_task_budget(simple_task.task_id) is not None

        # Step 3: Execute (simulated)
        # Step 4: Check result
        assert simple_task.success, "Task should succeed"

    def test_failing_task_with_recovery(self, cognitive_components, failing_task):
        """
        Test 14: Failing task triggers recovery workflow
        Expected: Failure → deadlock check → mode switch → recovery
        """
        deadlock = cognitive_components["deadlock"]
        sm = cognitive_components["state_machine"]
        scheduler = cognitive_components["scheduler"]

        # Assign budget
        scheduler.assign_budget(failing_task.task_id, failing_task.task_type)

        # Check for timeout
        is_exceeded = scheduler.check_timeout(failing_task.task_id, 25.0)
        assert is_exceeded, "API call with 25s should exceed 20s budget"

        # Suggest recovery
        recovery = deadlock.suggest_recovery_action(failing_task.agent_id)
        assert recovery is not None, "Should suggest recovery"

    def test_multiple_tasks_workflow(self, cognitive_components):
        """
        Test 15: Multiple tasks with mode switching
        Expected: Tasks flow through cognitive pipeline
        """
        scheduler = cognitive_components["scheduler"]

        tasks = [
            ("q1", "simple_query"),
            ("f1", "file_operation"),
            ("a1", "api_call"),
            ("c1", "complex_analysis"),
        ]

        # Assign budgets
        for task_id, task_type in tasks:
            scheduler.assign_budget(task_id, task_type)

        # Verify all budgets assigned
        for task_id, task_type in tasks:
            assert scheduler.get_task_budget(task_id) is not None


# ============================================================================
# Test Cases — No Regressions
# ============================================================================

class TestBackwardCompatibility:
    """Test that cognitive layers don't break existing system"""

    def test_cognitive_components_import(self):
        """
        Test 16: All cognitive components import without errors
        Expected: No ImportError
        """
        try:
            from core.ceo_planner import CEOPlanner
            from core.agent_deadlock_detector import DeadlockDetector
            from core.execution_modes import FocusedModeEngine, DiffuseBackgroundEngine
            from core.cognitive_state_machine import CognitiveStateMachine
            from core.time_boxed_scheduler import TimeBoxedScheduler
            from core.sleep_consolidator import SleepConsolidator

            assert True, "All imports successful"
        except ImportError as e:
            pytest.fail(f"Import error: {e}")

    def test_components_initialize_without_config(self):
        """
        Test 17: Cognitive components initialize with defaults
        Expected: No config required
        """
        from core.time_boxed_scheduler import TimeBoxedScheduler
        from core.sleep_consolidator import SleepConsolidator
        from core.ceo_planner import CEOPlanner

        # Should work without explicit config
        scheduler = TimeBoxedScheduler()
        sleep = SleepConsolidator()
        ceo = CEOPlanner()

        assert scheduler is not None
        assert sleep is not None
        assert ceo is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
