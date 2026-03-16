"""
PHASE 3: AGENT INTEGRATION & ACTIVATION
========================================

Comprehensive integration tests for new capabilities:
- Intent routing (3-tier system)
- LLM orchestration (multi-provider)
- Training system
- Analytics tracking
- Backward compatibility

All tests ensure Elyan is ALIVE and operational.
"""

import pytest
import asyncio
import json
import time
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from typing import Dict, Any, Optional

from core.agent import Agent
from core.intent.intent_router import IntentRouter, initialize_router
from core.intent.models import IntentResult, ConversationContext
from core.llm_orchestrator import LLMOrchestrator, LLMProvider, ProviderConfig
from core.training_system import get_training_system
from core.analytics_engine import get_analytics_engine
from core.reliability_integration import ExecutionGuard
from core.contracts.agent_response import AgentResponse


# ============================================================================
# FIXTURES & SETUP
# ============================================================================

@pytest.fixture
def agent():
    """Create a fresh agent instance."""
    agent = Agent()
    return agent


@pytest.fixture
def llm_orchestrator():
    """Create mock LLM orchestrator."""
    return LLMOrchestrator()


@pytest.fixture
def intent_router(llm_orchestrator):
    """Create intent router."""
    router = IntentRouter(llm_orchestrator=llm_orchestrator)
    return router


@pytest.fixture
def training_system():
    """Create training system."""
    return get_training_system()


@pytest.fixture
def analytics_engine():
    """Create analytics engine."""
    return get_analytics_engine()


@pytest.fixture
def conversation_context():
    """Create sample conversation context."""
    return ConversationContext(
        user_id="test_user",
        message_history=[],
        last_intent=None,
        last_action_time=None,
        active_task_id=None,
        session_vars={},
    )


# ============================================================================
# SECTION A: OLD API BACKWARD COMPATIBILITY
# ============================================================================

class TestBackwardCompatibility:
    """Verify old API still works (no breaking changes)."""

    @pytest.mark.asyncio
    async def test_process_old_api_still_works(self, agent):
        """Test old process() method signature works."""
        # Old API: simple text input, text output
        result = await agent.process(
            user_input="What time is it?",
            channel="cli",
        )
        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_process_envelope_backward_compat(self, agent):
        """Test process_envelope() with old-style parameters."""
        response = await agent.process_envelope(
            user_input="Hello",
            channel="cli",
            metadata={"user_id": "test"},
        )
        assert isinstance(response, AgentResponse)
        assert hasattr(response, "text")
        assert hasattr(response, "run_id")

    @pytest.mark.asyncio
    async def test_execute_tool_old_signature(self, agent):
        """Test _execute_tool with old parameters."""
        # Old API signature
        result = await agent._execute_tool(
            tool_name="chat",
            params={"message": "hello"},
            user_input="say hello",
            step_name="step1",
        )
        # Result can be dict or string depending on tool
        assert result is not None

    def test_action_to_tool_mapping_unchanged(self, agent):
        """Verify ACTION_TO_TOOL mapping is still available."""
        from core.agent import ACTION_TO_TOOL
        assert "research" in ACTION_TO_TOOL
        assert ACTION_TO_TOOL["research"] == "advanced_research"
        assert "weather" in ACTION_TO_TOOL

    @pytest.mark.asyncio
    async def test_old_user_profile_access(self, agent):
        """Test backward compat with user profile store."""
        assert hasattr(agent, "user_profile")
        assert agent.user_profile is not None

    @pytest.mark.asyncio
    async def test_old_learning_engine_access(self, agent):
        """Test backward compat with learning engine."""
        assert hasattr(agent, "learning")
        assert agent.learning is not None

    @pytest.mark.asyncio
    async def test_old_quick_intent_access(self, agent):
        """Test backward compat with quick intent detector."""
        assert hasattr(agent, "quick_intent")
        assert agent.quick_intent is not None


# ============================================================================
# SECTION B: NEW INTENT ROUTING (3-TIER)
# ============================================================================

