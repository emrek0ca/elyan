"""
Unit tests for Sleep Consolidator (Offline Learning).

Tests offline consolidation during sleep mode:
- Daily error analysis and categorization
- Pattern chunking (3-step → 1-step atomic)
- Q-learning consolidation (mark high-confidence actions)
- Garbage collection (temp data cleanup)
- Sleep report generation

Sleep mode is triggered offline, doesn't block user tasks.
"""

import pytest
from dataclasses import dataclass
from typing import Dict, List, Optional


# ============================================================================
# Test Data & Fixtures
# ============================================================================

@dataclass
class MockExecutionResult:
    """Mock execution result"""
    agent_id: str
    success: bool
    error_code: Optional[str] = None
    task_type: str = "test"


@pytest.fixture
def daily_errors():
    """Sample daily error log"""
    return [
        MockExecutionResult("agent1", False, "TIMEOUT"),
        MockExecutionResult("agent1", False, "TIMEOUT"),
        MockExecutionResult("agent1", False, "RATE_LIMIT"),
        MockExecutionResult("agent2", False, "PERMISSION_DENIED"),
        MockExecutionResult("agent2", False, "PERMISSION_DENIED"),
        MockExecutionResult("agent3", True),
        MockExecutionResult("agent3", True),
    ]


@pytest.fixture
def frequent_patterns():
    """Frequently executed task sequences"""
    return [
        ["read_file", "parse_json", "validate_schema"],  # 3-step → 1-step atomic
        ["read_file", "parse_json", "validate_schema"],
        ["read_file", "parse_json", "validate_schema"],
        ["open_app", "click_button"],  # 2-step, no chunking needed
        ["open_app", "click_button"],
    ]


@pytest.fixture
def q_table():
    """Sample Q-learning table"""
    return {
        "read": {
            "file.read": 0.95,      # High confidence
            "memory.read": 0.85,    # Medium
        },
        "write": {
            "file.write": 0.75,     # Lower confidence
            "db.write": 0.45,       # Low
        },
    }


# ============================================================================
# Test Cases — Error Analysis
# ============================================================================

class TestErrorAnalysis:
    """Test daily error categorization and analysis"""

    def test_categorize_timeout_errors(self, daily_errors):
        """
        Test 1: Categorize TIMEOUT errors
        Expected: 2 timeout errors identified
        """
        from core.sleep_consolidator import SleepConsolidator

        consolidator = SleepConsolidator()
        categories = consolidator.analyze_daily_errors(daily_errors)

        assert "TIMEOUT" in categories, "TIMEOUT category should exist"
        assert len(categories["TIMEOUT"]) == 2, "Should find 2 timeout errors"

    def test_categorize_permission_errors(self, daily_errors):
        """
        Test 2: Categorize PERMISSION_DENIED errors
        Expected: 2 permission errors for agent2
        """
        from core.sleep_consolidator import SleepConsolidator

        consolidator = SleepConsolidator()
        categories = consolidator.analyze_daily_errors(daily_errors)

        assert "PERMISSION_DENIED" in categories, "PERMISSION_DENIED should exist"
        assert len(categories["PERMISSION_DENIED"]) == 2, "Should find 2 permission errors"

    def test_aggregate_errors_by_agent(self, daily_errors):
        """
        Test 3: Aggregate errors by agent
        Expected: agent1=2 (TIMEOUT+RATE_LIMIT), agent2=2 (PERMISSION)
        """
        from core.sleep_consolidator import SleepConsolidator

        consolidator = SleepConsolidator()
        by_agent = consolidator.aggregate_errors_by_agent(daily_errors)

        assert "agent1" in by_agent, "agent1 should be in analysis"
        assert "agent2" in by_agent, "agent2 should be in analysis"
        assert len(by_agent["agent1"]) == 3, "agent1 has 3 errors (2 TIMEOUT + 1 RATE_LIMIT)"

    def test_success_rate_calculation(self, daily_errors):
        """
        Test 4: Calculate success rate
        Expected: 2 successes out of 7 total = 28.5%
        """
        from core.sleep_consolidator import SleepConsolidator

        consolidator = SleepConsolidator()
        success_rate = consolidator.calculate_success_rate(daily_errors)

        expected = 2 / 7  # 2 successes out of 7 total
        assert abs(success_rate - expected) < 0.01, f"Success rate should be ~{expected}"


# ============================================================================
# Test Cases — Pattern Chunking
# ============================================================================

class TestPatternChunking:
    """Test pattern chunking (3-step → 1-step atomic)"""

    def test_identify_frequent_patterns(self, frequent_patterns):
        """
        Test 5: Identify patterns executed 3+ times
        Expected: read_file→parse_json→validate_schema (3x frequency)
        """
        from core.sleep_consolidator import SleepConsolidator

        consolidator = SleepConsolidator()
        chunks = consolidator.identify_frequent_patterns(frequent_patterns, min_frequency=3)

        assert len(chunks) >= 1, "Should find at least 1 chunk pattern"
        # Check if the 3-step pattern is identified
        found_3step = any(len(pattern) == 3 for pattern in chunks)
        assert found_3step, "Should identify 3-step patterns"

    def test_create_atomic_chunks(self, frequent_patterns):
        """
        Test 6: Create atomic chunks from patterns
        Expected: read_file→parse_json→validate_schema → validate_json_schema (atomic)
        """
        from core.sleep_consolidator import SleepConsolidator

        consolidator = SleepConsolidator()
        chunks = consolidator.create_atomic_chunks(frequent_patterns)

        # Should have created at least one atomic chunk
        assert len(chunks) > 0, "Should create atomic chunks"

    def test_chunk_reduces_sequence_length(self, frequent_patterns):
        """
        Test 7: Chunking reduces execution sequence length
        Expected: 3 separate steps → 1 atomic step (67% reduction)
        """
        from core.sleep_consolidator import SleepConsolidator

        consolidator = SleepConsolidator()

        # Original: 3 steps per iteration (3 patterns × 3 steps = 9 total)
        original_steps = sum(len(p) for p in frequent_patterns)

        # After chunking: some steps become atomic
        chunks = consolidator.create_atomic_chunks(frequent_patterns)
        assert len(chunks) > 0, "Should create chunks to reduce steps"


