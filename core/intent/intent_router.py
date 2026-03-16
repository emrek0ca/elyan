"""
Intent Router - Main Orchestration

Coordinates all 3 tiers:
1. Check User Memory (< 1ms)
2. Tier 1 Fast Match (< 2ms)
3. Tier 2 Semantic Classifier (< 200ms)
4. Tier 3 Deep Reasoning (< 2s)
5. Feedback to Learning System

Total P99: < 2.5s
"""

import time
from typing import Optional, Dict, Any
from utils.logger import get_logger
from .models import IntentResult, ConversationContext, IntentCandidate, IntentConfidence
from .tier1_fast_match import FastMatcher
from .tier2_semantic_classifier import SemanticClassifier
from .tier3_deep_reasoning import DeepReasoner
from .user_intent_memory import UserIntentMemory
from .intent_metrics import IntentMetricsTracker

logger = get_logger("intent_router")

# Global instances
_fast_matcher: Optional[FastMatcher] = None
_semantic_classifier: Optional[SemanticClassifier] = None
_deep_reasoner: Optional[DeepReasoner] = None
_user_memory: Optional[UserIntentMemory] = None
_metrics: Optional[IntentMetricsTracker] = None


def initialize_router(llm_orchestrator=None, db_path: str = "~/.wiqo/intent_memory.db") -> None:
    """Initialize intent router components."""
    global _fast_matcher, _semantic_classifier, _deep_reasoner, _user_memory, _metrics

    _fast_matcher = FastMatcher()
    _semantic_classifier = SemanticClassifier(llm_orchestrator)
    _deep_reasoner = DeepReasoner(llm_orchestrator)
    _user_memory = UserIntentMemory(db_path=db_path)
    _metrics = IntentMetricsTracker()

    logger.info(f"Intent router initialized. Tier 1 patterns: {_fast_matcher.get_pattern_count()}")


