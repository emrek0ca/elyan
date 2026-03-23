"""
Integration tests for Phase 5-4 Adaptive Tuning System

Tests:
- Budget optimization
- Mode preference learning
- Deadlock prediction
- Consolidation scheduling
"""

import pytest
from datetime import datetime, timedelta
import time


class TestBudgetOptimizer:
    """Test budget optimization"""

    def test_record_performance(self):
        """Test recording task performance"""
        from core.adaptive_tuning import BudgetOptimizer, TaskPerformanceMetric

        optimizer = BudgetOptimizer()
        metric = TaskPerformanceMetric(
            task_type="query",
            actual_duration=8.0,
            budgeted_duration=10.0,
            mode="FOCUSED",
            success=True
        )

        optimizer.record_performance(metric)

        stats = optimizer.get_budget_stats("query")
        assert stats["samples"] == 1
        assert stats["avg_actual_duration"] == 8.0

    def test_budget_adjustment_insufficient_data(self):
        """Test that adjustment requires minimum samples"""
        from core.adaptive_tuning import BudgetOptimizer, TaskPerformanceMetric

        optimizer = BudgetOptimizer()
        optimizer.min_samples = 5

        # Record only 3 samples
        for i in range(3):
            metric = TaskPerformanceMetric(
                task_type="query",
                actual_duration=12.0,  # Over budget
                budgeted_duration=10.0,
                mode="FOCUSED",
                success=True
            )
            optimizer.record_performance(metric)

        # Should not recommend adjustment with only 3 samples
        adjustment = optimizer.calculate_budget_adjustment("query")
        assert adjustment is None

    def test_budget_increase_recommendation(self):
        """Test recommending budget increase"""
        from core.adaptive_tuning import BudgetOptimizer, TaskPerformanceMetric

        optimizer = BudgetOptimizer()
        optimizer.min_samples = 5

        # Record tasks consistently exceeding budget with good success
        for i in range(10):
            metric = TaskPerformanceMetric(
                task_type="query",
                actual_duration=12.5,  # 25% over budget
                budgeted_duration=10.0,
                mode="FOCUSED",
                success=True  # Good success rate
            )
            optimizer.record_performance(metric)

        adjustment = optimizer.calculate_budget_adjustment("query")
        assert adjustment is not None
        assert adjustment > 1.0  # Should increase

    def test_budget_decrease_recommendation(self):
        """Test recommending budget decrease"""
        from core.adaptive_tuning import BudgetOptimizer, TaskPerformanceMetric

        optimizer = BudgetOptimizer()
        optimizer.min_samples = 5

        # Record tasks consistently under budget with great success
        for i in range(10):
            metric = TaskPerformanceMetric(
                task_type="query",
                actual_duration=6.0,  # 40% under budget
                budgeted_duration=10.0,
                mode="FOCUSED",
                success=True  # Excellent success
            )
            optimizer.record_performance(metric)

        adjustment = optimizer.calculate_budget_adjustment("query")
        assert adjustment is not None
        assert adjustment < 1.0  # Should decrease

    def test_multiple_task_types(self):
        """Test optimization across task types"""
        from core.adaptive_tuning import BudgetOptimizer, TaskPerformanceMetric

        optimizer = BudgetOptimizer()
        optimizer.min_samples = 3

        # Query tasks
        for i in range(5):
            optimizer.record_performance(TaskPerformanceMetric(
                task_type="query", actual_duration=5.0, budgeted_duration=10.0,
                mode="FOCUSED", success=True
            ))

        # File operation tasks
        for i in range(5):
            optimizer.record_performance(TaskPerformanceMetric(
                task_type="file_operation", actual_duration=20.0, budgeted_duration=15.0,
                mode="FOCUSED", success=True
            ))

        query_adj = optimizer.calculate_budget_adjustment("query")
        file_adj = optimizer.calculate_budget_adjustment("file_operation")

        # Query should suggest decrease, file should suggest increase
        assert query_adj is not None and query_adj < 1.0
        assert file_adj is not None and file_adj > 1.0


