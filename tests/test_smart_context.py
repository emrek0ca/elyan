"""
Tests for Smart Context Manager
"""

import pytest
from core.smart_context_manager import SmartContextManager, ConversationTurn


class TestConversationTurn:
    """Test ConversationTurn class"""

    def test_turn_creation(self):
        turn = ConversationTurn("user", "Hello world")
        
        assert turn.role == "user"
        assert turn.content == "Hello world"
        assert turn.timestamp is not None

    def test_turn_to_dict(self):
        turn = ConversationTurn("assistant", "Response")
        result = turn.to_dict()

        assert result["role"] == "assistant"
        assert result["content"] == "Response"


class TestSmartContextManager:
    """Test SmartContextManager class"""

    @pytest.fixture
    def manager(self):
        return SmartContextManager(max_turns=10)

    def test_initialization(self, manager):
        assert len(manager.turns) == 0
        assert manager.max_turns == 10

    def test_add_turn(self, manager):
        result = manager.add_turn("user", "What is Python?")
        
        assert "Turn added" in result
        assert len(manager.turns) == 1

    def test_add_multiple_turns(self, manager):
        manager.add_turn("user", "Hello")
        manager.add_turn("assistant", "Hi there!")
        manager.add_turn("user", "How are you?")

        assert len(manager.turns) == 3

    def test_get_context(self, manager):
        manager.add_turn("user", "Test message")
        context = manager.get_context()

        assert "turns" in context
        assert "entities" in context
        assert len(context["turns"]) == 1

    def test_summarize_context(self, manager):
        manager.add_turn("user", "Tell me about Python")
        summary = manager.summarize_context()

        assert isinstance(summary, str)
        assert len(summary) > 0

    def test_identify_intent_evolution(self, manager):
        manager.add_turn("user", "How do I start?")  # ask
        manager.add_turn("user", "Can you help?")     # request
        
        evolution = manager.identify_intent_evolution()
        assert "total_intent_changes" in evolution

    def test_suggest_next_action(self, manager):
        manager.add_turn("user", "What should I do?")
        suggestion = manager.suggest_next_action()

        assert isinstance(suggestion, str)
        assert len(suggestion) > 0

    def test_intent_detection(self, manager):
        manager.add_turn("user", "How does this work?")
        
        if manager.intent_history:
            assert manager.intent_history[0] is not None

    def test_sentiment_analysis(self, manager):
        manager.add_turn("user", "This is great!")
        
        if manager.turns:
            assert manager.turns[0].sentiment in ["positive", "negative", "neutral"]

    def test_get_memory_efficiency(self, manager):
        for i in range(3):
            manager.add_turn("user", f"Message {i}")

        efficiency = manager.get_memory_efficiency()
        assert "memory_usage_percent" in efficiency

    def test_reset_context(self, manager):
        manager.add_turn("user", "Test")
        manager.reset()

        assert len(manager.turns) == 0
        assert len(manager.intent_history) == 0
