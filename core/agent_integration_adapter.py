"""
Agent Integration Adapter - Bridges agent.py with new reliability systems

Provides integration points for:
- Intent routing (3-tier system)
- LLM orchestration
- Training system
- Analytics engine
- Execution tracking

Designed for zero-breaking-changes backward compatibility.
"""

import asyncio
import time
from typing import Any, Dict, Optional, Tuple
from dataclasses import dataclass

from core.intent.intent_router import route_intent, IntentRouter, initialize_router
from core.llm_orchestrator import LLMOrchestrator
from core.training_system import get_training_system
from core.analytics_engine import AnalyticsEngine
from core.reliability_integration import (
    get_execution_tracker,
    validate_before_execution,
    create_execution_context,
)
from core.json_repair import JSONRepair
from core.execution_model import ExecutionStatus
from utils.logger import get_logger

logger = get_logger("agent_integration_adapter")


@dataclass
class IntentRoutingContext:
    """Context for intent routing"""
    user_input: str
    user_id: str
    available_tools: Dict[str, Any]
    conversation_history: Optional[list] = None
    metadata: Optional[Dict[str, Any]] = None


class AgentIntegrationAdapter:
    """
    Adapter for seamless integration of new systems into agent.py

    Handles:
    - Intent routing initialization
    - LLM orchestration
    - Training system coordination
    - Analytics recording
    - Execution tracking
    """

    def __init__(self):
        self.llm_orchestrator: Optional[LLMOrchestrator] = None
        self.training_system = None  # Will be initialized in initialize()
        self.analytics: Optional[AnalyticsEngine] = None
        self.intent_router: Optional[IntentRouter] = None
        self.execution_tracker = get_execution_tracker()

        self._initialized = False

    async def initialize(self) -> bool:
        """Initialize all adapter systems"""
        try:
            # Initialize LLM orchestrator first (needed by other systems)
            self.llm_orchestrator = LLMOrchestrator()
            logger.info("LLM orchestrator initialized")

            # Initialize intent router with orchestrator
            initialize_router(self.llm_orchestrator)
            self.intent_router = IntentRouter(self.llm_orchestrator)
            logger.info("Intent router initialized")

            # Initialize training system
            self.training_system = get_training_system()
            logger.info("Training system initialized")

            # Initialize analytics
            self.analytics = AnalyticsEngine()
            logger.info("Analytics engine initialized")

            self._initialized = True
            return True

        except Exception as e:
            logger.error(f"Initialization failed: {e}")
            return False

    async def route_intent_safely(
        self,
        context: IntentRoutingContext,
        fallback_fn: Optional[callable] = None,
    ) -> Dict[str, Any]:
        """
        Route intent through 3-tier system with fallback

        Args:
            context: Intent routing context
            fallback_fn: Optional fallback function if routing fails

        Returns:
            Intent result dict with action, params, confidence
        """
        start = time.time()

        try:
            if not self.intent_router:
                logger.warning("Intent router not initialized, using fallback")
                if fallback_fn:
                    return await fallback_fn(context.user_input)
                return {
                    "action": "chat",
                    "confidence": 0.0,
                    "params": {},
                    "error": "Router not initialized",
                }

            # Route through new system
            result = self.intent_router.route(
                user_input=context.user_input,
                user_id=context.user_id,
                available_tools=context.available_tools,
                context=None,  # TODO: Convert metadata to ConversationContext
            )

            routing_time = (time.time() - start) * 1000

            # Convert result to dict
            return {
                "action": result.action,
                "params": result.params or {},
                "confidence": result.confidence,
                "source": result.source_tier,
                "requires_clarification": result.requires_clarification,
                "is_multi_task": result.is_multi_task,
                "tasks": result.tasks or [],
                "routing_time_ms": routing_time,
            }

        except Exception as e:
            logger.error(f"Intent routing error: {e}")
            if fallback_fn:
                return await fallback_fn(context.user_input)
            return {
                "action": "clarify",
                "confidence": 0.0,
                "params": {},
                "error": str(e),
            }

    async def validate_tool_execution(
        self,
        tool_name: str,
        params: Dict[str, Any],
        user_id: Optional[str] = None,
    ) -> Tuple[bool, Optional[str]]:
        """
        Validate tool execution before running

        Returns:
            (is_valid, error_message_if_any)
        """
        try:
            context = create_execution_context(user_id=user_id)
            is_valid, error = validate_before_execution(tool_name, "execute", params, context)

            if not is_valid:
                logger.warning(f"Validation failed for {tool_name}: {error.message if error else 'unknown'}")
                return False, error.message if error else "Validation failed"

            return True, None

        except Exception as e:
            logger.error(f"Validation error: {e}")
            # Don't block execution on validation errors
            return True, None

    async def record_execution_start(
        self,
        execution_id: str,
        tool_name: str,
        user_id: Optional[str] = None,
    ) -> None:
        """Record start of tool execution"""
        try:
            self.execution_tracker.start_execution(execution_id, tool_name, user_id)
        except Exception as e:
            logger.error(f"Failed to record execution start: {e}")

    async def record_execution_success(
        self,
        execution_id: str,
        tool_name: str,
        output: Any,
    ) -> None:
        """Record successful tool execution"""
        try:
            self.execution_tracker.record_tool_execution(
                tool_name=tool_name,
                action="execute",
                status=ExecutionStatus.SUCCESS,
                output=output,
            )

            # Record for training
            if self.training_system:
                await self.training_system.record_successful_execution(
                    tool_name=tool_name,
                    output=output,
                )

        except Exception as e:
            logger.error(f"Failed to record execution success: {e}")

    async def record_execution_failure(
        self,
        execution_id: str,
        tool_name: str,
        error: str,
    ) -> None:
        """Record failed tool execution"""
        try:
            self.execution_tracker.record_tool_execution(
                tool_name=tool_name,
                action="execute",
                status=ExecutionStatus.FAILED,
                output=error,
            )
        except Exception as e:
            logger.error(f"Failed to record execution failure: {e}")

    async def learn_from_success(
        self,
        user_id: str,
        user_input: str,
        intent: str,
        params: Dict[str, Any],
    ) -> None:
        """Record successful pattern for learning"""
        try:
            if self.training_system:
                await self.training_system.record_successful_intent(
                    user_id=user_id,
                    input_text=user_input,
                    intent=intent,
                    params=params,
                )
        except Exception as e:
            logger.error(f"Failed to record learning: {e}")

    async def record_analytics(
        self,
        user_id: str,
        action: str,
        duration_ms: float,
        success: bool,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record action for analytics"""
        try:
            if self.analytics:
                await self.analytics.record_action(
                    user_id=user_id,
                    action=action,
                    duration_ms=duration_ms,
                    success=success,
                    metadata=metadata or {},
                )
        except Exception as e:
            logger.error(f"Failed to record analytics: {e}")

    async def repair_json_response(
        self,
        response: str,
    ) -> Tuple[bool, Any, Optional[str]]:
        """
        Repair and parse potentially malformed JSON from LLM

        Returns:
            (success, parsed_data, repair_log)
        """
        try:
            success, result, repair_log = JSONRepair.repair_and_parse(response)
            return success, result, repair_log
        except Exception as e:
            logger.error(f"JSON repair failed: {e}")
            return False, None, str(e)

    def get_best_llm_provider(
        self,
        tier: str = "tier2",
        context: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Get best LLM provider for current context"""
        try:
            if self.llm_orchestrator:
                return self.llm_orchestrator.select_best_provider(tier=tier, context=context)
            return "default"
        except Exception as e:
            logger.error(f"Failed to select LLM provider: {e}")
            return "default"

    def get_routing_stats(self) -> Dict[str, Any]:
        """Get intent routing statistics"""
        try:
            if self.intent_router:
                return self.intent_router.get_stats()
            return {}
        except Exception as e:
            logger.error(f"Failed to get routing stats: {e}")
            return {}

    def get_execution_report(self) -> Optional[Dict[str, Any]]:
        """Get current execution report"""
        try:
            report = self.execution_tracker.get_current_report()
            if report:
                return {
                    "status": report.status.value if report.status else "unknown",
                    "tool_results": len(report.tool_results) if report.tool_results else 0,
                    "started_at": str(report.started_at) if report.started_at else "",
                    "completed_at": str(report.completed_at) if report.completed_at else "",
                }
            return None
        except Exception as e:
            logger.error(f"Failed to get execution report: {e}")
            return None


# Global adapter instance
_adapter: Optional[AgentIntegrationAdapter] = None


def get_agent_adapter() -> AgentIntegrationAdapter:
    """Get or create global adapter"""
    global _adapter
    if _adapter is None:
        _adapter = AgentIntegrationAdapter()
    return _adapter


async def initialize_agent_integration() -> bool:
    """Initialize agent integration"""
    adapter = get_agent_adapter()
    return await adapter.initialize()