class TestModePreference:
    """Test mode learning"""

    def test_mode_success_rate_calculation(self):
        """Test success rate calculation for modes"""
        from core.adaptive_tuning import ModePreference

        pref = ModePreference()
        pref.focused_successes = 8
        pref.focused_attempts = 10
        pref.diffuse_successes = 6
        pref.diffuse_attempts = 10

        assert pref.get_success_rate("FOCUSED") == 80.0
        assert pref.get_success_rate("DIFFUSE") == 60.0

    def test_mode_recommendation_focused_better(self):
        """Test mode recommendation when FOCUSED is better"""
        from core.adaptive_tuning import ModePreference

        pref = ModePreference()
        pref.focused_successes = 9
        pref.focused_attempts = 10
        pref.diffuse_successes = 5
        pref.diffuse_attempts = 10

        mode = pref.recommend_mode()
        assert mode == "FOCUSED"

    def test_mode_recommendation_diffuse_better(self):
        """Test mode recommendation when DIFFUSE is better"""
        from core.adaptive_tuning import ModePreference

        pref = ModePreference()
        pref.focused_successes = 5
        pref.focused_attempts = 10
        pref.diffuse_successes = 9
        pref.diffuse_attempts = 10

        mode = pref.recommend_mode()
        assert mode == "DIFFUSE"

    def test_mode_recommendation_insufficient_data(self):
        """Test that recommendation defaults without enough data"""
        from core.adaptive_tuning import ModePreference

        pref = ModePreference()
        pref.focused_attempts = 2
        pref.diffuse_attempts = 0

        # Should default to FOCUSED when no DIFFUSE data
        mode = pref.recommend_mode()
        assert mode == "FOCUSED"


class TestDeadlockPredictor:
    """Test deadlock prediction"""

    def test_no_deadlock_history(self):
        """Test predictor with no history"""
        from core.adaptive_tuning import DeadlockPredictor

        predictor = DeadlockPredictor()
        risk, level = predictor.predict_risk("query")

        assert risk == 0.0
        assert level == "low"

    def test_low_risk_detection(self):
        """Test low risk detection"""
        from core.adaptive_tuning import DeadlockPredictor

        predictor = DeadlockPredictor(lookback_hours=24)

        # Record 2 deadlocks
        predictor.record_deadlock("query")
        predictor.record_deadlock("query")

        risk, level = predictor.predict_risk("query")
        assert risk == 0.2
        assert level == "low"

    def test_medium_risk_detection(self):
        """Test medium risk detection"""
        from core.adaptive_tuning import DeadlockPredictor

        predictor = DeadlockPredictor(lookback_hours=24)

        # Record 4 deadlocks
        for _ in range(4):
            predictor.record_deadlock("query")

        risk, level = predictor.predict_risk("query")
        assert risk == 0.5
        assert level == "medium"

    def test_high_risk_detection(self):
        """Test high risk detection"""
        from core.adaptive_tuning import DeadlockPredictor

        predictor = DeadlockPredictor(lookback_hours=24)

        # Record 7 deadlocks
        for _ in range(7):
            predictor.record_deadlock("query")

        risk, level = predictor.predict_risk("query")
        assert risk == 0.8
        assert level == "high"

    def test_old_deadlocks_ignored(self):
        """Test that old deadlocks don't affect risk"""
        from core.adaptive_tuning import DeadlockPredictor
        from datetime import datetime, timedelta
        import time

        predictor = DeadlockPredictor(lookback_hours=24)

        # Simulate an old deadlock by directly adding to history
        predictor._lock.acquire()
        predictor.deadlock_patterns["query"] = [
            datetime.now() - timedelta(hours=30)  # Old
        ]
        predictor._lock.release()

        # Current deadlock count should be 0
        risk, level = predictor.predict_risk("query")
        assert risk == 0.0
        assert level == "low"

    def test_risk_summary(self):
        """Test risk summary across task types"""
        from core.adaptive_tuning import DeadlockPredictor

        predictor = DeadlockPredictor()

        # Record deadlocks for multiple types
        predictor.record_deadlock("query")
        predictor.record_deadlock("file_operation")
        predictor.record_deadlock("file_operation")
        predictor.record_deadlock("file_operation")

        summary = predictor.get_risk_summary()

        assert "query" in summary
        assert "file_operation" in summary
        assert summary["query"]["count"] == 1
        assert summary["file_operation"]["count"] == 3


