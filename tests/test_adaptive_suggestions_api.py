"""
Tests for Adaptive Suggestions API endpoints

Tests the integration of the adaptive engine with the dashboard API
and HTTP server routes.
"""

import pytest
import json
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

from api.dashboard_api import DashboardAPIv1


class TestSmartSuggestionsAPI:
    """Test smart suggestions API endpoint."""

    @pytest.fixture
    def api(self):
        """Create API instance."""
        with patch('api.dashboard_api.DashboardAPIv1._start_metrics_collector'):
            api = DashboardAPIv1()
            yield api

    def test_get_smart_suggestions_success(self, api):
        """Test getting smart suggestions."""
        with patch('core.adaptive_engine.get_adaptive_engine') as mock_engine:
            mock_adaptive = MagicMock()
            mock_adaptive.get_smart_suggestions.return_value = [
                {"action": "task1", "reason": "common", "confidence": 0.9},
                {"action": "task2", "reason": "frequent", "confidence": 0.7}
            ]
            mock_engine.return_value = mock_adaptive

            result = api.get_smart_suggestions()
            assert result["success"] is True
            assert result["count"] == 2
            assert len(result["suggestions"]) == 2

    def test_get_smart_suggestions_with_context(self, api):
        """Test getting suggestions with custom context."""
        with patch('core.adaptive_engine.get_adaptive_engine') as mock_engine:
            mock_adaptive = MagicMock()
            mock_adaptive.get_smart_suggestions.return_value = []
            mock_engine.return_value = mock_adaptive

            context = {"last_action": "deploy", "session_count": 5}
            result = api.get_smart_suggestions(context)

            # Verify context was passed and enriched
            mock_adaptive.get_smart_suggestions.assert_called_once()
            called_context = mock_adaptive.get_smart_suggestions.call_args[0][0]
            assert "time_of_day" in called_context
            assert "last_action" in called_context
            assert result["success"] is True

    def test_get_smart_suggestions_error_handling(self, api):
        """Test error handling in smart suggestions."""
        with patch('core.adaptive_engine.get_adaptive_engine') as mock_engine:
            mock_engine.side_effect = Exception("Engine error")

            result = api.get_smart_suggestions()
            assert result["success"] is False
            assert "error" in result


class TestAdaptiveResponseAPI:
    """Test adaptive response API endpoint."""

    @pytest.fixture
    def api(self):
        """Create API instance."""
        with patch('api.dashboard_api.DashboardAPIv1._start_metrics_collector'):
            api = DashboardAPIv1()
            yield api

    def test_get_adaptive_response_success(self, api):
        """Test getting adaptive response."""
        with patch('core.adaptive_engine.get_adaptive_engine') as mock_engine:
            mock_adaptive = MagicMock()
            mock_adaptive.get_adaptive_response.return_value = {
                "success": True,
                "recommended_action": "action_a",
                "confidence": 0.85,
                "alternatives": ["action_b"],
                "reasoning": "Based on pattern"
            }
            mock_engine.return_value = mock_adaptive

            result = api.get_adaptive_response(
                intent="file_operation",
                available_actions=["action_a", "action_b", "action_c"],
                context={"session_count": 5}
            )

            assert result["success"] is True
            assert result["recommended_action"] == "action_a"
            assert result["confidence"] == 0.85

    def test_get_adaptive_response_empty_actions(self, api):
        """Test adaptive response with empty action list."""
        with patch('core.adaptive_engine.get_adaptive_engine') as mock_engine:
            mock_adaptive = MagicMock()
            mock_adaptive.get_adaptive_response.return_value = {
                "success": False,
                "error": "No actions to score"
            }
            mock_engine.return_value = mock_adaptive

            result = api.get_adaptive_response(
                intent="test",
                available_actions=[],
                context={}
            )

            assert result["success"] is False
            assert "error" in result

    def test_get_adaptive_response_with_context(self, api):
        """Test that context is passed through correctly."""
        with patch('core.adaptive_engine.get_adaptive_engine') as mock_engine:
            mock_adaptive = MagicMock()
            mock_adaptive.get_adaptive_response.return_value = {"success": True}
            mock_engine.return_value = mock_adaptive

            context = {"session_id": "sess_123", "user": "test"}
            result = api.get_adaptive_response(
                intent="test_intent",
                available_actions=["a", "b"],
                context=context
            )

            # Verify the exact context was passed
            call_args = mock_adaptive.get_adaptive_response.call_args
            assert call_args[0][0] == "test_intent"
            assert call_args[0][2] == ["a", "b"]
            assert call_args[0][1] == context


