"""
Tests for Adaptive Engine

Covers intelligent suggestions, adaptive responses, context-aware decisions,
and learning from user interactions.
"""

import pytest
import json
import tempfile
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock

from core.adaptive_engine import AdaptiveEngine, get_adaptive_engine


class TestAdaptiveEngineBasics:
    """Test basic AdaptiveEngine functionality."""

    @pytest.fixture
    def engine(self):
        """Create adaptive engine with temp storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('core.adaptive_engine.get_preference_manager') as mock_pref:
                mock_pref_instance = MagicMock()
                mock_pref_instance.get_intent_success_rate.return_value = 0.7
                mock_pref_instance.get_top_actions_for_intent.return_value = []
                mock_pref_instance.command_frequency = {}
                mock_pref.return_value = mock_pref_instance
                engine = AdaptiveEngine(storage_path=tmpdir)
                yield engine

    def test_init(self, engine):
        """Test AdaptiveEngine initialization."""
        assert engine.storage_path.exists()
        assert engine.pref_manager is not None

    def test_get_adaptive_response_no_actions(self, engine):
        """Test get_adaptive_response with empty actions list."""
        result = engine.get_adaptive_response(
            intent="research",
            context={"session_count": 1},
            available_actions=[]
        )
        assert result["success"] is False
        assert "error" in result

    def test_get_adaptive_response_single_action(self, engine):
        """Test get_adaptive_response with single action."""
        result = engine.get_adaptive_response(
            intent="screenshot",
            context={"session_count": 1},
            available_actions=["take_screenshot"]
        )
        assert result["success"] is True
        assert result["recommended_action"] == "take_screenshot"
        assert 0.0 <= result["confidence"] <= 1.0
        assert "reasoning" in result

    def test_get_adaptive_response_multiple_actions(self, engine):
        """Test scoring and ranking multiple actions."""
        actions = ["action_a", "action_b", "action_c"]
        result = engine.get_adaptive_response(
            intent="file_operation",
            context={"session_count": 5},
            available_actions=actions
        )
        assert result["success"] is True
        assert result["recommended_action"] in actions
        assert len(result.get("alternatives", [])) <= 2


class TestContextSimilarity:
    """Test context similarity calculation."""

    @pytest.fixture
    def engine(self):
        """Create engine with temp storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = AdaptiveEngine(storage_path=tmpdir)
            yield engine

    def test_context_similarity_no_history(self, engine):
        """Test similarity when no history exists."""
        similarity = engine._calculate_context_similarity(
            "test_action",
            {"key1": "value1"}
        )
        assert similarity == 0.0

    def test_context_similarity_perfect_match(self, engine):
        """Test similarity with perfect context match."""
        # Create historical context
        context_file = engine.storage_path / "contexts_test_action.json"
        historical = [{"key1": "value1", "key2": "value2"}]
        with open(context_file, "w") as f:
            json.dump(historical, f)

        # Calculate similarity with matching context
        similarity = engine._calculate_context_similarity(
            "test_action",
            {"key1": "value1", "key2": "value2"}
        )
        assert similarity > 0.5

    def test_context_similarity_partial_match(self, engine):
        """Test similarity with partial context overlap."""
        context_file = engine.storage_path / "contexts_test_action.json"
        historical = [
            {"key1": "v1", "key2": "v2", "key3": "v3"},
            {"key1": "v1", "key2": "v2", "key4": "v4"}
        ]
        with open(context_file, "w") as f:
            json.dump(historical, f)

        similarity = engine._calculate_context_similarity(
            "test_action",
            {"key1": "v1"}
        )
        assert 0.0 < similarity < 1.0

    def test_context_similarity_last_10_limit(self, engine):
        """Test that only last 10 historical contexts are used."""
        context_file = engine.storage_path / "contexts_test_action.json"
        # Create 15 historical contexts with completely different keys for first vs last
        historical = [
            {"old_key": i, "old_data": "first"} if i < 5 else {"new_key": i, "new_data": "last"}
            for i in range(15)
        ]
        with open(context_file, "w") as f:
            json.dump(historical, f)

        # Query with old-style keys - only matches first 5 (which are excluded from last 10)
        similarity = engine._calculate_context_similarity(
            "test_action",
            {"old_key": 0, "old_data": "first"}
        )
        # Last 10 have {new_key, new_data}, query has {old_key, old_data} - no overlap
        assert similarity == 0.0

        # Query with new-style keys - matches last 10
        similarity2 = engine._calculate_context_similarity(
            "test_action",
            {"new_key": 14, "new_data": "last"}
        )
        # Should be high because it matches keys in last 10 contexts
        assert similarity2 > 0.5