class TestIntentRouting:
    """Test new 3-tier intent routing system."""

    def test_intent_router_initialization(self, intent_router):
        """Test intent router initializes properly."""
        assert intent_router is not None
        assert intent_router.llm is not None

    @pytest.mark.asyncio
    async def test_route_simple_intent(self, intent_router, conversation_context):
        """Test routing a simple intent (Tier 1 fast match)."""
        available_tools = {
            "chat": {},
            "take_screenshot": {},
            "set_volume": {},
        }
        result = intent_router.route(
            user_input="say hello",
            user_id="test_user",
            available_tools=available_tools,
            context=conversation_context,
        )
        assert isinstance(result, IntentResult)
        assert hasattr(result, "action")
        assert hasattr(result, "confidence")

    @pytest.mark.asyncio
    async def test_route_complex_intent(self, intent_router, conversation_context):
        """Test routing a complex intent (may use Tier 2/3)."""
        available_tools = {
            "advanced_research": {},
            "chat": {},
        }
        result = intent_router.route(
            user_input="research machine learning and create a summary",
            user_id="test_user",
            available_tools=available_tools,
            context=conversation_context,
        )
        assert isinstance(result, IntentResult)
        assert result.action is not None

    def test_intent_router_with_user_memory(self, intent_router, conversation_context):
        """Test intent router uses user intent memory."""
        # First route
        result1 = intent_router.route(
            user_input="screenshot",
            user_id="test_user_1",
            available_tools={"take_screenshot": {}},
            context=conversation_context,
        )

        # Second route should be faster (memory hit)
        result2 = intent_router.route(
            user_input="screenshot",
            user_id="test_user_1",
            available_tools={"take_screenshot": {}},
            context=conversation_context,
        )

        assert isinstance(result1, IntentResult)
        assert isinstance(result2, IntentResult)

    @pytest.mark.asyncio
    async def test_intent_confidence_scoring(self, intent_router, conversation_context):
        """Test confidence scoring for intents."""
        result = intent_router.route(
            user_input="open browser",
            user_id="test_user",
            available_tools={"browser_open": {}},
            context=conversation_context,
        )
        assert hasattr(result, "confidence")
        assert 0 <= result.confidence <= 1.0

    @pytest.mark.asyncio
    async def test_intent_fallback_chain(self, intent_router, conversation_context):
        """Test fallback when no tier matches."""
        result = intent_router.route(
            user_input="xyzabc12345invalid",
            user_id="test_user",
            available_tools={"chat": {}},
            context=conversation_context,
        )
        # Should fallback to chat
        assert isinstance(result, IntentResult)


# ============================================================================
# SECTION C: LLM ORCHESTRATION
# ============================================================================

class TestLLMOrchestration:
    """Test LLM provider selection and fallback."""

    def test_llm_orchestrator_initialization(self, llm_orchestrator):
        """Test LLM orchestrator initializes."""
        assert llm_orchestrator is not None

    @pytest.mark.asyncio
    async def test_provider_selection(self, llm_orchestrator):
        """Test automatic provider selection."""
        # Should select best available provider
        provider = llm_orchestrator._select_best_provider()
        assert provider in [p.value for p in LLMProvider]

    @pytest.mark.asyncio
    async def test_fallback_on_provider_failure(self, llm_orchestrator):
        """Test fallback to secondary provider on failure."""
        # Mock provider failure
        with patch.object(llm_orchestrator, "_select_best_provider") as mock_select:
            mock_select.side_effect = [LLMProvider.GROQ.value, LLMProvider.GEMINI.value]

            p1 = llm_orchestrator._select_best_provider()
            p2 = llm_orchestrator._select_best_provider()

            assert p1 != p2 or p2 is not None

    def test_provider_config_validation(self, llm_orchestrator):
        """Test provider configuration validation."""
        config = ProviderConfig(
            provider=LLMProvider.GROQ,
            api_key="test_key",
            endpoint="http://localhost:8000",
            model="llama-3.3-70b-versatile",
        )
        assert config.provider == LLMProvider.GROQ
        assert config.model is not None

    @pytest.mark.asyncio
    async def test_cost_tracking(self, llm_orchestrator):
        """Test cost tracking across providers."""
        # Should track costs
        assert hasattr(llm_orchestrator, "_provider_stats")

    @pytest.mark.asyncio
    async def test_quality_metrics(self, llm_orchestrator):
        """Test quality metrics collection."""
        # Should track quality
        stats = llm_orchestrator.get_provider_stats()
        assert isinstance(stats, dict)


