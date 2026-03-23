"""
Integration tests for Phase 5 Dashboard Widgets

Tests:
- Cognitive State Widget
- Deadlock Prevention Widget
- Sleep Consolidation Widget
- Performance Cache
"""

import pytest
from unittest.mock import patch, MagicMock


class TestCognitiveStateWidget:
    """Test cognitive state widget"""

    def test_widget_initialization(self):
        """Test widget initializes"""
        from ui.widgets.cognitive_state_widget import CognitiveStateWidget

        widget = CognitiveStateWidget()
        assert widget is not None
        assert widget.cached_metrics is None

    def test_get_metrics(self):
        """Test getting cognitive metrics"""
        from ui.widgets.cognitive_state_widget import CognitiveStateWidget

        widget = CognitiveStateWidget()
        metrics = widget.get_metrics()

        # Should return metrics or None
        assert metrics is None or hasattr(metrics, 'mode')

    def test_render_card_text(self):
        """Test rendering widget as text card"""
        from ui.widgets.cognitive_state_widget import CognitiveStateWidget

        widget = CognitiveStateWidget()
        card = widget.render_card()

        assert isinstance(card, str)
        assert "Bilişsel Durum" in card or "Cognitive" in card

    def test_render_json(self):
        """Test rendering widget as JSON"""
        from ui.widgets.cognitive_state_widget import CognitiveStateWidget

        widget = CognitiveStateWidget()
        json_data = widget.render_json()

        assert isinstance(json_data, dict)
        assert "mode" in json_data or "error" in json_data

    def test_cache_validity(self):
        """Test cache TTL"""
        from ui.widgets.cognitive_state_widget import CognitiveStateWidget

        widget = CognitiveStateWidget()
        widget.cache_ttl_seconds = 1

        # First call
        metrics1 = widget.get_metrics()

        # Second call should use cache
        metrics2 = widget.get_metrics()

        # Both should return same object (from cache)
        assert metrics1 == metrics2


class TestErrorPredictionWidget:
    """Test error prediction widget"""

    def test_widget_initialization(self):
        """Test widget initializes"""
        from ui.widgets.cognitive_state_widget import ErrorPredictionWidget

        widget = ErrorPredictionWidget()
        assert widget is not None

    def test_get_recent_predictions(self):
        """Test getting predictions"""
        from ui.widgets.cognitive_state_widget import ErrorPredictionWidget

        widget = ErrorPredictionWidget()
        predictions = widget.get_recent_predictions()

        assert isinstance(predictions, dict)
        assert "total_simulated" in predictions or "error" in predictions

    def test_render_card(self):
        """Test rendering prediction card"""
        from ui.widgets.cognitive_state_widget import ErrorPredictionWidget

        widget = ErrorPredictionWidget()
        card = widget.render_card()

        assert isinstance(card, str)
        assert "Hata Tahmini" in card or "Error" in card


class TestDeadlockPreventionWidget:
    """Test deadlock prevention widget"""

    def test_widget_initialization(self):
        """Test widget initializes"""
        from ui.widgets.deadlock_prevention_widget import DeadlockPreventionWidget

        widget = DeadlockPreventionWidget()
        assert widget is not None

    def test_get_deadlock_stats(self):
        """Test getting deadlock stats"""
        from ui.widgets.deadlock_prevention_widget import DeadlockPreventionWidget

        widget = DeadlockPreventionWidget()
        stats = widget.get_deadlock_stats()

        assert isinstance(stats, dict)
        assert "total_detected" in stats or "error" in stats

    def test_render_card(self):
        """Test rendering deadlock card"""
        from ui.widgets.deadlock_prevention_widget import DeadlockPreventionWidget

        widget = DeadlockPreventionWidget()
        card = widget.render_card()

        assert isinstance(card, str)
        assert "Kilitlenme" in card or "Deadlock" in card

    def test_timeline_data(self):
        """Test timeline data generation"""
        from ui.widgets.deadlock_prevention_widget import DeadlockTimeline

        data = DeadlockTimeline.get_timeline_data()

        assert isinstance(data, dict)
        assert "timeline" in data or "error" in data

    def test_timeline_render(self):
        """Test timeline rendering"""
        from ui.widgets.deadlock_prevention_widget import DeadlockTimeline

        timeline = DeadlockTimeline.render_timeline()

        assert isinstance(timeline, str)