class TestLearningRecordAPI:
    """Test learning record API endpoint."""

    @pytest.fixture
    def api(self):
        """Create API instance."""
        with patch('api.dashboard_api.DashboardAPIv1._start_metrics_collector'):
            api = DashboardAPIv1()
            yield api

    def test_learn_interaction_success(self, api):
        """Test recording a successful interaction."""
        with patch('core.adaptive_engine.get_adaptive_engine') as mock_engine:
            mock_adaptive = MagicMock()
            mock_engine.return_value = mock_adaptive

            result = api.learn_interaction(
                intent="file_operation",
                action="create_file",
                success=True,
                context={"path": "/tmp/test"},
                duration=1.5
            )

            assert result["success"] is True
            assert "create_file" in result["message"]
            mock_adaptive.learn_from_interaction.assert_called_once_with(
                "file_operation",
                "create_file",
                True,
                {"path": "/tmp/test"},
                1.5
            )

    def test_learn_interaction_failure(self, api):
        """Test recording a failed interaction."""
        with patch('core.adaptive_engine.get_adaptive_engine') as mock_engine:
            mock_adaptive = MagicMock()
            mock_engine.return_value = mock_adaptive

            result = api.learn_interaction(
                intent="research",
                action="search",
                success=False,
                context={},
                duration=2.0
            )

            assert result["success"] is True
            assert "failed" in result["message"]
            mock_adaptive.learn_from_interaction.assert_called_once_with(
                "research",
                "search",
                False,
                {},
                2.0
            )

    def test_learn_interaction_default_context(self, api):
        """Test learning with default empty context."""
        with patch('core.adaptive_engine.get_adaptive_engine') as mock_engine:
            mock_adaptive = MagicMock()
            mock_engine.return_value = mock_adaptive

            result = api.learn_interaction(
                intent="test",
                action="action",
                success=True,
                context=None,  # Should default to {}
                duration=0.5
            )

            assert result["success"] is True
            mock_adaptive.learn_from_interaction.assert_called_once()
            call_args = mock_adaptive.learn_from_interaction.call_args
            assert call_args[0][3] == {}  # context argument

    def test_learn_interaction_error_handling(self, api):
        """Test error handling when learning fails."""
        with patch('core.adaptive_engine.get_adaptive_engine') as mock_engine:
            mock_engine.side_effect = Exception("Learning error")

            result = api.learn_interaction(
                intent="test",
                action="test",
                success=True,
                context={},
                duration=1.0
            )

            assert result["success"] is False
            assert "error" in result


class TestGetTimeOfDay:
    """Test time of day helper method."""

    def test_morning_time(self):
        """Test morning time categorization."""
        with patch('api.dashboard_api.datetime') as mock_dt:
            mock_dt.now.return_value = MagicMock(hour=9)
            result = DashboardAPIv1._get_time_of_day()
            assert result == "morning"

    def test_afternoon_time(self):
        """Test afternoon time categorization."""
        with patch('api.dashboard_api.datetime') as mock_dt:
            mock_dt.now.return_value = MagicMock(hour=14)
            result = DashboardAPIv1._get_time_of_day()
            assert result == "afternoon"

    def test_evening_time(self):
        """Test evening time categorization."""
        with patch('api.dashboard_api.datetime') as mock_dt:
            mock_dt.now.return_value = MagicMock(hour=19)
            result = DashboardAPIv1._get_time_of_day()
            assert result == "evening"

    def test_night_time(self):
        """Test night time categorization."""
        with patch('api.dashboard_api.datetime') as mock_dt:
            mock_dt.now.return_value = MagicMock(hour=23)
            result = DashboardAPIv1._get_time_of_day()
            assert result == "night"

    def test_boundary_times(self):
        """Test boundary hour cases."""
        with patch('api.dashboard_api.datetime') as mock_dt:
            # 5:00 should be morning
            mock_dt.now.return_value = MagicMock(hour=5)
            assert DashboardAPIv1._get_time_of_day() == "morning"

            # 12:00 should be afternoon
            mock_dt.now.return_value = MagicMock(hour=12)
            assert DashboardAPIv1._get_time_of_day() == "afternoon"

            # 17:00 should be evening
            mock_dt.now.return_value = MagicMock(hour=17)
            assert DashboardAPIv1._get_time_of_day() == "evening"

            # 21:00 should be night
            mock_dt.now.return_value = MagicMock(hour=21)
            assert DashboardAPIv1._get_time_of_day() == "night"