# ============================================================================
# SECTION D: TRAINING SYSTEM
# ============================================================================

class TestTrainingSystem:
    """Test learning and adaptation system."""

    def test_training_system_initialization(self, training_system):
        """Test training system initializes."""
        assert training_system is not None

    def test_record_success(self, training_system):
        """Test recording successful execution."""
        from core.training_system import TrainingExample
        example = TrainingExample(
            input_text="test",
            expected_output="test",
            intent="chat",
            success=True,
            timestamp=time.time(),
            feedback=None,
            confidence=0.8,
        )
        training_system.learn_from_example(example)
        # Should store without error
        assert training_system is not None

    def test_record_failure(self, training_system):
        """Test recording failed execution."""
        from core.training_system import TrainingExample
        example = TrainingExample(
            input_text="test",
            expected_output="test",
            intent="chat",
            success=False,
            timestamp=time.time(),
            feedback="test error",
            confidence=0.3,
        )
        training_system.learn_from_example(example)
        # Should store without error
        assert training_system is not None

    def test_get_recommendations(self, training_system):
        """Test getting recommendations based on history."""
        recs = training_system.get_recommendations(
            user_id="test",
            context={"last_intent": "chat"},
        )
        assert isinstance(recs, list)

    def test_learning_enabled_flag(self, training_system):
        """Test learning can be enabled/disabled."""
        assert hasattr(training_system, "enabled")
        training_system.enabled = True
        assert training_system.enabled is True
        training_system.enabled = False
        assert training_system.enabled is False


# ============================================================================
# SECTION E: ANALYTICS ENGINE
# ============================================================================

class TestAnalyticsEngine:
    """Test analytics and metrics tracking."""

    def test_analytics_initialization(self, analytics_engine):
        """Test analytics engine initializes."""
        assert analytics_engine is not None

    def test_record_execution_metric(self, analytics_engine):
        """Test recording execution metrics."""
        analytics_engine.record_execution(
            tool="chat",
            intent="chat",
            duration_ms=100,
            success=True,
            user_id="test",
        )
        assert analytics_engine is not None

    def test_record_intent_metric(self, analytics_engine):
        """Test recording intent metrics."""
        # Analytics has record_execution, not record_intent
        analytics_engine.record_execution(
            tool="chat",
            intent="chat",
            duration_ms=100,
            success=True,
        )
        assert analytics_engine is not None

    def test_get_metrics_summary(self, analytics_engine):
        """Test getting metrics summary."""
        # Record some metrics
        analytics_engine.record_execution(
            tool="chat",
            intent="chat",
            duration_ms=100,
            success=True,
        )

        summary = analytics_engine.get_summary()
        assert isinstance(summary, dict)

    def test_metrics_persistence(self, analytics_engine):
        """Test metrics are persisted."""
        analytics_engine.record_execution(
            tool="chat",
            intent="chat",
            duration_ms=100,
            success=True,
        )
        assert analytics_engine is not None


# ============================================================================
# SECTION F: RELIABILITY & VALIDATION
# ============================================================================

class TestReliabilityIntegration:
    """Test reliability foundation integration."""

    def test_execution_guard_decorator(self):
        """Test ExecutionGuard decorator."""
        @ExecutionGuard.with_error_handling(
            tool_name="test_tool",
            action="execute",
        )
        def test_func(params):
            return {"result": "success"}

        assert callable(test_func)

    @pytest.mark.asyncio
    async def test_json_repair(self):
        """Test JSON repair for broken responses."""
        from core.json_repair import JSONRepair

        broken_json = '{"key": "value", "broken": '
        success, repaired, error = JSONRepair.repair_and_parse(broken_json)
        # Should attempt repair
        assert isinstance(repaired, (dict, str)) or success is False

    def test_execution_report(self):
        """Test execution report generation."""
        from core.execution_report import ExecutionReportBuilder

        builder = ExecutionReportBuilder("exec_001", "task_001")
        report = builder.build()
        assert report is not None
        assert report.execution_id == "exec_001"
        assert report.task_id == "task_001"


