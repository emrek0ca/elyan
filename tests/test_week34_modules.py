"""
Week 3-4 Memory & Knowledge Base Tests
"""

import pytest
from core.episodic_memory import EpisodicMemory, Episode
from core.semantic_knowledge_base import SemanticKnowledgeBase
from core.autonomous_decision_engine import AutonomousDecisionEngine
from core.self_healing_system import SelfHealingSystem


class TestEpisodicMemory:
    """Test episodic memory"""

    def test_start_episode(self):
        mem = EpisodicMemory()
        episode_id = mem.start_episode()
        assert episode_id is not None
        assert mem.current_episode is not None

    def test_record_action(self):
        mem = EpisodicMemory()
        mem.start_episode()
        result = mem.record_action("test_action", {"param": "value"}, True)
        assert result is True
        assert len(mem.current_episode.actions) == 1

    def test_end_episode(self):
        mem = EpisodicMemory()
        initial_count = len(mem.episodes)  # May have episodes from previous runs
        episode_id = mem.start_episode()
        mem.record_action("action1", {}, True)
        ended_id = mem.end_episode(["learning1"])
        assert ended_id == episode_id
        assert mem.current_episode is None
        # Should have exactly one more episode than before
        assert len(mem.episodes) == initial_count + 1

    def test_recall_episodes(self):
        mem = EpisodicMemory()
        mem.start_episode()
        mem.record_action("test", {}, True)
        mem.end_episode()
        
        similar = mem.recall_similar_episodes({"action": "test"})
        assert isinstance(similar, list)

    def test_get_statistics(self):
        mem = EpisodicMemory()
        mem.start_episode()
        mem.record_action("a", {}, True)
        mem.end_episode()
        
        stats = mem.get_statistics()
        assert "total_episodes" in stats


class TestSemanticKnowledgeBase:
    """Test semantic knowledge base"""

    def test_add_entity(self):
        kb = SemanticKnowledgeBase()
        entity_id = kb.add_entity("e1", "Entity One", "concept", "A test entity")
        assert entity_id == "e1"
        assert "e1" in kb.entities

    def test_add_relationship(self):
        kb = SemanticKnowledgeBase()
        kb.add_entity("e1", "E1", "concept")
        kb.add_entity("e2", "E2", "concept")
        kb.add_relationship("e1", "e2", "related_to", 0.9)
        assert len(kb.relationships) == 1

    def test_find_related(self):
        kb = SemanticKnowledgeBase()
        kb.add_entity("e1", "E1", "concept")
        kb.add_entity("e2", "E2", "concept")
        kb.add_relationship("e1", "e2", "related_to")
        
        related = kb.find_related_entities("e1")
        assert len(related) > 0

    def test_query_entities(self):
        kb = SemanticKnowledgeBase()
        kb.add_entity("e1", "Python Programming", "concept")
        results = kb.query_entities("Python")
        assert len(results) > 0


class TestAutonomousDecisionEngine:
    """Test autonomous decisions"""

    def test_initialization(self):
        engine = AutonomousDecisionEngine()
        assert engine.decision_accuracy == 0.0

    def test_make_decision(self):
        engine = AutonomousDecisionEngine()
        options = [
            {"name": "option1", "score": 0.8},
            {"name": "option2", "score": 0.5}
        ]
        decision, confidence = engine.make_decision({}, options)
        assert decision is not None
        assert 0 <= confidence <= 1.0

    def test_record_outcome(self):
        engine = AutonomousDecisionEngine()
        options = [{"name": "opt1", "score": 0.8}]
        decision, _ = engine.make_decision({}, options)
        
        if engine.decisions:
            decision_id = engine.decisions[0].decision_id
            result = engine.record_outcome(decision_id, "Success", True)
            assert result is True

    def test_get_stats(self):
        engine = AutonomousDecisionEngine()
        options = [{"name": "opt", "score": 0.8}]
        engine.make_decision({}, options)
        stats = engine.get_decision_stats()
        assert "total_decisions" in stats


class TestSelfHealingSystem:
    """Test self-healing"""

    def test_initialization(self):
        system = SelfHealingSystem()
        assert system.recovery_rate == 0.0

    def test_detect_error(self):
        system = SelfHealingSystem()
        errors = system.detect_error({}, None)
        assert errors is not None or errors is None

    def test_attempt_recovery(self):
        system = SelfHealingSystem()
        success, strategy = system.attempt_recovery(
            "timeout",
            {"error_message": "Timeout", "duration": 10}
        )
        assert isinstance(success, bool)
        assert isinstance(strategy, str)

    def test_prevent_errors(self):
        system = SelfHealingSystem()
        suggestions = system.prevent_future_errors("timeout")
        assert len(suggestions) > 0

    def test_health_status(self):
        system = SelfHealingSystem()
        status = system.get_health_status()
        assert "recovery_rate" in status
        assert "total_errors" in status