class IntentRouter:
    """Main intent routing orchestrator."""

    def __init__(self, llm_orchestrator=None):
        self.llm = llm_orchestrator
        initialize_router(llm_orchestrator)

    def route(
        self,
        user_input: str,
        user_id: str,
        available_tools: Dict[str, Any],
        context: Optional[ConversationContext] = None,
        force_tier: Optional[str] = None
    ) -> IntentResult:
        """
        Route user input through 3-tier system.

        Args:
            user_input: User's message
            user_id: User ID for personalization
            available_tools: Available tools dict
            context: Conversation context
            force_tier: Force specific tier (for testing)

        Returns:
            IntentResult with action, confidence, params
        """
        start = time.time()

        if not context:
            context = ConversationContext(user_id=user_id)

        result = IntentResult(
            user_input=user_input,
            user_id=user_id,
            action="clarify",  # Default
            confidence=0.0,
            context=context
        )

        try:
            # 1. Check User Memory (< 1ms)
            if not force_tier or force_tier == "memory":
                memory_candidate = _user_memory.get_intent(user_input, user_id)
                if memory_candidate and memory_candidate.confidence >= IntentConfidence.HIGH.value:
                    self._populate_result(result, memory_candidate, "memory")
                    result.execution_time_ms = (time.time() - start) * 1000
                    _metrics.record_routing(result)
                    logger.info(f"Memory hit: {result.action} ({result.confidence:.2f})")
                    return result

            # 2. Tier 1 Fast Match (< 2ms)
            if not force_tier or force_tier == "tier1":
                t1_candidate = _fast_matcher.match(user_input)
                if t1_candidate and t1_candidate.confidence >= IntentConfidence.HIGH.value:
                    self._populate_result(result, t1_candidate, "tier1")
                    result.execution_time_ms = (time.time() - start) * 1000
                    _metrics.record_routing(result)
                    logger.info(f"Tier 1 match: {result.action} ({result.confidence:.2f})")
                    return result

            # 3. Tier 2 Semantic Classifier (< 200ms)
            if not force_tier or force_tier == "tier2":
                context_str = context.get_context_summary() if context else None
                t2_candidate = _semantic_classifier.classify(
                    user_input,
                    available_tools,
                    context_str
                )
                if t2_candidate and t2_candidate.confidence >= IntentConfidence.MEDIUM.value:
                    self._populate_result(result, t2_candidate, "tier2")
                    result.execution_time_ms = (time.time() - start) * 1000
                    _metrics.record_routing(result)
                    if t2_candidate.confidence >= IntentConfidence.HIGH.value:
                        logger.info(f"Tier 2 match: {result.action} ({result.confidence:.2f})")
                        return result
                    # Else: escalate to Tier 3

            # 4. Tier 3 Deep Reasoning (< 2s)
            if not force_tier or force_tier == "tier3":
                # Collect candidates from Tier 1 & 2
                candidates = []
                if t1_candidate:
                    candidates.append(t1_candidate)
                if t2_candidate:
                    candidates.append(t2_candidate)

                context_str = context.get_context_summary() if context else None
                t3_candidate = _deep_reasoner.reason(
                    user_input,
                    candidates if candidates else [IntentCandidate(
                        action="clarify",
                        confidence=0.5,
                        reasoning="No candidates from lower tiers"
                    )],
                    available_tools,
                    context_str
                )
                if t3_candidate:
                    self._populate_result(result, t3_candidate, "tier3")
                    result.execution_time_ms = (time.time() - start) * 1000
                    _metrics.record_routing(result)
                    logger.info(f"Tier 3 result: {result.action} ({result.confidence:.2f})")
                    return result

            # 5. Default fallback
            result.action = "clarify"
            result.confidence = 0.3
            result.reasoning = "Unable to determine intent - requires clarification"
            result.requires_clarification = True
            result.execution_time_ms = (time.time() - start) * 1000
            _metrics.record_routing(result)

            logger.warning(f"Routing failed for '{user_input}' - falling back to clarify")
            return result

        except Exception as e:
            logger.error(f"Routing error: {e}")
            result.action = "clarify"
            result.confidence = 0.2
            result.reasoning = f"Routing error: {str(e)}"
            result.execution_time_ms = (time.time() - start) * 1000
            return result

    def _populate_result(self, result: IntentResult, candidate: IntentCandidate, source: str) -> None:
        """Populate result from candidate."""
        result.action = candidate.action
        result.confidence = candidate.confidence
        result.params = candidate.params
        result.reasoning = candidate.reasoning
        result.source_tier = source
        result.is_multi_task = candidate.action == "multi_task"
        result.tasks = candidate.tasks
        result.requires_clarification = candidate.action == "clarify"

    def train_from_correction(
        self,
        user_id: str,
        user_input: str,
        correct_action: str,
        params: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Learn from user correction.

        Args:
            user_id: User ID
            user_input: Original input
            correct_action: What user actually wanted
            params: Correct parameters
        """
        try:
            # Add to Tier 1 if it's a simple action
            if correct_action in ["set_volume", "take_screenshot", "chat", "lock_screen"]:
                _fast_matcher.add_pattern(correct_action, user_input.lower())

            # Record in user memory
            _user_memory.learn_pattern(user_id, user_input, correct_action, params or {})

            logger.info(f"Learned: '{user_input}' → {correct_action} for user {user_id}")

        except Exception as e:
            logger.error(f"Training error: {e}")

    def get_stats(self) -> Dict[str, Any]:
        """Get routing statistics."""
        return {
            "tier1_patterns": _fast_matcher.get_pattern_count() if _fast_matcher else 0,
            "metrics": _metrics.get_summary() if _metrics else {},
            "user_memory_entries": _user_memory.get_stats() if _user_memory else {}
        }


def route_intent(
    user_input: str,
    user_id: str,
    available_tools: Dict[str, Any],
    context: Optional[ConversationContext] = None,
    llm_orchestrator=None
) -> IntentResult:
    """
    Convenience function: route single intent.

    Args:
        user_input: User's message
        user_id: User ID
        available_tools: Available tools
        context: Conversation context
        llm_orchestrator: LLM orchestrator (if not initialized)

    Returns:
        IntentResult
    """
    if not _fast_matcher:
        initialize_router(llm_orchestrator)

    router = IntentRouter(llm_orchestrator)
    return router.route(user_input, user_id, available_tools, context)
