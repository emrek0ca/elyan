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
            "enabled": True,
            "execution_mode": "local_first",
            "device_policy": "cpu",
            "backends": {},
            "environment": {
                "backend": "local_hashing",
                "device": "cpu_fallback",
                "torch_available": False,
                "sentence_transformers_available": False,
                "modules": {
                    "torch": False,
                    "sentence_transformers": False,
                    "transformers": False,
                    "peft": False,
                    "trl": False,
                    "faiss": False,
                    "lancedb": False,
                    "bitsandbytes": False,
                },
            },
            "dependencies": {
                "torch": False,
                "sentence_transformers": False,
                "transformers": False,
                "peft": False,
                "trl": False,
                "faiss": False,
                "lancedb": False,
                "bitsandbytes": False,
            },
            "capabilities": {
                "embedding": {
                    "kind": "embedding",
                    "available": True,
                    "backend": "local_hashing",
                    "device": "cpu_fallback",
                    "fallback": True,
                    "reason": "deterministic_fallback",
                    "metadata": {
                        "sentence_transformers_available": False,
                        "torch_available": False,
                        "dependency_status": {
                            "torch": False,
                            "sentence_transformers": False,
                        },
                        "fallback_mode": "deterministic",
                    },
                },
                "intent_encoder": {
                    "kind": "intent_encoder",
                    "available": False,
                    "backend": "heuristic_router",
                    "device": "cpu_fallback",
                    "fallback": True,
                    "reason": "heuristic_only",
                    "metadata": {
                        "dependency_status": {
                            "transformers": False,
                        },
                        "fallback_mode": "heuristic",
                    },
                },
                "reranker": {
                    "kind": "reranker",
                    "available": False,
                    "backend": "lexical_reranker",
                    "device": "cpu_fallback",
                    "fallback": True,
                    "reason": "lexical_only",
                    "metadata": {
                        "dependency_status": {
                            "sentence_transformers": False,
                            "transformers": False,
                        },
                        "fallback_mode": "lexical",
                    },
                },
                "reward_model": {
                    "kind": "reward_model",
                    "available": False,
                    "backend": "heuristic_scorer",
                    "device": "cpu_fallback",
                    "fallback": True,
                    "reason": "missing_transformers_or_trl",
                    "metadata": {
                        "requires": ["transformers", "trl"],
                        "dependency_status": {
                            "transformers": False,
                            "trl": False,
                        },
                        "fallback_mode": "heuristic",
                    },
                },
                "adapter_runtime": {
                    "kind": "adapter_runtime",
                    "available": False,
                    "backend": "heuristic_fallback",
                    "device": "cpu_fallback",
                    "fallback": True,
                    "reason": "missing_torch_or_peft",
                    "metadata": {
                        "requires": ["torch", "peft"],
                        "dependency_status": {
                            "torch": False,
                            "peft": False,
                        },
                        "fallback_mode": "heuristic",
                    },
                },
            },
            "updated_at": 0.0,
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