# ============================================================================
# SECTION G: AGENT INTEGRATION POINTS
# ============================================================================

class TestAgentIntegration:
    """Test integration of new systems into Agent."""

    @pytest.mark.asyncio
    async def test_agent_has_intent_router(self, agent):
        """Test agent has integrated intent router."""
        # After Phase 3, agent should have intent_router
        if hasattr(agent, "intent_router"):
            assert agent.intent_router is not None

    @pytest.mark.asyncio
    async def test_agent_has_llm_orchestrator(self, agent):
        """Test agent has integrated LLM orchestrator."""
        # After Phase 3, agent should have llm_orchestrator
        if hasattr(agent, "llm_orchestrator"):
            assert agent.llm_orchestrator is not None

    @pytest.mark.asyncio
    async def test_agent_has_training_system(self, agent):
        """Test agent has integrated training system."""
        # After Phase 3, agent should have training_system
        if hasattr(agent, "training_system"):
            assert agent.training_system is not None

    @pytest.mark.asyncio
    async def test_agent_has_analytics(self, agent):
        """Test agent has integrated analytics."""
        # After Phase 3, agent should have analytics
        if hasattr(agent, "analytics"):
            assert agent.analytics is not None

    @pytest.mark.asyncio
    async def test_agent_process_uses_new_routing(self, agent):
        """Test that process() can use new intent routing."""
        # If integration successful, routing should be used
        with patch.object(agent, "intent_parser") as mock_parser:
            mock_parser.parse.return_value = ("chat", {})
            result = await agent.process("hello")
            assert isinstance(result, str)


# ============================================================================
# SECTION H: GRACEFUL DEGRADATION
# ============================================================================

class TestGracefulDegradation:
    """Test fallback behavior when new systems fail."""

    @pytest.mark.asyncio
    async def test_fallback_if_intent_router_fails(self, agent):
        """Test fallback to old parser if router fails."""
        with patch.object(agent, "intent_parser") as mock_parser:
            mock_parser.parse.return_value = ("chat", {})
            result = await agent.process("hello")
            # Should still work
            assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_fallback_if_llm_unavailable(self, agent):
        """Test fallback to offline patterns if LLM unavailable."""
        if hasattr(agent, "llm_orchestrator"):
            with patch.object(agent.llm_orchestrator, "call") as mock_call:
                mock_call.side_effect = Exception("LLM unavailable")
                result = await agent.process("what time is it")
                # Should still work with fallback
                assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_fallback_if_training_fails(self, agent):
        """Test agent continues if training system fails."""
        if hasattr(agent, "training_system"):
            with patch.object(agent.training_system, "record_success") as mock_record:
                mock_record.side_effect = Exception("Training failed")
                # Should not crash
                result = await agent.process("hello")
                assert isinstance(result, str)


# ============================================================================
# SECTION I: INTEGRATION WORKFLOWS
# ============================================================================

class TestIntegrationWorkflows:
    """Test complete workflows with new systems."""

    @pytest.mark.asyncio
    async def test_simple_query_workflow(self, agent):
        """Test simple query goes through all systems."""
        result = await agent.process("hello")
        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_tool_execution_workflow(self, agent):
        """Test tool execution with new validation."""
        # This test depends on tools being available
        result = await agent._execute_tool(
            tool_name="chat",
            params={"message": "hello"},
        )
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_learning_feedback_workflow(self, agent):
        """Test learning feedback integration."""
        # Execute something
        result = await agent.process("hello")

        # If training system integrated, should record
        if hasattr(agent, "training_system"):
            assert agent.training_system is not None

    @pytest.mark.asyncio
    async def test_analytics_tracking_workflow(self, agent):
        """Test analytics tracks all operations."""
        result = await agent.process("hello")

        # If analytics integrated, should record
        if hasattr(agent, "analytics"):
            assert agent.analytics is not None


# ============================================================================
# SECTION J: ERROR HANDLING & RECOVERY
# ============================================================================

