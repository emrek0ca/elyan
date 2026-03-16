"""
NLU Revolution System - 3-Tier Intent Recognition

Tier 1: Fast Match (< 2ms) - Exact/fuzzy hardcoded patterns
Tier 2: Semantic Classifier (< 200ms) - LLM with speed optimization
Tier 3: Deep Reasoning (< 2s) - Best-quality LLM for complex cases

Public API:
  - route_intent(user_input, user_id, context) -> IntentResult
  - train_from_correction(user_id, input, actual_intent, params)
  - get_intent_metrics() -> {latency, accuracy, confidence}
"""

from .models import (
    IntentResult,
    IntentCandidate,
    ConversationContext,
    IntentConfidence,
    TaskDefinition,
    DependencyGraph,
)
from .intent_router import IntentRouter, route_intent
from .tier1_fast_match import FastMatcher
from .tier2_semantic_classifier import SemanticClassifier
from .tier3_deep_reasoning import DeepReasoner
from .user_intent_memory import UserIntentMemory
from .multi_task_decomposer import MultiTaskDecomposer
from .intent_disambiguator import IntentDisambiguator
from .intent_metrics import IntentMetricsTracker

__all__ = [
    "IntentResult",
    "IntentCandidate",
    "ConversationContext",
    "IntentConfidence",
    "TaskDefinition",
    "DependencyGraph",
    "IntentRouter",
    "route_intent",
    "FastMatcher",
    "SemanticClassifier",
    "DeepReasoner",
    "UserIntentMemory",
    "MultiTaskDecomposer",
    "IntentDisambiguator",
    "IntentMetricsTracker",
]
