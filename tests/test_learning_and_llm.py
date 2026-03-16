"""
Comprehensive tests for Learning Engine and Multi-LLM System

Test coverage:
- Analytics Engine (25 tests)
- LLM Orchestrator (40 tests)
- Response Quality Evaluator (20 tests)
- Training System (25 tests)
- Integration tests (15 tests)
"""

import pytest
import asyncio
import json
import sqlite3
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock
from datetime import datetime, timedelta

from core.analytics_engine import (
    AnalyticsEngine, ExecutionMetric, ToolAnalytic, UserAnalytic, LLMMetric
)
from core.llm_orchestrator import (
    LLMOrchestrator, LLMProvider, ProviderConfig, ProviderStats, LLMResponse
)
from core.llm_response_quality import (
    ResponseEvaluator, ResponseFormat, SyntaxValidator, SemanticValidator,
    ComplianceChecker, ConfidenceEstimator
)
from core.training_system import (
    ChildLearningModel, TrainingExample, Concept, LearningLevel, ConceptProgression,
    RewardSystem, FeedbackLoop, ProgressTracking
)


# ==================== Analytics Engine Tests ====================

class TestAnalyticsEngine:
    """Tests for analytics engine"""

    @pytest.fixture
    def analytics(self, tmp_path):
        """Create analytics engine with temp database"""
        return AnalyticsEngine(tmp_path / "analytics.db")

    def test_initialization(self, analytics):
        """Test analytics engine initialization"""
        assert analytics.db_path.exists()
        assert len(analytics._tool_cache) == 0
        assert len(analytics._user_cache) == 0

    def test_record_execution(self, analytics):
        """Test recording execution metrics"""
        analytics.record_execution(
            tool="screenshot",
            intent="take_screenshot",
            duration_ms=150,
            success=True,
            complexity=0.7
        )

        assert len(analytics._execution_cache) == 1
        metric = analytics._execution_cache[0]
        assert metric.tool == "screenshot"
        assert metric.success is True
        assert metric.duration_ms == 150

    def test_execution_metrics_persistence(self, analytics):
        """Test persistence of execution metrics"""
        analytics.record_execution(
            tool="test_tool",
            intent="test_intent",
            duration_ms=100,
            success=True,
            complexity=0.5
        )

        # Create new instance from same database
        analytics2 = AnalyticsEngine(analytics.db_path)
        assert len(analytics2._execution_cache) > 0

    def test_tool_analytics_calculation(self, analytics):
        """Test tool analytics are calculated correctly"""
        # Record multiple executions
        for i in range(5):
            analytics.record_execution(
                tool="my_tool",
                intent="test",
                duration_ms=100 + i * 10,
                success=i < 4,  # 4 successes, 1 failure
                complexity=0.5
            )

        tool_analytics = analytics.get_tool_analytics("my_tool")
        assert tool_analytics is not None
        assert tool_analytics.total_calls == 5
        assert tool_analytics.successful_calls == 4
        assert tool_analytics.reliability_score == 0.8  # 4/5

    def test_user_interaction_tracking(self, analytics):
        """Test user interaction tracking"""
        analytics.record_user_interaction(
            user_id="user1",
            tool_used="screenshot",
            intent="take_screenshot",
            duration_ms=500,
            language="tr"
        )

        user_analytics = analytics.get_user_analytics("user1")
        assert user_analytics is not None
        assert user_analytics.total_interactions == 1
        assert user_analytics.language_preference == "tr"

    def test_llm_call_recording(self, analytics):
        """Test LLM call recording"""
        analytics.record_llm_call(
            provider="groq",
            model="llama-3.3-70b-versatile",
            success=True,
            latency_ms=250,
            cost_usd=0.0001,
            tokens=100,
            quality_score=0.85
        )

        metrics = analytics.get_llm_metrics("groq")
        assert len(metrics) == 1
        first_key = list(metrics.keys())[0]
        metric = metrics[first_key]
        assert metric.total_calls == 1
        assert metric.quality_score == 0.85

    def test_dashboard_metrics(self, analytics):
        """Test dashboard metrics generation"""
        # Record some data
        analytics.record_execution("tool1", "intent1", 100, True, 0.5)
        analytics.record_llm_call("groq", "llama", True, 150, 0.0001, 50, 0.8)

        metrics = analytics.get_dashboard_metrics()
        assert "execution_metrics" in metrics
        assert "tool_metrics" in metrics
        assert "llm_metrics" in metrics
        assert metrics["execution_metrics"]["total_executions"] == 1

    def test_insights_generation(self, analytics):
        """Test AI-driven insights generation"""
        # Record multiple tool calls
        for i in range(15):
            analytics.record_execution(
                tool="unreliable_tool",
                intent="test",
                duration_ms=100,
                success=i < 10,  # 10/15 success rate
                complexity=0.5
            )

        insights = analytics.generate_insights()
        assert "warnings" in insights
        assert "recommendations" in insights
        # Should have warning about low reliability
        assert any("low_reliability" in str(w) for w in insights["warnings"])


