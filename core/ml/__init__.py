from __future__ import annotations

import sys

from .scorers import (
    ActionRanker,
    ClarificationClassifier,
    ClaimEvidenceMatcher,
    FixSuggestionReranker,
    HallucinationRiskScorer,
    IntentScorer,
    RepoAwareEditRanker,
    SourceQualityScorer,
    TestImpactPredictor,
    Verifier,
    get_action_ranker,
    get_clarification_classifier,
    get_intent_scorer,
    get_verifier,
)
from .types import (
    DecisionRecord,
    ModelCapabilitySnapshot,
    OutcomeRecord,
    PreferencePair,
    RewardEvent,
    RuntimeContext,
    VerificationRecord,
)


class _DisabledModelRuntime:
    def snapshot(self) -> dict:
        return {
            "kind": "disabled",
            "available": False,
            "backend": "disabled",
            "device": "macos_safe",
            "fallback": True,
            "reason": "model_runtime_disabled_on_macos",
            "metadata": {},
        }


def get_model_runtime():
    if sys.platform == "darwin":
        return _DisabledModelRuntime()
    from .runtime import get_model_runtime as _get_model_runtime

    return _get_model_runtime()


def __getattr__(name: str):
    if name == "ModelRuntime":
        if sys.platform == "darwin":
            return _DisabledModelRuntime
        from .runtime import ModelRuntime as _ModelRuntime

        return _ModelRuntime
    raise AttributeError(name)

__all__ = [
    "ActionRanker",
    "ClarificationClassifier",
    "ClaimEvidenceMatcher",
    "DecisionRecord",
    "FixSuggestionReranker",
    "HallucinationRiskScorer",
    "IntentScorer",
    "ModelCapabilitySnapshot",
    "ModelRuntime",
    "OutcomeRecord",
    "PreferencePair",
    "RepoAwareEditRanker",
    "RewardEvent",
    "RuntimeContext",
    "SourceQualityScorer",
    "TestImpactPredictor",
    "Verifier",
    "VerificationRecord",
    "ModelRuntime",
    "get_action_ranker",
    "get_clarification_classifier",
    "get_intent_scorer",
    "get_model_runtime",
    "get_verifier",
]
