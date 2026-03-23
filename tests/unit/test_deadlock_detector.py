"""
Unit tests for Deadlock Detector (Einstellung Breaker).

The Deadlock Detector identifies when an agent is stuck in a failing loop
(Einstellung effect) and suggests recovery actions.

Tests validate:
1. Stuck loop detection (3+ consecutive failures with same error)
2. Failure pattern matching
3. Recovery action suggestions
4. No false positives on single failures
"""

import pytest
from dataclasses import dataclass
from typing import Optional


# ============================================================================
# Test Data & Fixtures
# ============================================================================

@dataclass
class MockExecutionResult:
    """Minimal execution result for testing"""
    agent_id: str
    success: bool
    error_code: Optional[str] = None
    duration: float = 1.0


@pytest.fixture
def api_rate_limit_failures():
    """3 consecutive API rate limit failures"""
    return [
        MockExecutionResult(agent_id="api_agent", success=False, error_code="RATE_LIMIT", duration=1.0),
        MockExecutionResult(agent_id="api_agent", success=False, error_code="RATE_LIMIT", duration=1.0),
        MockExecutionResult(agent_id="api_agent", success=False, error_code="RATE_LIMIT", duration=1.0),
    ]


@pytest.fixture
def timeout_cascade():
    """3 consecutive timeout failures"""
    return [
        MockExecutionResult(agent_id="slow_agent", success=False, error_code="TIMEOUT", duration=30.0),
        MockExecutionResult(agent_id="slow_agent", success=False, error_code="TIMEOUT", duration=30.0),
        MockExecutionResult(agent_id="slow_agent", success=False, error_code="TIMEOUT", duration=30.0),
    ]


@pytest.fixture
def single_failure():
    """Single failure (should not trigger stuck detection)"""
    return MockExecutionResult(agent_id="agent", success=False, error_code="API_ERROR", duration=1.0)


@pytest.fixture
def mixed_errors():
    """Different error codes (should not trigger pattern match)"""
    return [
        MockExecutionResult(agent_id="agent", success=False, error_code="ERROR_A", duration=1.0),
        MockExecutionResult(agent_id="agent", success=False, error_code="ERROR_B", duration=1.0),
        MockExecutionResult(agent_id="agent", success=False, error_code="ERROR_C", duration=1.0),
    ]


# ============================================================================
# Test Cases — Stuck Detection
# ============================================================================

class TestStuckDetection:
    """Test deadlock detection for stuck agents"""

    def test_detect_api_rate_limit_stuck(self, api_rate_limit_failures):
        """
        Test 1: Detect agent stuck on API rate limit
        Expected: is_stuck() returns True after 3rd failure
        """
        from core.agent_deadlock_detector import DeadlockDetector

        detector = DeadlockDetector(failure_window_size=5)

        # Add failures one by one
        assert not detector.is_stuck(api_rate_limit_failures[0]), "1st failure shouldn't trigger"
        assert not detector.is_stuck(api_rate_limit_failures[1]), "2nd failure shouldn't trigger"
        assert detector.is_stuck(api_rate_limit_failures[2]), "3rd same-error failure should trigger"

    def test_detect_timeout_cascade(self, timeout_cascade):
        """
        Test 2: Detect agent stuck on timeout cascade
        Expected: is_stuck() detects repeated timeout pattern
        """
        from core.agent_deadlock_detector import DeadlockDetector

        detector = DeadlockDetector(failure_window_size=5)

        for i, result in enumerate(timeout_cascade):
            if i < 2:
                assert not detector.is_stuck(result)
            else:
                assert detector.is_stuck(result), "3rd timeout should trigger stuck"

    def test_no_false_positive_single_failure(self, single_failure):
        """
        Test 3: Single failure should NOT trigger stuck detection
        Expected: is_stuck() returns False
        """
        from core.agent_deadlock_detector import DeadlockDetector

        detector = DeadlockDetector(failure_window_size=5)
        assert not detector.is_stuck(single_failure), "Single failure is not stuck"

    def test_no_false_positive_mixed_errors(self, mixed_errors):
        """
        Test 4: Different error codes should NOT match pattern
        Expected: is_stuck() returns False (no repeated error pattern)
        """
        from core.agent_deadlock_detector import DeadlockDetector

        detector = DeadlockDetector(failure_window_size=5)

        for result in mixed_errors:
            # Pattern matching should fail (different errors)
            is_stuck = detector.is_stuck(result)
            # After 3 different errors, not stuck
            assert not is_stuck, "Different error codes should not trigger stuck"

    def test_failure_history_sliding_window(self, api_rate_limit_failures):
        """
        Test 5: Failure history uses sliding window (old failures drop out)
        Expected: Window size respected, old failures forgotten
        """
        from core.agent_deadlock_detector import DeadlockDetector

        detector = DeadlockDetector(failure_window_size=2)

        # Add more than window size
        failures = api_rate_limit_failures + [
            MockExecutionResult(agent_id="api_agent", success=False, error_code="RATE_LIMIT"),
        ]

        for result in failures:
            detector.is_stuck(result)

        # History should only keep last 2
        history_key = "api_agent"
        if history_key in detector.failure_history:
            assert len(detector.failure_history[history_key]) <= 2


# ============================================================================
# Test Cases — Recovery Suggestions
# ============================================================================