class TestConsolidationScheduler:
    """Test consolidation scheduling"""

    def test_first_consolidation_always_recommended(self):
        """Test that first consolidation is recommended"""
        from core.adaptive_tuning import ConsolidationScheduler

        scheduler = ConsolidationScheduler()

        # No consolidation yet
        assert scheduler.last_consolidation is None
        assert scheduler.should_consolidate_now() is True

    def test_consolidation_interval_respected(self):
        """Test that consolidations are spaced out"""
        from core.adaptive_tuning import ConsolidationScheduler
        from datetime import datetime, timedelta

        scheduler = ConsolidationScheduler()

        # Mark first consolidation
        scheduler.mark_consolidation()

        # Too soon - should not consolidate
        assert scheduler.should_consolidate_now() is False


    def test_recommended_consolidation_time(self):
        """Test consolidation time recommendation"""
        from core.adaptive_tuning import ConsolidationScheduler

        scheduler = ConsolidationScheduler()

        time_str = scheduler.recommend_consolidation_time()

        # Should be a valid time string
        assert isinstance(time_str, str)
        assert ":" in time_str
        parts = time_str.split(":")
        assert len(parts) == 2
        assert 0 <= int(parts[0]) < 24
        assert 0 <= int(parts[1]) < 60

    def test_consolidation_statistics(self):
        """Test consolidation statistics"""
        from core.adaptive_tuning import ConsolidationScheduler

        scheduler = ConsolidationScheduler()

        # Record some patterns
        for i in range(3):
            scheduler.record_pattern("test_pattern")

        stats = scheduler.get_consolidation_stats()

        assert "consolidations_since_startup" in stats
        assert "patterns_since_last" in stats
        assert stats["patterns_since_last"] == 3


