"""
Tests for Learning Engine module
"""

import pytest
import tempfile
from pathlib import Path
from core.learning_engine import LearningEngine, LearningMetrics, Pattern


class TestLearningMetrics:
    """Test LearningMetrics class"""

    def test_initialization(self):
        metrics = LearningMetrics()
        assert metrics.total_interactions == 0
        assert metrics.successful_interactions == 0
        assert metrics.user_confidence == 0.0

    def test_update_success(self):
        metrics = LearningMetrics()
        metrics.update("test_tool", success=True, duration=1.0)

        assert metrics.total_interactions == 1
        assert metrics.successful_interactions == 1
        assert metrics.tool_usage_count["test_tool"] == 1

    def test_update_failure(self):
        metrics = LearningMetrics()
        metrics.update("test_tool", success=False, duration=1.0)

        assert metrics.total_interactions == 1
        assert metrics.failed_interactions == 1

    def test_confidence_calculation(self):
        metrics = LearningMetrics()
        metrics.update("tool", success=True, duration=1.0)
        metrics.update("tool", success=True, duration=1.0)
        metrics.update("tool", success=False, duration=1.0)

        assert metrics.user_confidence == 2.0/3

    def test_to_dict(self):
        metrics = LearningMetrics()
        metrics.update("tool1", success=True, duration=1.0)

        result = metrics.to_dict()
        assert "total_interactions" in result
        assert "overall_success_rate" in result


class TestPattern:
    """Test Pattern class"""

    def test_pattern_creation(self):
        pattern = Pattern("p1", "tool1", {"param": "value"})
        assert pattern.pattern_id == "p1"
        assert pattern.tool == "tool1"
        assert pattern.confidence == 0.0

    def test_record_success(self):
        pattern = Pattern("p1", "tool1", {})
        pattern.record_success()

        assert pattern.success_count == 1
        assert pattern.confidence == 1.0

    def test_record_failure(self):
        pattern = Pattern("p1", "tool1", {})
        pattern.record_failure()

        assert pattern.failure_count == 1
        assert pattern.confidence == 0.0

    def test_confidence_update(self):
        pattern = Pattern("p1", "tool1", {})
        pattern.record_success()
        pattern.record_success()
        pattern.record_failure()

        assert pattern.confidence == 2.0/3


class TestLearningEngine:
    """Test LearningEngine class"""

    @pytest.fixture
    def engine(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = LearningEngine("test_user", tmpdir)
            yield engine

    def test_initialization(self, engine):
        assert engine.user_id == "test_user"
        assert len(engine.patterns) == 0

    def test_record_interaction(self, engine):
        result = engine.record_interaction(
            tool="tool1",
            input_params={"param1": "value1"},
            output={"result": "success"},
            success=True,
            duration=1.5
        )

        assert "Interaction recorded" in result
        assert len(engine.interaction_history) == 1

    def test_multiple_interactions(self, engine):
        for i in range(5):
            engine.record_interaction(
                tool="tool1",
                input_params={"i": i},
                output={},
                success=True,
                duration=1.0
            )

        assert len(engine.interaction_history) == 5
        assert engine.metrics.total_interactions == 5

    def test_analyze_patterns(self, engine):
        engine.record_interaction("tool1", {}, {}, True, 1.0)
        engine.record_interaction("tool2", {}, {}, True, 1.0)

        analysis = engine.analyze_patterns()
        assert "total_patterns" in analysis
        assert "most_used_tools" in analysis

    def test_get_recommendations(self, engine):
        engine.record_interaction("tool1", {}, {}, True, 1.0)
        engine.record_interaction("tool1", {}, {}, True, 1.0)

        recommendations = engine.get_recommendations(limit=5)
        # Should have recommendations if pattern confidence is high enough
        assert isinstance(recommendations, list)

    def test_evaluate_confidence(self, engine):
        engine.record_interaction("tool1", {}, {}, True, 1.0)

        patterns = list(engine.patterns.keys())
        if patterns:
            confidence = engine.evaluate_confidence(patterns[0])
            assert 0 <= confidence <= 1.0

    def test_update_user_model(self, engine):
        engine.record_interaction("tool1", {}, {}, True, 1.0)
        result = engine.update_user_model()

        assert "status" in result
        assert "metrics" in result
        assert "preferences" in result

    def test_get_user_profile(self, engine):
        engine.record_interaction("tool1", {}, {}, True, 1.0)
        profile = engine.get_user_profile()

        assert profile["user_id"] == "test_user"
        assert "metrics" in profile
        assert "patterns_count" in profile

    def test_export_learning(self, engine):
        engine.record_interaction("tool1", {}, {}, True, 1.0)
        exported = engine.export_learning()

        assert "user_id" in exported
        assert "metrics" in exported
        assert "patterns" in exported