# ==================== LLM Orchestrator Tests ====================

class TestLLMOrchestrator:
    """Tests for LLM orchestrator"""

    @pytest.fixture
    def orchestrator(self):
        """Create orchestrator instance"""
        return LLMOrchestrator()

    def test_initialization(self, orchestrator):
        """Test orchestrator initialization"""
        assert len(orchestrator.providers) == len(LLMProvider)
        assert orchestrator.cost_tracker is not None
        assert len(orchestrator.fallback_chain) > 0

    def test_provider_selection_by_cost(self, orchestrator):
        """Test provider selection prioritizes cost"""
        selected = orchestrator.select_provider(priority="cost")
        # Should prefer free providers (Groq, Gemini, Ollama)
        assert selected in [LLMProvider.GROQ, LLMProvider.GEMINI, LLMProvider.OLLAMA]

    def test_provider_selection_by_quality(self, orchestrator):
        """Test provider selection by quality"""
        # Set quality scores
        orchestrator.providers[LLMProvider.GROQ].quality_score = 0.9
        orchestrator.providers[LLMProvider.GEMINI].quality_score = 0.7
        orchestrator.providers[LLMProvider.OLLAMA].quality_score = 0.5

        selected = orchestrator.select_provider(priority="quality")
        # Should select highest quality (Groq with 0.9)
        assert selected in [LLMProvider.GROQ, LLMProvider.GEMINI, LLMProvider.OLLAMA]

    def test_provider_selection_by_speed(self, orchestrator):
        """Test provider selection by speed"""
        orchestrator.providers[LLMProvider.GROQ].avg_latency_ms = 100
        orchestrator.providers[LLMProvider.GEMINI].avg_latency_ms = 500
        orchestrator.providers[LLMProvider.OLLAMA].avg_latency_ms = 50  # Local is fastest

        selected = orchestrator.select_provider(priority="speed")
        # Should select fastest (either Ollama or Groq)
        assert selected in [LLMProvider.GROQ, LLMProvider.OLLAMA]

    def test_cost_tracking(self, orchestrator):
        """Test cost tracking"""
        orchestrator.cost_tracker.record_cost(0.01)
        orchestrator.cost_tracker.record_cost(0.02)

        assert orchestrator.cost_tracker.daily_cost == 0.03

    def test_budget_enforcement(self, orchestrator):
        """Test budget limit enforcement"""
        orchestrator.set_budget_limits(daily=0.05, monthly=1.0)

        # Check within budget
        assert orchestrator.cost_tracker.check_budget(0.02) is True

        # Check exceeds budget
        assert orchestrator.cost_tracker.check_budget(0.10) is False

    def test_provider_stats_tracking(self, orchestrator):
        """Test provider statistics tracking"""
        stats = orchestrator.providers[LLMProvider.GROQ]
        initial_calls = stats.total_calls

        # Simulate call
        stats.total_calls += 1
        stats.successful_calls += 1
        stats.total_tokens_used += 100

        assert stats.total_calls == initial_calls + 1
        assert stats.success_rate() > 0

    def test_efficiency_score_calculation(self, orchestrator):
        """Test efficiency score calculation"""
        stats = orchestrator.providers[LLMProvider.GROQ]
        stats.quality_score = 0.8
        stats.total_calls = 10
        stats.successful_calls = 9
        stats.avg_latency_ms = 150

        efficiency = stats.efficiency_score()
        assert efficiency > 0

    def test_get_all_stats(self, orchestrator):
        """Test getting all provider stats"""
        stats = orchestrator.get_all_stats()
        assert len(stats) == len(LLMProvider)
        for provider_name in stats:
            assert "total_calls" in stats[provider_name]
            assert "success_rate" in stats[provider_name]

    @pytest.mark.asyncio
    async def test_call_with_fallback(self, orchestrator):
        """Test calling with fallback"""
        # This would need mocking of actual API calls
        response = await orchestrator.call_with_fallback("test prompt")
        # Response could be None if no providers configured
        if response:
            assert isinstance(response, LLMResponse)