class TestAdaptiveTuningEngine:
    """Test the main adaptive tuning engine"""

    def test_engine_initialization(self):
        """Test engine initializes properly"""
        from core.adaptive_tuning import AdaptiveTuningEngine

        engine = AdaptiveTuningEngine()

        assert engine.enabled is True
        assert engine.budget_optimizer is not None
        assert engine.deadlock_predictor is not None
        assert engine.consolidation_scheduler is not None

    def test_record_task_outcome(self):
        """Test recording task outcomes"""
        from core.adaptive_tuning import get_adaptive_tuning, reset_adaptive_tuning

        reset_adaptive_tuning()
        engine = get_adaptive_tuning()

        engine.record_task_outcome(
            task_type="query",
            actual_duration=8.0,
            budgeted_duration=10.0,
            mode="FOCUSED",
            success=True
        )

        # Should be recorded
        stats = engine.budget_optimizer.get_budget_stats("query")
        assert stats["samples"] == 1

    def test_mode_learning(self):
        """Test mode learning across task outcomes"""
        from core.adaptive_tuning import get_adaptive_tuning, reset_adaptive_tuning

        reset_adaptive_tuning()
        engine = get_adaptive_tuning()

        # Record FOCUSED successes
        for i in range(7):
            engine.record_task_outcome(
                task_type="query",
                actual_duration=8.0,
                budgeted_duration=10.0,
                mode="FOCUSED",
                success=True
            )

        # Record DIFFUSE failures
        for i in range(3):
            engine.record_task_outcome(
                task_type="query",
                actual_duration=12.0,
                budgeted_duration=10.0,
                mode="DIFFUSE",
                success=False
            )

        # Should prefer FOCUSED
        mode = engine.get_preferred_mode("query")
        assert mode == "FOCUSED"

    def test_deadlock_detection_in_outcomes(self):
        """Test that deadlock detection is recorded"""
        from core.adaptive_tuning import get_adaptive_tuning, reset_adaptive_tuning

        reset_adaptive_tuning()
        engine = get_adaptive_tuning()

        # Record outcome with deadlock
        engine.record_task_outcome(
            task_type="query",
            actual_duration=15.0,
            budgeted_duration=10.0,
            mode="FOCUSED",
            success=False,
            deadlock_detected=True
        )

        # Check deadlock was detected
        risk, level = engine.get_deadlock_risk("query")
        assert risk > 0.0

    def test_optimization_summary(self):
        """Test complete optimization summary"""
        from core.adaptive_tuning import get_adaptive_tuning, reset_adaptive_tuning

        reset_adaptive_tuning()
        engine = get_adaptive_tuning()

        # Record some data
        for i in range(5):
            engine.record_task_outcome(
                task_type="query",
                actual_duration=8.0,
                budgeted_duration=10.0,
                mode="FOCUSED",
                success=True
            )

        summary = engine.get_optimization_summary()

        assert "enabled" in summary
        assert "budget_optimizations" in summary
        assert "mode_preferences" in summary
        assert "deadlock_risks" in summary
        assert "consolidation_stats" in summary

    def test_engine_disabled_flag(self):
        """Test that disabled engine doesn't record data"""
        from core.adaptive_tuning import AdaptiveTuningEngine

        engine = AdaptiveTuningEngine()
        engine.enabled = False

        # Try to record - should be ignored
        engine.record_task_outcome(
            task_type="query",
            actual_duration=8.0,
            budgeted_duration=10.0,
            mode="FOCUSED",
            success=True
        )

        # No data should be recorded
        stats = engine.budget_optimizer.get_budget_stats("query")
        assert stats["samples"] == 0


class TestAdaptiveTuningIntegration:
    """Integration tests for adaptive tuning"""

    def test_full_learning_cycle(self):
        """Test complete learning cycle"""
        from core.adaptive_tuning import get_adaptive_tuning, reset_adaptive_tuning

        reset_adaptive_tuning()
        engine = get_adaptive_tuning()

        # Phase 1: Initial learning (FOCUSED mode)
        for i in range(10):
            engine.record_task_outcome(
                task_type="complex_analysis",
                actual_duration=250.0,
                budgeted_duration=300.0,
                mode="FOCUSED",
                success=True if i < 8 else False,  # 80% success
                deadlock_detected=False
            )

        # Check recommendations
        mode = engine.get_preferred_mode("complex_analysis")
        budget = engine.get_recommended_budget("complex_analysis", 300.0)

        assert mode in ("FOCUSED", "DIFFUSE")
        # Budget should be adjusted for good performance
        assert isinstance(budget, float)

    def test_concurrent_recording(self):
        """Test thread-safe concurrent recording"""
        from core.adaptive_tuning import get_adaptive_tuning, reset_adaptive_tuning
        import threading

        reset_adaptive_tuning()
        engine = get_adaptive_tuning()
        results = []

        def record_outcomes(task_id):
            for i in range(10):
                engine.record_task_outcome(
                    task_type=f"task_{task_id}",
                    actual_duration=float(i),
                    budgeted_duration=10.0,
                    mode="FOCUSED",
                    success=True
                )
                results.append(f"task_{task_id}_{i}")

        threads = [threading.Thread(target=record_outcomes, args=(i,)) for i in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All outcomes should be recorded safely
        assert len(results) == 30


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
