"""
Tests for Predictive Assistant
"""

import pytest
from core.predictive_assistant import PredictiveAssistant, Suggestion


class TestSuggestion:
    """Test Suggestion class"""

    def test_suggestion_creation(self):
        suggestion = Suggestion("Take action", 0.85, "Based on pattern")
        
        assert suggestion.action == "Take action"
        assert suggestion.confidence == 0.85
        assert suggestion.reason == "Based on pattern"

    def test_suggestion_to_dict(self):
        suggestion = Suggestion("Action", 0.9, "Reason")
        result = suggestion.to_dict()

        assert result["action"] == "Action"
        assert result["confidence"] == 0.9


class TestPredictiveAssistant:
    """Test PredictiveAssistant class"""

    @pytest.fixture
    def assistant(self):
        return PredictiveAssistant()

    def test_initialization(self, assistant):
        assert assistant.accuracy == 0.0
        assert len(assistant.prediction_history) == 0

    def test_predict_next_step(self, assistant):
        suggestions = assistant.predict_next_step()

        assert isinstance(suggestions, list)

    def test_anticipate_problems(self, assistant):
        problems = assistant.anticipate_problems()

        assert isinstance(problems, list)
        if problems:
            assert "issue" in problems[0]
            assert "probability" in problems[0]

    def test_suggest_optimization(self, assistant):
        suggestions = assistant.suggest_optimization()

        assert isinstance(suggestions, list)
        assert len(suggestions) > 0

    def test_estimate_resource_needs(self, assistant):
        estimation = assistant.estimate_resource_needs()

        assert "time_estimate" in estimation
        assert "complexity_level" in estimation
        assert "estimated_cost" in estimation

    def test_recommend_tools(self, assistant):
        tools = assistant.recommend_tools()

        assert isinstance(tools, list)
        if tools:
            assert "tool" in tools[0]
            assert "confidence" in tools[0]

    def test_record_prediction(self, assistant):
        assistant.record_prediction("test_action", True)
        
        assert len(assistant.prediction_history) == 1
        assert assistant.accuracy > 0

    def test_record_multiple_predictions(self, assistant):
        assistant.record_prediction("action1", True)
        assistant.record_prediction("action2", True)
        assistant.record_prediction("action3", False)

        assert len(assistant.prediction_history) == 3
        assert assistant.accuracy == 2.0/3

    def test_get_assistance_score(self, assistant):
        score = assistant.get_assistance_score()

        assert 0 <= score <= 1.0

    def test_get_insights(self, assistant):
        assistant.record_prediction("test", True)
        insights = assistant.get_insights()

        assert "prediction_accuracy" in insights
        assert "total_predictions" in insights
        assert "assistance_quality" in insights