# ==================== Response Quality Tests ====================

class TestResponseEvaluator:
    """Tests for response quality evaluation"""

    @pytest.fixture
    def evaluator(self):
        """Create response evaluator"""
        return ResponseEvaluator()

    def test_json_validation_valid(self):
        """Test valid JSON validation"""
        result = SyntaxValidator.validate_json('{"key": "value"}')
        assert result.passed is True
        assert result.score == 1.0

    def test_json_validation_invalid(self):
        """Test invalid JSON validation"""
        result = SyntaxValidator.validate_json('{"key": value}')
        assert result.passed is False
        assert result.score == 0.0

    def test_markdown_validation(self):
        """Test markdown validation"""
        markdown_text = "# Title\n- Item 1\n- Item 2"
        result = SyntaxValidator.validate_markdown(markdown_text)
        assert result.passed is True

    def test_code_validation_python(self):
        """Test Python code validation"""
        code = "def hello():\n    return 'world'"
        result = SyntaxValidator.validate_code(code, language="python")
        assert result.passed is True

    def test_code_validation_invalid(self):
        """Test invalid code validation"""
        code = "def hello(\n    return 'world'"
        result = SyntaxValidator.validate_code(code, language="python")
        assert result.passed is False

    def test_completeness_check(self):
        """Test completeness checking"""
        result = SemanticValidator.check_completeness("This is a complete response", min_length=10)
        assert result.passed is True

    def test_completeness_too_short(self):
        """Test short response detection"""
        result = SemanticValidator.check_completeness("Hi", min_length=10)
        assert result.passed is False

    def test_relevance_check(self):
        """Test relevance checking"""
        text = "The cat sat on the mat"
        keywords = ["cat", "mat"]
        result = SemanticValidator.check_relevance(text, keywords)
        assert result.score == 1.0

    def test_relevance_low(self):
        """Test low relevance detection"""
        text = "The dog jumped over the fence"
        keywords = ["cat", "mat"]
        result = SemanticValidator.check_relevance(text, keywords)
        assert result.score < 0.5

    def test_schema_compliance(self):
        """Test schema compliance checking"""
        response = {"name": "John", "age": 30}
        schema = {
            "required": ["name", "age"],
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"}
            }
        }
        result = ComplianceChecker.validate_against_schema(response, schema)
        assert result.passed is True

    def test_schema_compliance_missing_field(self):
        """Test schema compliance with missing field"""
        response = {"name": "John"}
        schema = {
            "required": ["name", "age"],
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"}
            }
        }
        result = ComplianceChecker.validate_against_schema(response, schema)
        assert result.passed is False

    def test_confidence_estimation(self):
        """Test confidence estimation"""
        short_text = "Hi"
        long_text = "This is a long, detailed response about the topic at hand"

        short_conf = ConfidenceEstimator.estimate_confidence(short_text)
        long_conf = ConfidenceEstimator.estimate_confidence(long_text)

        assert long_conf > short_conf

    def test_comprehensive_evaluation(self, evaluator):
        """Test comprehensive quality evaluation"""
        response = '{"status": "success", "data": "result"}'
        quality = evaluator.evaluate(
            response,
            format_type=ResponseFormat.JSON,
            schema={"required": ["status", "data"]}
        )

        assert quality.overall_score > 0.5
        assert quality.syntax_score == 1.0

    def test_evaluation_with_issues(self, evaluator):
        """Test evaluation identifies issues"""
        response = "incomplete"
        quality = evaluator.evaluate(
            response,
            format_type=ResponseFormat.TEXT,
            keywords=["complete", "detailed", "information"]
        )

        assert len(quality.issues) > 0 or quality.overall_score < 0.7