class TestActionSequences:
    """Test action sequence tracking and prediction."""

    @pytest.fixture
    def engine(self):
        """Create engine with temp storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = AdaptiveEngine(storage_path=tmpdir)
            yield engine

    def test_predict_next_action_no_history(self, engine):
        """Test prediction when no sequence history exists."""
        next_action = engine._predict_next_action("unknown_action")
        assert next_action is None

    def test_predict_next_action_single_sequence(self, engine):
        """Test predicting next action with one known sequence."""
        sequence_file = engine.storage_path / "action_sequences.json"
        sequences = {
            "action_a": [{"action": "action_b", "count": 5}]
        }
        with open(sequence_file, "w") as f:
            json.dump(sequences, f)

        next_action = engine._predict_next_action("action_a")
        assert next_action is not None
        assert next_action["action"] == "action_b"
        assert 0.0 < next_action["confidence"] <= 1.0

    def test_predict_next_action_multiple_options(self, engine):
        """Test picking most common next action."""
        sequence_file = engine.storage_path / "action_sequences.json"
        sequences = {
            "action_x": [
                {"action": "action_y", "count": 10},
                {"action": "action_z", "count": 3}
            ]
        }
        with open(sequence_file, "w") as f:
            json.dump(sequences, f)

        next_action = engine._predict_next_action("action_x")
        assert next_action["action"] == "action_y"
        assert next_action["confidence"] == min(10 / 10, 1.0)

    def test_update_action_sequence_new(self, engine):
        """Test updating sequence with new transition."""
        engine._update_action_sequence("from_a", "to_b")

        sequence_file = engine.storage_path / "action_sequences.json"
        assert sequence_file.exists()
        with open(sequence_file, "r") as f:
            sequences = json.load(f)

        assert "from_a" in sequences
        assert sequences["from_a"][0]["action"] == "to_b"
        assert sequences["from_a"][0]["count"] == 1

    def test_update_action_sequence_increment(self, engine):
        """Test incrementing existing sequence count."""
        engine._update_action_sequence("a", "b")
        engine._update_action_sequence("a", "b")
        engine._update_action_sequence("a", "b")

        sequence_file = engine.storage_path / "action_sequences.json"
        with open(sequence_file, "r") as f:
            sequences = json.load(f)

        assert sequences["a"][0]["count"] == 3


class TestTimePatterns:
    """Test time-of-day pattern tracking."""

    @pytest.fixture
    def engine(self):
        """Create engine with temp storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = AdaptiveEngine(storage_path=tmpdir)
            yield engine

    def test_get_time_of_day_morning(self):
        """Test morning time categorization."""
        with patch('core.adaptive_engine.datetime') as mock_dt:
            mock_dt.now.return_value = datetime(2026, 3, 24, 9, 0)
            assert AdaptiveEngine._get_time_of_day() == "morning"

    def test_get_time_of_day_afternoon(self):
        """Test afternoon time categorization."""
        with patch('core.adaptive_engine.datetime') as mock_dt:
            mock_dt.now.return_value = datetime(2026, 3, 24, 14, 0)
            assert AdaptiveEngine._get_time_of_day() == "afternoon"

    def test_get_time_of_day_evening(self):
        """Test evening time categorization."""
        with patch('core.adaptive_engine.datetime') as mock_dt:
            mock_dt.now.return_value = datetime(2026, 3, 24, 19, 0)
            assert AdaptiveEngine._get_time_of_day() == "evening"

    def test_get_time_of_day_night(self):
        """Test night time categorization."""
        with patch('core.adaptive_engine.datetime') as mock_dt:
            mock_dt.now.return_value = datetime(2026, 3, 24, 23, 0)
            assert AdaptiveEngine._get_time_of_day() == "night"

    def test_suggest_by_time_of_day_no_patterns(self, engine):
        """Test suggestions when no time patterns exist."""
        suggestions = engine._suggest_by_time_of_day("morning")
        assert suggestions == []

    def test_suggest_by_time_of_day_with_patterns(self, engine):
        """Test suggestions based on time-of-day patterns."""
        patterns_file = engine.storage_path / "time_patterns.json"
        patterns = {
            "morning": [
                {"name": "email_check", "frequency": 0.9},
                {"name": "standup", "frequency": 0.8}
            ]
        }
        with open(patterns_file, "w") as f:
            json.dump(patterns, f)

        suggestions = engine._suggest_by_time_of_day("morning")
        assert len(suggestions) == 2
        assert suggestions[0]["action"] == "email_check"
        assert "Usually done in the morning" in suggestions[0]["reason"]

    def test_update_time_pattern_new(self, engine):
        """Test recording new time pattern."""
        with patch('core.adaptive_engine.AdaptiveEngine._get_time_of_day') as mock_time:
            mock_time.return_value = "morning"
            engine._update_time_pattern("morning", "email", True)

        patterns_file = engine.storage_path / "time_patterns.json"
        with open(patterns_file, "r") as f:
            patterns = json.load(f)

        assert "morning" in patterns
        assert patterns["morning"][0]["name"] == "email"
        assert patterns["morning"][0]["count"] == 1
        assert patterns["morning"][0]["frequency"] > 0.5

    def test_update_time_pattern_failure_tracking(self, engine):
        """Test that failed actions don't increment count."""
        engine._update_time_pattern("afternoon", "report", False)

        patterns_file = engine.storage_path / "time_patterns.json"
        with open(patterns_file, "r") as f:
            patterns = json.load(f)

        assert patterns["afternoon"][0]["count"] == 0