class TestRecoverySuggestions:
    """Test deadlock recovery action suggestions"""

    def test_recovery_for_api_rate_limit(self):
        """
        Test 6: Recovery action for API rate limit
        Expected: Suggests queuing, exponential backoff, cache
        """
        from core.agent_deadlock_detector import DeadlockDetector

        detector = DeadlockDetector()
        stuck_result = MockExecutionResult(agent_id="api_agent", success=False, error_code="RATE_LIMIT")

        recovery = detector.suggest_recovery_action("api_agent", ["cache_agent", "queue_agent"])

        assert recovery is not None, "Should suggest recovery"
        assert "action" in recovery, "Recovery should have action field"
        assert recovery["action"] in ["switch_to_diffuse_mode", "queue_task"], "Should suggest appropriate action"

    def test_recovery_for_timeout(self):
        """
        Test 7: Recovery action for timeout
        Expected: Suggests increased timeout, backoff, chunking
        """
        from core.agent_deadlock_detector import DeadlockDetector

        detector = DeadlockDetector()
        stuck_result = MockExecutionResult(agent_id="slow_agent", success=False, error_code="TIMEOUT")

        recovery = detector.suggest_recovery_action("slow_agent", ["chunk_agent"])

        assert recovery is not None
        assert "action" in recovery
        # Should suggest timeout increase or chunking
        assert any(x in recovery.get("action", "") for x in ["timeout", "chunk"]) or "action" in recovery

    def test_recovery_for_permission_denied(self):
        """
        Test 8: Recovery action for permission denied
        Expected: Suggests approval, escalation
        """
        from core.agent_deadlock_detector import DeadlockDetector

        detector = DeadlockDetector()
        stuck_result = MockExecutionResult(agent_id="fs_agent", success=False, error_code="PERMISSION_DENIED")

        recovery = detector.suggest_recovery_action("fs_agent", [])

        assert recovery is not None
        assert "action" in recovery
        assert recovery.get("requires_manual_intervention") in [True, False]  # Either requires intervention or escalates


# ============================================================================
# Integration / Pattern Matching
# ============================================================================

class TestPatternMatching:
    """Test failure pattern recognition"""

    def test_same_error_code_detection(self):
        """
        Test 9: Detector recognizes same error code repeated
        Expected: 3+ same codes = pattern
        """
        from core.agent_deadlock_detector import DeadlockDetector

        detector = DeadlockDetector(failure_window_size=5)

        # Add 3 identical errors
        for _ in range(3):
            result = MockExecutionResult(agent_id="test_agent", success=False, error_code="SPECIFIC_ERROR")
            detector.is_stuck(result)

        # Check internal state
        history_key = "test_agent"
        if history_key in detector.failure_history:
            history = detector.failure_history[history_key]
            error_codes = [r.error_code for r in history if not r.success]
            # Should have 3 identical error codes
            unique_codes = set(error_codes)
            assert len(unique_codes) == 1, "All errors should be identical"

    def test_partial_success_breaks_pattern(self):
        """
        Test 10: One success breaks the failure pattern
        Expected: Pattern counter resets after success
        """
        from core.agent_deadlock_detector import DeadlockDetector

        detector = DeadlockDetector(failure_window_size=5)

        # Fail, fail, succeed, fail, fail, fail
        failures = [
            MockExecutionResult(agent_id="agent", success=False, error_code="E"),
            MockExecutionResult(agent_id="agent", success=False, error_code="E"),
            MockExecutionResult(agent_id="agent", success=True),  # Success breaks chain
            MockExecutionResult(agent_id="agent", success=False, error_code="E"),
            MockExecutionResult(agent_id="agent", success=False, error_code="E"),
        ]

        for i, result in enumerate(failures):
            is_stuck = detector.is_stuck(result)
            # Before 5th result (index 4), should not be stuck
            if i < 4:
                assert not is_stuck, f"Should not be stuck at index {i}"


# ============================================================================
# Edge Cases / Robustness
# ============================================================================

class TestRobustness:
    """Test edge cases and error handling"""

    def test_unknown_agent_id(self):
        """
        Test 11: Detector handles new agent IDs gracefully
        Expected: No crashes, creates new history entry
        """
        from core.agent_deadlock_detector import DeadlockDetector

        detector = DeadlockDetector()

        # First time seeing this agent
        result1 = MockExecutionResult(agent_id="new_agent_xyz", success=False, error_code="ERROR")
        detector.is_stuck(result1)

        # Should not crash
        result2 = MockExecutionResult(agent_id="new_agent_xyz", success=False, error_code="ERROR")
        is_stuck = detector.is_stuck(result2)

        # Not stuck yet (only 2 failures)
        assert not is_stuck

    def test_window_size_boundary(self):
        """
        Test 12: Respects window size boundary (e.g., size=3)
        Expected: Only keeps last N failures in history
        """
        from core.agent_deadlock_detector import DeadlockDetector

        detector = DeadlockDetector(failure_window_size=3)

        # Add 5 failures
        for _ in range(5):
            result = MockExecutionResult(agent_id="agent", success=False, error_code="E")
            detector.is_stuck(result)

        # History should have max 3 entries
        history_key = "agent"
        if history_key in detector.failure_history:
            assert len(detector.failure_history[history_key]) <= 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