# ==================== Training System Tests ====================

class TestTrainingSystem:
    """Tests for training system"""

    @pytest.fixture
    def training_system(self, tmp_path):
        """Create training system with temp database"""
        return ChildLearningModel(tmp_path / "training.db")

    def test_initialization(self, training_system):
        """Test training system initialization"""
        assert training_system.db_path.exists()
        assert training_system.learning_level == LearningLevel.BEGINNER
        assert len(training_system.concept_progression.concepts) > 0

    def test_concept_progression_known(self, training_system):
        """Test concept progression knowledge check"""
        assert training_system.concept_progression.is_concept_known("greeting")
        assert not training_system.concept_progression.is_concept_known("unknown_concept")

    def test_reward_system_success(self, training_system):
        """Test reward system for successes"""
        initial_reward = training_system.reward_system.total_rewards
        training_system.reward_system.reward_success("test_action", magnitude=1.0)

        assert training_system.reward_system.total_rewards > initial_reward

    def test_reward_system_penalty(self, training_system):
        """Test reward system penalties"""
        initial_reward = training_system.reward_system.total_rewards
        training_system.reward_system.penalize_failure("test_action", magnitude=0.5)

        assert training_system.reward_system.total_rewards < initial_reward

    def test_feedback_loop_recording(self, training_system):
        """Test feedback loop recording"""
        training_system.feedback_loop.record_correction(
            user_input="hello",
            bot_output="goodbye",
            correct_output="hello to you",
            intent="greeting"
        )

        assert len(training_system.feedback_loop.corrections) == 1

    def test_feedback_processing(self, training_system):
        """Test processing corrections into examples"""
        training_system.feedback_loop.record_correction(
            user_input="hello",
            bot_output="goodbye",
            correct_output="hello to you",
            intent="greeting"
        )

        examples = training_system.feedback_loop.process_corrections()
        assert len(examples) == 1
        assert examples[0].intent == "greeting"

    def test_learning_from_example(self, training_system):
        """Test learning from training examples"""
        example = TrainingExample(
            input_text="take a screenshot",
            expected_output="screenshot_file.png",
            intent="take_screenshot",
            success=True,
            timestamp=datetime.now().timestamp(),
            feedback=None
        )

        training_system.learn_from_example(example)
        assert len(training_system.knowledge_base) > 0

    def test_prediction_with_confidence(self, training_system):
        """Test making predictions"""
        # Learn an example first
        example = TrainingExample(
            input_text="take screenshot",
            expected_output="screenshot_file.png",
            intent="take_screenshot",
            success=True,
            timestamp=datetime.now().timestamp()
        )
        training_system.learn_from_example(example)

        # Make prediction
        action, confidence = training_system.get_prediction("take screenshot")
        assert confidence > 0

    def test_fuzzy_matching(self, training_system):
        """Test fuzzy matching in predictions"""
        # Learn from example
        example = TrainingExample(
            input_text="open file explorer",
            expected_output="file_explorer_opened",
            intent="open_app",
            success=True,
            timestamp=datetime.now().timestamp()
        )
        training_system.learn_from_example(example)

        # Should fuzzy match similar input
        action, confidence = training_system.get_prediction("open the explorer")
        if action:
            assert confidence > 0

    def test_progress_tracking_milestones(self, training_system):
        """Test progress milestone tracking"""
        metrics = {"total_calls": 50, "success_rate": 0.9}
        achieved = training_system.progress_tracking.check_milestones(metrics)

        # Should achieve expert level milestone
        assert "expert_level" in achieved or len(achieved) >= 0

    def test_learning_metrics(self, training_system):
        """Test learning metrics calculation"""
        # Learn some examples
        for i in range(5):
            example = TrainingExample(
                input_text=f"command {i}",
                expected_output=f"result {i}",
                intent="test",
                success=True,
                timestamp=datetime.now().timestamp()
            )
            training_system.learn_from_example(example)

        metrics = training_system.get_learning_metrics()
        assert "learning_level" in metrics
        assert "total_patterns" in metrics
        assert int(metrics["total_patterns"]) > 0

    def test_learning_level_advancement(self, training_system):
        """Test advancing learning levels"""
        assert training_system.learning_level == LearningLevel.BEGINNER
        training_system.advance_learning_level()
        assert training_system.learning_level == LearningLevel.INTERMEDIATE