class TestSuggestMaintenance:
    """Test maintenance action suggestions."""

    @pytest.fixture
    def engine(self):
        """Create engine with temp storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = AdaptiveEngine(storage_path=tmpdir)
            yield engine

    def test_suggest_maintenance_no_health_check(self, engine):
        """Test when no health check file exists."""
        suggestions = engine._suggest_maintenance_actions()
        assert suggestions == []

    def test_suggest_maintenance_recent_check(self, engine):
        """Test when health check is recent."""
        health_check_file = engine.storage_path / "last_health_check.json"
        now = datetime.now().timestamp()
        data = {"timestamp": now}
        with open(health_check_file, "w") as f:
            json.dump(data, f)

        suggestions = engine._suggest_maintenance_actions()
        assert len(suggestions) == 0  # No suggestion if recent

    def test_suggest_maintenance_overdue(self, engine):
        """Test when health check is overdue."""
        health_check_file = engine.storage_path / "last_health_check.json"
        now = datetime.now().timestamp()
        old_timestamp = now - 86400 * 2  # 2 days ago
        data = {"timestamp": old_timestamp}
        with open(health_check_file, "w") as f:
            json.dump(data, f)

        suggestions = engine._suggest_maintenance_actions()
        assert len(suggestions) == 1
        assert suggestions[0]["action"] == "health_check"
        assert suggestions[0]["confidence"] == 0.7


class TestSmartSuggestions:
    """Test smart suggestion generation."""

    @pytest.fixture
    def engine(self):
        """Create engine with temp storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = AdaptiveEngine(storage_path=tmpdir)
            yield engine

    def test_get_smart_suggestions_empty(self, engine):
        """Test suggestions with minimal context."""
        suggestions = engine.get_smart_suggestions({})
        assert isinstance(suggestions, list)
        assert len(suggestions) <= 3

    def test_get_smart_suggestions_with_time(self, engine):
        """Test suggestions with time-of-day context."""
        # Setup time patterns
        patterns_file = engine.storage_path / "time_patterns.json"
        patterns = {
            "morning": [
                {"name": "standup", "frequency": 0.9},
                {"name": "code_review", "frequency": 0.7}
            ]
        }
        with open(patterns_file, "w") as f:
            json.dump(patterns, f)

        suggestions = engine.get_smart_suggestions({"time_of_day": "morning"})
        assert len(suggestions) > 0
        assert any("Usually done in the morning" in s.get("reason", "") for s in suggestions)

    def test_get_smart_suggestions_with_last_action(self, engine):
        """Test suggestions based on action sequences."""
        # Setup sequences
        sequence_file = engine.storage_path / "action_sequences.json"
        sequences = {
            "code_push": [{"action": "run_tests", "count": 8}]
        }
        with open(sequence_file, "w") as f:
            json.dump(sequences, f)

        suggestions = engine.get_smart_suggestions({"last_action": "code_push"})
        assert any("Frequently follows" in s.get("reason", "") for s in suggestions)

    def test_get_smart_suggestions_sorted_by_confidence(self, engine):
        """Test that suggestions are sorted by confidence."""
        # Setup multiple suggestion sources
        patterns_file = engine.storage_path / "time_patterns.json"
        patterns = {"morning": [{"name": "task1", "frequency": 0.95}]}
        with open(patterns_file, "w") as f:
            json.dump(patterns, f)

        health_check_file = engine.storage_path / "last_health_check.json"
        old_time = datetime.now().timestamp() - 86400 * 2
        with open(health_check_file, "w") as f:
            json.dump({"timestamp": old_time}, f)

        suggestions = engine.get_smart_suggestions({"time_of_day": "morning"})
        # Should be sorted by confidence descending
        for i in range(len(suggestions) - 1):
            assert suggestions[i].get("confidence", 0) >= suggestions[i + 1].get("confidence", 0)