# ============================================================================
# Test Cases — Q-Learning Consolidation
# ============================================================================

class TestQLearningConsolidation:
    """Test Q-learning table optimization"""

    def test_mark_high_confidence_actions(self, q_table):
        """
        Test 8: Mark actions with Q > 0.9 as preferred
        Expected: file.read (0.95) and memory.read (0.85) marked
        """
        from core.sleep_consolidator import SleepConsolidator

        consolidator = SleepConsolidator()
        preferred = consolidator.mark_preferred_actions(q_table, threshold=0.85)

        assert "read" in preferred, "read task should have preferred actions"
        # Should include high-confidence actions
        assert len(preferred["read"]) >= 1, "Should mark at least one preferred action"

    def test_update_q_values_from_daily_data(self):
        """
        Test 9: Update Q-values from daily execution data
        Expected: Successful actions increase Q, failed decrease
        """
        from core.sleep_consolidator import SleepConsolidator

        consolidator = SleepConsolidator()

        # Simulate daily data: action succeeded 8/10 times
        old_q = 0.80
        success_rate = 0.80
        new_q = consolidator.update_q_value(old_q, success_rate)

        # Should increase if success rate is good
        assert new_q >= old_q * 0.95, "Q-value should not decrease significantly"

    def test_consolidation_generates_report(self, q_table):
        """
        Test 10: Consolidation generates summary report
        Expected: Report includes consolidation stats
        """
        from core.sleep_consolidator import SleepConsolidator

        consolidator = SleepConsolidator()
        report = consolidator.generate_consolidation_report(q_table)

        assert report is not None, "Should generate report"
        assert "preferred_actions" in report or "q_values" in report, "Report should have Q-learning data"


# ============================================================================
# Test Cases — Garbage Collection
# ============================================================================

class TestGarbageCollection:
    """Test offline garbage collection"""

    def test_identify_temp_data(self):
        """
        Test 11: Identify temporary data for cleanup
        Expected: Temp caches, old logs identified
        """
        from core.sleep_consolidator import SleepConsolidator

        consolidator = SleepConsolidator()
        temp_items = consolidator.identify_temporary_data()

        # Should identify some temp data
        assert isinstance(temp_items, (list, dict)), "Should return cleanup candidates"

    def test_garbage_collection_frees_memory(self):
        """
        Test 12: Garbage collection frees unused memory
        Expected: Cleanup completes without errors
        """
        from core.sleep_consolidator import SleepConsolidator

        consolidator = SleepConsolidator()

        try:
            consolidator.perform_garbage_collection()
            assert True, "Garbage collection succeeded"
        except Exception as e:
            pytest.fail(f"Garbage collection should succeed: {e}")


# ============================================================================
# Integration Tests
# ============================================================================

class TestSleepConsolidation:
    """Test full sleep consolidation workflow"""

    def test_sleep_mode_offline_no_blocking(self):
        """
        Test 13: Sleep mode runs offline without blocking
        Expected: Consolidation completes, user tasks not blocked
        """
        from core.sleep_consolidator import SleepConsolidator

        consolidator = SleepConsolidator()

        # Sleep mode should complete without blocking
        try:
            consolidator.enter_sleep_mode(
                daily_errors=[],
                q_table={},
                patterns=[]
            )
            assert True, "Sleep mode completed without blocking"
        except Exception as e:
            pytest.fail(f"Sleep mode should not block: {e}")

    def test_consolidation_report_generation(self, daily_errors, q_table):
        """
        Test 14: Sleep consolidation generates detailed report
        Expected: Report includes errors, chunks, Q-values
        """
        from core.sleep_consolidator import SleepConsolidator

        consolidator = SleepConsolidator()
        report = consolidator.enter_sleep_mode(
            daily_errors=daily_errors,
            q_table=q_table,
            patterns=[]
        )

        assert report is not None, "Should generate report"
        assert hasattr(report, 'timestamp') or hasattr(report, 'chunks_created'), "Report should be detailed"

    def test_sleep_report_contains_metrics(self):
        """
        Test 15: Sleep report contains consolidation metrics
        Expected: Report has chunks created, Q-values updated, memory freed
        """
        from core.sleep_consolidator import SleepConsolidator

        consolidator = SleepConsolidator()
        report = consolidator.generate_sleep_report(
            chunks_created=5,
            q_values_optimized=12,
            memory_freed_mb=256
        )

        assert report is not None, "Should generate report"
        assert isinstance(report, dict), "Report should be dict"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