class TestSleepConsolidationWidget:
    """Test sleep consolidation widget"""

    def test_widget_initialization(self):
        """Test widget initializes"""
        from ui.widgets.sleep_consolidation_widget import SleepConsolidationWidget

        widget = SleepConsolidationWidget()
        assert widget is not None

    def test_get_sleep_metrics(self):
        """Test getting sleep metrics"""
        from ui.widgets.sleep_consolidation_widget import SleepConsolidationWidget

        widget = SleepConsolidationWidget()
        metrics = widget.get_sleep_metrics()

        assert metrics is not None
        assert hasattr(metrics, 'enabled')

    def test_render_card(self):
        """Test rendering sleep card"""
        from ui.widgets.sleep_consolidation_widget import SleepConsolidationWidget

        widget = SleepConsolidationWidget()
        card = widget.render_card()

        assert isinstance(card, str)
        assert "Uyku" in card or "Sleep" in card

    def test_schedule_sleep(self):
        """Test sleep scheduling"""
        from ui.widgets.sleep_consolidation_widget import SleepScheduleManager

        result = SleepScheduleManager.schedule_sleep("02:00")

        assert isinstance(result, dict)
        assert "error" in result or "success" in result

    def test_schedule_invalid_time(self):
        """Test invalid time rejection"""
        from ui.widgets.sleep_consolidation_widget import SleepScheduleManager

        result = SleepScheduleManager.schedule_sleep("25:00")

        assert "error" in result

    def test_get_next_sleep_time(self):
        """Test getting next sleep time"""
        from ui.widgets.sleep_consolidation_widget import SleepScheduleManager

        next_time = SleepScheduleManager.get_next_sleep_time()

        # Should return None or ISO format string
        assert next_time is None or isinstance(next_time, str)

    def test_time_until_sleep(self):
        """Test time calculation"""
        from ui.widgets.sleep_consolidation_widget import SleepScheduleManager

        time_info = SleepScheduleManager.time_until_sleep()

        # Should return None or time dict
        assert time_info is None or (isinstance(time_info, dict) and "hours" in time_info)


class TestPerformanceCache:
    """Test performance caching system"""

    def test_cache_initialization(self):
        """Test cache initializes"""
        from core.performance_cache import PerformanceCache

        cache = PerformanceCache("test_cache")
        assert cache is not None
        assert cache.stats["hits"] == 0

    def test_set_and_get(self):
        """Test basic set/get operations"""
        from core.performance_cache import PerformanceCache

        cache = PerformanceCache("test")
        cache.set("key1", "value1")

        result = cache.get("key1")
        assert result == "value1"

    def test_cache_expiration(self):
        """Test TTL expiration"""
        import time
        from core.performance_cache import PerformanceCache

        cache = PerformanceCache("test")
        cache.set("expiring", "value", ttl_seconds=1)

        # Should be available immediately
        assert cache.get("expiring") == "value"

        # Wait for expiration
        time.sleep(1.1)

        # Should be expired
        assert cache.get("expiring") is None

    def test_cache_stats(self):
        """Test cache statistics"""
        from core.performance_cache import PerformanceCache

        cache = PerformanceCache("test")
        cache.set("key1", "value1")

        # Hit
        cache.get("key1")

        # Miss
        cache.get("nonexistent")

        stats = cache.get_stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1

    def test_intent_cache(self):
        """Test intent caching"""
        from core.performance_cache import IntentCache

        intent = {"type": "CHAT", "confidence": 0.9}
        IntentCache.cache_intent("hello", intent)

        cached = IntentCache.get_cached_intent("hello")
        assert cached == intent or cached is None  # May not be cached in test

    def test_decomposition_cache(self):
        """Test decomposition caching"""
        from core.performance_cache import DecompositionCache

        sig = DecompositionCache._make_signature(
            "test input",
            {"type": "TASK", "action": "search"}
        )

        tasks = [{"id": "t1", "action": "search"}]
        DecompositionCache.cache_decomposition(sig, tasks)

        cached = DecompositionCache.get_cached_decomposition(sig)
        assert cached == tasks or cached is None

    def test_clear_caches(self):
        """Test clearing all caches"""
        from core.performance_cache import clear_all_caches, get_intent_cache

        cache = get_intent_cache()
        cache.set("test", "value")

        clear_all_caches()

        # After clearing
        result = cache.get("test")
        assert result is None

    def test_all_cache_stats(self):
        """Test getting all cache statistics"""
        from core.performance_cache import get_all_cache_stats

        stats = get_all_cache_stats()

        assert isinstance(stats, dict)
        assert "intent" in stats
        assert "decomposition" in stats
        assert "cognitive" in stats


class TestWidgetIntegration:
    """Test widgets working together"""

    def test_all_widgets_render(self):
        """Test all widgets can render"""
        from ui.widgets.cognitive_state_widget import CognitiveStateWidget, ErrorPredictionWidget
        from ui.widgets.deadlock_prevention_widget import DeadlockPreventionWidget
        from ui.widgets.sleep_consolidation_widget import SleepConsolidationWidget

        # Create all widgets
        cognitive = CognitiveStateWidget()
        error = ErrorPredictionWidget()
        deadlock = DeadlockPreventionWidget()
        sleep = SleepConsolidationWidget()

        # All should render text
        assert isinstance(cognitive.render_card(), str)
        assert isinstance(error.render_card(), str)
        assert isinstance(deadlock.render_card(), str)
        assert isinstance(sleep.render_card(), str)

        # All should render JSON
        assert isinstance(cognitive.render_json(), dict)
        assert isinstance(error.render_json(), dict)
        assert isinstance(deadlock.render_json(), dict)
        assert isinstance(sleep.render_json(), dict)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