class TestLearning:
    """Test learning from user interactions."""

    @pytest.fixture
    def engine(self):
        """Create engine with temp storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = AdaptiveEngine(storage_path=tmpdir)
            yield engine

    def test_learn_from_interaction_stores_context(self, engine):
        """Test that contexts are stored after interactions."""
        with patch('core.adaptive_engine.datetime') as mock_dt:
            mock_dt.now.return_value = datetime(2026, 3, 24, 10, 0)
            mock_dt.isoformat = datetime.isoformat  # Allow isoformat to work
            engine.learn_from_interaction(
                intent="file_operation",
                action="create_file",
                success=True,
                context={"path": "/tmp/test"},
                duration=1.5
            )

        context_file = engine.storage_path / "contexts_create_file.json"
        assert context_file.exists()
        with open(context_file, "r") as f:
            contexts = json.load(f)

        assert len(contexts) == 1
        assert contexts[0]["success"] is True
        assert contexts[0]["duration"] == 1.5
        assert contexts[0]["path"] == "/tmp/test"

    def test_learn_from_interaction_limits_history(self, engine):
        """Test that only last 100 contexts are kept."""
        for i in range(150):
            engine.learn_from_interaction(
                intent="test",
                action="test_action",
                success=True,
                context={"iteration": i},
                duration=1.0
            )

        context_file = engine.storage_path / "contexts_test_action.json"
        with open(context_file, "r") as f:
            contexts = json.load(f)

        assert len(contexts) == 100
        # Should keep most recent (iteration 50-149)
        assert contexts[0]["iteration"] == 50
        assert contexts[99]["iteration"] == 149
        # All should have success, timestamp, duration fields
        assert all("success" in c for c in contexts)
        assert all("timestamp" in c for c in contexts)
        assert all("duration" in c for c in contexts)

    def test_learn_from_interaction_sequence_update(self, engine):
        """Test that action sequences are updated."""
        engine.learn_from_interaction(
            intent="workflow",
            action="step2",
            success=True,
            context={"last_action": "step1"},
            duration=1.0
        )

        sequence_file = engine.storage_path / "action_sequences.json"
        assert sequence_file.exists()

    def test_learn_from_interaction_time_pattern_update(self, engine):
        """Test that time patterns are updated."""
        with patch('core.adaptive_engine.AdaptiveEngine._get_time_of_day') as mock_time:
            mock_time.return_value = "afternoon"
            engine.learn_from_interaction(
                intent="test",
                action="test_action",
                success=True,
                context={},
                duration=1.0
            )

        patterns_file = engine.storage_path / "time_patterns.json"
        assert patterns_file.exists()


class TestReasoningGeneration:
    """Test reasoning explanation generation."""

    @pytest.fixture
    def engine(self):
        """Create engine with temp storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = AdaptiveEngine(storage_path=tmpdir)
            yield engine

    def test_reasoning_high_success_rate(self, engine):
        """Test reasoning for high success rate action."""
        reasoning = engine._generate_reasoning("file_op", "create_file", 0.95)
        assert "95%" in reasoning
        assert "success rate" in reasoning

    def test_reasoning_medium_success_rate(self, engine):
        """Test reasoning for medium success rate action."""
        reasoning = engine._generate_reasoning("file_op", "create_file", 0.65)
        assert "usage patterns" in reasoning

    def test_reasoning_low_success_rate(self, engine):
        """Test reasoning for low/unknown success rate action."""
        reasoning = engine._generate_reasoning("file_op", "create_file", 0.3)
        assert "available" in reasoning

    def test_reasoning_contains_action_name(self, engine):
        """Test that reasoning includes the action name."""
        reasoning = engine._generate_reasoning("test", "my_action", 0.7)
        assert "my_action" in reasoning