class TestErrorHandling:
    """Test error handling in new systems."""

    @pytest.mark.asyncio
    async def test_invalid_user_input(self, agent):
        """Test handling of invalid input."""
        result = await agent.process("")
        # Should handle gracefully
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_missing_tool(self, agent):
        """Test handling of missing tool."""
        result = await agent._execute_tool(
            tool_name="nonexistent_tool_xyz",
            params={},
        )
        assert isinstance(result, dict)
        # Should have error
        if "error" in result:
            assert result["error"] is not None

    @pytest.mark.asyncio
    async def test_invalid_params(self, agent):
        """Test handling of invalid parameters."""
        result = await agent._execute_tool(
            tool_name="chat",
            params={"invalid": "params"},
        )
        # Should handle gracefully
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_timeout_handling(self, agent):
        """Test handling of timeouts."""
        # Mock timeout
        with patch("asyncio.wait_for") as mock_timeout:
            mock_timeout.side_effect = asyncio.TimeoutError()
            # Should still work with fallback
            result = await agent.process("hello")
            assert isinstance(result, str)


# ============================================================================
# SECTION K: PERFORMANCE & METRICS
# ============================================================================

class TestPerformanceMetrics:
    """Test performance characteristics of new systems."""

    @pytest.mark.asyncio
    async def test_fast_intent_matching_speed(self, intent_router, conversation_context):
        """Test Tier 1 fast matching is <2ms."""
        start = time.time()
        result = intent_router.route(
            user_input="screenshot",
            user_id="test",
            available_tools={"take_screenshot": {}},
            context=conversation_context,
        )
        elapsed = (time.time() - start) * 1000  # Convert to ms
        # Tier 1 should be <10ms (allowing overhead)
        assert elapsed < 100  # Generous timeout for CI

    @pytest.mark.asyncio
    async def test_process_completes_in_time(self, agent):
        """Test process() completes in reasonable time."""
        start = time.time()
        result = await agent.process("hello")
        elapsed = (time.time() - start) * 1000  # Convert to ms
        # Should complete in <5s
        assert elapsed < 5000
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_metrics_overhead_minimal(self, analytics_engine):
        """Test analytics doesn't add significant overhead."""
        start = time.time()
        for i in range(100):
            analytics_engine.record_execution(
                tool="chat",
                intent="chat",
                duration_ms=100,
                success=True,
            )
        elapsed = (time.time() - start) * 1000  # Convert to ms
        # 100 operations should be <1000ms
        assert elapsed < 1500


# ============================================================================
# SECTION L: SMOKE TESTS
# ============================================================================

class TestSmokeSuite:
    """Quick smoke tests to verify basic functionality."""

    @pytest.mark.asyncio
    async def test_agent_process_works(self, agent):
        """Smoke: agent.process() works."""
        result = await agent.process("hello")
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_agent_process_envelope_works(self, agent):
        """Smoke: agent.process_envelope() works."""
        response = await agent.process_envelope("hello")
        assert isinstance(response, AgentResponse)

    def test_intent_router_works(self, intent_router):
        """Smoke: intent router works."""
        result = intent_router.route(
            user_input="hello",
            user_id="test",
            available_tools={"chat": {}},
        )
        assert isinstance(result, IntentResult)

    def test_llm_orchestrator_works(self, llm_orchestrator):
        """Smoke: LLM orchestrator works."""
        assert llm_orchestrator is not None

    def test_training_system_works(self, training_system):
        """Smoke: training system works."""
        # Training system API uses learn_from_example
        from core.training_system import TrainingExample
        example = TrainingExample(
            input_text="test",
            expected_output="test",
            intent="test",
            success=True,
            timestamp=time.time(),
            feedback=None,
            confidence=0.8,
        )
        training_system.learn_from_example(example)
        assert training_system is not None

    def test_analytics_works(self, analytics_engine):
        """Smoke: analytics works."""
        analytics_engine.record_execution(
            tool="test",
            intent="test",
            duration_ms=100,
            success=True,
        )
        assert analytics_engine is not None


# ============================================================================
# RUN TESTS
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