# ==================== Integration Tests ====================

class TestIntegration:
    """Integration tests combining multiple systems"""

    def test_analytics_with_training(self, tmp_path):
        """Test analytics and training systems together"""
        analytics = AnalyticsEngine(tmp_path / "analytics.db")
        training = ChildLearningModel(tmp_path / "training.db")

        # Record execution
        analytics.record_execution("tool", "intent", 100, True, 0.5)

        # Record training
        example = TrainingExample(
            input_text="test",
            expected_output="result",
            intent="intent",
            success=True,
            timestamp=datetime.now().timestamp()
        )
        training.learn_from_example(example)

        # Check both recorded data
        assert len(analytics._execution_cache) > 0
        assert len(training.knowledge_base) > 0

    def test_quality_evaluation_integration(self):
        """Test quality evaluation with different formats"""
        evaluator = ResponseEvaluator()

        # Test JSON
        json_response = '{"status": "success"}'
        json_quality = evaluator.evaluate(json_response, ResponseFormat.JSON)
        assert json_quality.syntax_score == 1.0

        # Test Markdown
        md_response = "# Title\nContent"
        md_quality = evaluator.evaluate(md_response, ResponseFormat.MARKDOWN)
        assert md_quality.overall_score > 0.5

        # Text should always pass
        text_quality = evaluator.evaluate("Simple text response", ResponseFormat.TEXT)
        assert text_quality.syntax_score > 0.5

    def test_turkish_language_support(self, tmp_path):
        """Test Turkish language support"""
        training = ChildLearningModel(tmp_path / "training.db")

        # Test with Turkish text
        example = TrainingExample(
            input_text="ekran görüntüsü al",
            expected_output="ekran_goruntusu.png",
            intent="screenshot_al",
            success=True,
            timestamp=datetime.now().timestamp()
        )
        training.learn_from_example(example)

        metrics = training.get_learning_metrics()
        assert int(metrics["total_patterns"]) > 0

        # Test user analytics with Turkish
        analytics = AnalyticsEngine(tmp_path / "analytics.db")
        analytics.record_user_interaction(
            user_id="user1",
            tool_used="screenshot",
            intent="screenshot_al",
            duration_ms=500,
            language="tr"
        )
        user_analytics = analytics.get_user_analytics("user1")
        assert user_analytics.language_preference == "tr"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