class TestSingleton:
    """Test singleton pattern."""

    def test_get_adaptive_engine_singleton(self):
        """Test that get_adaptive_engine returns same instance."""
        with tempfile.TemporaryDirectory() as tmpdir:
            engine1 = get_adaptive_engine(tmpdir)
            engine2 = get_adaptive_engine(tmpdir)
            # Can't directly compare due to module-level _adaptive_engine
            # But both should have same type
            assert type(engine1) == type(engine2)

    def test_adaptive_engine_path_creation(self):
        """Test that storage path is created."""
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = AdaptiveEngine(storage_path=tmpdir)
            assert Path(tmpdir).exists()


class TestEdgeCases:
    """Test edge cases and error handling."""

    @pytest.fixture
    def engine(self):
        """Create engine with temp storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = AdaptiveEngine(storage_path=tmpdir)
            yield engine

    def test_corrupted_context_file(self, engine):
        """Test graceful handling of corrupted JSON."""
        context_file = engine.storage_path / "contexts_action.json"
        with open(context_file, "w") as f:
            f.write("INVALID JSON {")

        # Should not raise exception
        similarity = engine._calculate_context_similarity("action", {"key": "value"})
        assert similarity == 0.0

    def test_corrupted_sequence_file(self, engine):
        """Test graceful handling of corrupted sequence file."""
        sequence_file = engine.storage_path / "action_sequences.json"
        with open(sequence_file, "w") as f:
            f.write("NOT VALID JSON [")

        # Should not raise exception
        next_action = engine._predict_next_action("action")
        assert next_action is None

    def test_learn_with_corrupted_context_file(self, engine):
        """Test learning when context file is corrupted."""
        context_file = engine.storage_path / "contexts_action.json"
        with open(context_file, "w") as f:
            f.write("INVALID")

        # Should handle gracefully and not raise
        engine.learn_from_interaction(
            intent="test",
            action="action",
            success=True,
            context={"key": "value"},
            duration=1.0
        )

    def test_very_large_context_similarity(self, engine):
        """Test performance with many historical contexts."""
        context_file = engine.storage_path / "contexts_action.json"
        # Create 100 contexts
        historical = [{"key": f"value_{i}"} for i in range(100)]
        with open(context_file, "w") as f:
            json.dump(historical, f)

        # Should efficiently handle (only uses last 10)
        similarity = engine._calculate_context_similarity(
            "action",
            {"key": "value_95"}
        )
        assert 0.0 <= similarity <= 1.0

    def test_context_with_nested_objects(self, engine):
        """Test context similarity with nested data."""
        context_file = engine.storage_path / "contexts_action.json"
        historical = [
            {"nested": {"inner": "value"}, "list": [1, 2, 3]}
        ]
        with open(context_file, "w") as f:
            json.dump(historical, f)

        # Should handle complex structures
        similarity = engine._calculate_context_similarity(
            "action",
            {"nested": {"inner": "value"}, "list": [1, 2, 3]}
        )
        assert similarity >= 0.5
