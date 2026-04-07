"""
core/llm/model_selection_policy.py
───────────────────────────────────────────────────────────────────────────────
Autonomous Model Selection Policy — decides local vs cloud per LLM call.

Decision function:
  Given a request R with properties (privacy, complexity, latency_budget, cost_budget,
  capability_required), the policy computes a weighted score for each candidate model
  and returns the optimal choice.

Scoring model:
  score(model, request) = w_p · privacy(m, r)
                        + w_c · complexity(m, r)
                        + w_l · latency(m, r)
                        + w_$ · cost(m, r)
                        + w_h · history(m, r)

  Where:
    w_p = 100  (privacy is hard constraint, not soft)
    w_c = 3    (capability match)
    w_l = 2    (latency preference)
    w_$ = 2    (cost preference)
    w_h = 1    (historical success boost)

  privacy() returns -inf if model violates privacy constraint → hard veto.

Design principles:
  - Hard constraints (privacy) are non-negotiable
  - Soft preferences (cost, latency) are weighted
  - Historical performance biases toward proven models
  - Fallback chain guarantees a result even when all scores are low
  - No external dependencies — pure computation
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class PrivacyLevel(str, Enum):
    """Data sensitivity classification."""
    PUBLIC = "public"         # No restrictions
    INTERNAL = "internal"     # Prefer local, cloud acceptable with redaction
    SENSITIVE = "sensitive"   # Local only — no cloud transmission
    CRITICAL = "critical"     # Local only, encrypted at rest


class Complexity(str, Enum):
    """Task complexity estimation."""
    TRIVIAL = "trivial"       # Greeting, status check
    SIMPLE = "simple"         # Single-step, well-defined
    MODERATE = "moderate"     # Multi-step, some reasoning
    COMPLEX = "complex"       # Deep reasoning, code generation
    EXPERT = "expert"         # Research, multi-domain synthesis


class CapabilityTag(str, Enum):
    """Required model capabilities."""
    CHAT = "chat"
    CODE = "code"
    REASONING = "reasoning"
    VISION = "vision"
    EMBEDDING = "embedding"
    TOOL_USE = "tool_use"
    LONG_CONTEXT = "long_context"


@dataclass(slots=True)
class ModelCandidate:
    """A model available for selection.

    Attributes:
        provider:       Provider key (ollama, openai, anthropic, groq, google).
        model:          Model identifier (e.g. "llama3.2:3b", "gpt-4o", "claude-3.5-sonnet").
        is_local:       True if runs on local hardware (Ollama).
        capabilities:   Set of CapabilityTag values this model supports.
        cost_per_1k:    Cost per 1K tokens in currency units (0 for local).
        avg_latency_ms: Average response latency in milliseconds.
        context_window:  Maximum context window in tokens.
        quality_score:   Subjective quality [0.0, 1.0] — higher is better.
        available:       Whether the model is currently reachable.
    """
    provider: str
    model: str
    is_local: bool = False
    capabilities: set[str] = field(default_factory=set)
    cost_per_1k: float = 0.0
    avg_latency_ms: float = 500.0
    context_window: int = 8192
    quality_score: float = 0.5
    available: bool = True


@dataclass(slots=True)
class SelectionRequest:
    """Input to the model selection policy.

    Attributes:
        privacy:              Data sensitivity level.
        complexity:           Task complexity.
        capabilities_needed:  Required model capabilities.
        latency_budget_ms:    Maximum acceptable latency (None = no constraint).
        cost_budget:          Maximum cost per 1K tokens (None = no constraint).
        context_tokens:       Estimated input+output token count.
        agent_id:             Requesting agent (for history lookup).
        task_type:            Task category (for history lookup).
    """
    privacy: PrivacyLevel = PrivacyLevel.INTERNAL
    complexity: Complexity = Complexity.MODERATE
    capabilities_needed: set[str] = field(default_factory=lambda: {CapabilityTag.CHAT.value})
    latency_budget_ms: float | None = None
    cost_budget: float | None = None
    context_tokens: int = 2000
    agent_id: str = ""
    task_type: str = ""


@dataclass(slots=True)
class ModelDecision:
    """Output of the model selection policy."""
    provider: str
    model: str
    is_local: bool
    score: float
    reason: str
    quality_score: float = 0.0
    fallback_chain: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "is_local": self.is_local,
            "score": round(self.score, 3),
            "quality_score": round(self.quality_score, 3),
            "reason": self.reason,
            "fallback_chain": self.fallback_chain,
        }


# ── Scoring weights ─────────────────────────────────────────────────────────

_W_PRIVACY = 100.0    # Hard constraint weight (effectively veto)
_W_CAPABILITY = 3.0   # Capability match
_W_LATENCY = 2.0      # Latency preference
_W_COST = 2.0         # Cost preference
_W_HISTORY = 1.0      # Historical success
_W_QUALITY = 2.5      # Model quality score

# Complexity → minimum quality threshold
_COMPLEXITY_QUALITY_FLOOR: dict[Complexity, float] = {
    Complexity.TRIVIAL: 0.1,
    Complexity.SIMPLE: 0.2,
    Complexity.MODERATE: 0.4,
    Complexity.COMPLEX: 0.65,
    Complexity.EXPERT: 0.85,
}


class ModelSelectionPolicy:
    """Stateless model selection engine.

    Usage:
        policy = ModelSelectionPolicy()
        policy.register_candidate(ModelCandidate(...))
        decision = policy.select(SelectionRequest(...))
    """

    def __init__(self) -> None:
        self._candidates: list[ModelCandidate] = []
        self._history: dict[str, _HistoryEntry] = {}  # key = "provider:model"

    # ── Candidate management ─────────────────────────────────────────────

    def register_candidate(self, candidate: ModelCandidate) -> None:
        """Add or update a model candidate."""
        # Replace if same provider+model exists
        self._candidates = [
            c for c in self._candidates
            if not (c.provider == candidate.provider and c.model == candidate.model)
        ]
        self._candidates.append(candidate)

    def register_candidates(self, candidates: list[ModelCandidate]) -> None:
        for c in candidates:
            self.register_candidate(c)

    def set_availability(self, provider: str, model: str, available: bool) -> None:
        for c in self._candidates:
            if c.provider == provider and c.model == model:
                c.available = available
                break

    # ── History ──────────────────────────────────────────────────────────

    def record_outcome(self, provider: str, model: str, success: bool, latency_ms: float) -> None:
        """Record a model call outcome for future selection bias."""
        key = f"{provider}:{model}"
        entry = self._history.get(key)
        if entry is None:
            entry = _HistoryEntry()
            self._history[key] = entry
        entry.total += 1
        if success:
            entry.successes += 1
        # Exponential moving average for latency
        alpha = 0.3
        entry.avg_latency_ms = alpha * latency_ms + (1 - alpha) * entry.avg_latency_ms

    # ── Selection ────────────────────────────────────────────────────────

    def select(self, request: SelectionRequest) -> ModelDecision:
        """Select the optimal model for the given request.

        Returns a ModelDecision with the best model and fallback chain.
        Raises ValueError if no candidates are registered.
        """
        if not self._candidates:
            raise ValueError("No model candidates registered")

        scored: list[tuple[float, ModelCandidate, str]] = []

        for candidate in self._candidates:
            if not candidate.available:
                continue
            score, reason = self._score(candidate, request)
            if math.isfinite(score):
                scored.append((score, candidate, reason))

        # Sort descending by score
        scored.sort(key=lambda x: x[0], reverse=True)

        if not scored:
            # All candidates vetoed — return first available as emergency fallback
            for c in self._candidates:
                if c.available:
                    return ModelDecision(
                        provider=c.provider,
                        model=c.model,
                        is_local=c.is_local,
                        score=0.0,
                        reason="emergency_fallback: all candidates scored -inf",
                        quality_score=c.quality_score,
                        fallback_chain=[],
                    )
            raise ValueError("No available model candidates")

        best_score, best_candidate, best_reason = scored[0]
        fallback_chain = [
            f"{c.provider}/{c.model}" for _, c, _ in scored[1:4]
        ]

        return ModelDecision(
            provider=best_candidate.provider,
            model=best_candidate.model,
            is_local=best_candidate.is_local,
            score=best_score,
            reason=best_reason,
            quality_score=best_candidate.quality_score,
            fallback_chain=fallback_chain,
        )

    def _score(self, candidate: ModelCandidate, request: SelectionRequest) -> tuple[float, str]:
        """Compute composite score for a candidate given a request.

        Returns (score, reason_string).
        """
        reasons: list[str] = []
        score = 0.0

        # ── Privacy (hard constraint) ────────────────────────────────────
        if request.privacy in (PrivacyLevel.SENSITIVE, PrivacyLevel.CRITICAL):
            if not candidate.is_local:
                return -math.inf, "privacy_veto: sensitive data requires local model"
            score += _W_PRIVACY
            reasons.append("privacy:local_ok")
        elif request.privacy == PrivacyLevel.INTERNAL:
            if candidate.is_local:
                score += _W_PRIVACY * 0.3  # Prefer local but don't veto cloud
                reasons.append("privacy:local_preferred")
            else:
                reasons.append("privacy:cloud_acceptable")
        else:
            reasons.append("privacy:public")

        # ── Capability match ─────────────────────────────────────────────
        needed = request.capabilities_needed
        has = candidate.capabilities
        if needed:
            match_ratio = len(needed & has) / len(needed) if needed else 1.0
            if match_ratio < 0.5:
                return -math.inf, f"capability_veto: {needed - has} missing"
            score += _W_CAPABILITY * match_ratio
            reasons.append(f"capability:{match_ratio:.0%}")

        # ── Quality floor ────────────────────────────────────────────────
        min_quality = _COMPLEXITY_QUALITY_FLOOR.get(request.complexity, 0.3)
        if candidate.quality_score < min_quality:
            # Soft penalty, not veto
            deficit = min_quality - candidate.quality_score
            score -= _W_QUALITY * deficit * 5
            reasons.append(f"quality:below_floor({candidate.quality_score:.2f}<{min_quality:.2f})")
        else:
            score += _W_QUALITY * candidate.quality_score
            reasons.append(f"quality:{candidate.quality_score:.2f}")

        # ── Latency ──────────────────────────────────────────────────────
        if request.latency_budget_ms is not None:
            if candidate.avg_latency_ms <= request.latency_budget_ms:
                ratio = 1.0 - (candidate.avg_latency_ms / request.latency_budget_ms)
                score += _W_LATENCY * ratio
                reasons.append(f"latency:ok({candidate.avg_latency_ms:.0f}ms)")
            else:
                overshoot = candidate.avg_latency_ms / request.latency_budget_ms - 1.0
                score -= _W_LATENCY * overshoot
                reasons.append(f"latency:slow({candidate.avg_latency_ms:.0f}ms)")
        else:
            # No budget → small bonus for fast models
            if candidate.avg_latency_ms < 1000:
                score += _W_LATENCY * 0.3
            reasons.append(f"latency:{candidate.avg_latency_ms:.0f}ms")

        # ── Cost ─────────────────────────────────────────────────────────
        if candidate.cost_per_1k == 0:
            score += _W_COST  # Free (local) gets full cost bonus
            reasons.append("cost:free")
        elif request.cost_budget is not None:
            if candidate.cost_per_1k <= request.cost_budget:
                ratio = 1.0 - (candidate.cost_per_1k / request.cost_budget)
                score += _W_COST * ratio
                reasons.append(f"cost:within_budget")
            else:
                score -= _W_COST
                reasons.append(f"cost:over_budget")
        else:
            # Prefer cheaper
            score += _W_COST * max(0, 1.0 - candidate.cost_per_1k / 10.0)
            reasons.append(f"cost:{candidate.cost_per_1k:.3f}/1k")

        # ── Context window ───────────────────────────────────────────────
        if request.context_tokens > candidate.context_window:
            return -math.inf, f"context_veto: need {request.context_tokens} > {candidate.context_window}"

        # ── Historical performance ───────────────────────────────────────
        key = f"{candidate.provider}:{candidate.model}"
        hist = self._history.get(key)
        if hist is not None and hist.total >= 5:
            success_rate = hist.successes / hist.total
            score += _W_HISTORY * (success_rate - 0.5) * 2  # Normalize to [-1, +1]
            reasons.append(f"history:{success_rate:.0%}({hist.total})")

        return score, " | ".join(reasons)

    # ── Inspection ───────────────────────────────────────────────────────

    def candidates_summary(self) -> list[dict[str, Any]]:
        return [
            {
                "provider": c.provider,
                "model": c.model,
                "is_local": c.is_local,
                "available": c.available,
                "quality": c.quality_score,
                "cost": c.cost_per_1k,
                "latency_ms": c.avg_latency_ms,
                "capabilities": sorted(c.capabilities),
            }
            for c in self._candidates
        ]


@dataclass
class _HistoryEntry:
    total: int = 0
    successes: int = 0
    avg_latency_ms: float = 500.0


# ── Singleton ───────────────────────────────────────────────────────────────

_policy_instance: ModelSelectionPolicy | None = None


def get_model_selection_policy() -> ModelSelectionPolicy:
    """Get or create the singleton ModelSelectionPolicy."""
    global _policy_instance
    if _policy_instance is None:
        _policy_instance = ModelSelectionPolicy()
    return _policy_instance


# ── Default model catalog ───────────────────────────────────────────────────


def register_default_candidates(policy: ModelSelectionPolicy | None = None) -> ModelSelectionPolicy:
    """Register the standard Elyan model catalog.

    This provides sensible defaults for the scoring engine.
    Actual availability is updated at runtime by health checks.
    """
    p = policy or get_model_selection_policy()

    cap = CapabilityTag
    p.register_candidates([
        # ── Local (Ollama) ───────────────────────────────────────────────
        ModelCandidate(
            provider="ollama", model="llama3.2:3b", is_local=True,
            capabilities={cap.CHAT.value, cap.CODE.value, cap.REASONING.value},
            cost_per_1k=0.0, avg_latency_ms=200, context_window=8192,
            quality_score=0.45, available=False,  # discovered at runtime
        ),
        ModelCandidate(
            provider="ollama", model="qwen2.5:7b", is_local=True,
            capabilities={cap.CHAT.value, cap.CODE.value, cap.REASONING.value, cap.TOOL_USE.value},
            cost_per_1k=0.0, avg_latency_ms=400, context_window=32768,
            quality_score=0.55, available=False,
        ),
        ModelCandidate(
            provider="ollama", model="qwen2.5-coder:7b", is_local=True,
            capabilities={cap.CHAT.value, cap.CODE.value, cap.TOOL_USE.value},
            cost_per_1k=0.0, avg_latency_ms=400, context_window=32768,
            quality_score=0.60, available=False,
        ),
        ModelCandidate(
            provider="ollama", model="deepseek-r1:8b", is_local=True,
            capabilities={cap.CHAT.value, cap.REASONING.value, cap.CODE.value},
            cost_per_1k=0.0, avg_latency_ms=600, context_window=32768,
            quality_score=0.58, available=False,
        ),
        # ── Cloud: OpenAI ────────────────────────────────────────────────
        ModelCandidate(
            provider="openai", model="gpt-4o", is_local=False,
            capabilities={cap.CHAT.value, cap.CODE.value, cap.REASONING.value, cap.VISION.value, cap.TOOL_USE.value, cap.LONG_CONTEXT.value},
            cost_per_1k=2.50, avg_latency_ms=800, context_window=128000,
            quality_score=0.90, available=False,
        ),
        ModelCandidate(
            provider="openai", model="gpt-4o-mini", is_local=False,
            capabilities={cap.CHAT.value, cap.CODE.value, cap.TOOL_USE.value, cap.VISION.value},
            cost_per_1k=0.15, avg_latency_ms=400, context_window=128000,
            quality_score=0.72, available=False,
        ),
        # ── Cloud: Anthropic ─────────────────────────────────────────────
        ModelCandidate(
            provider="anthropic", model="claude-sonnet-4-20250514", is_local=False,
            capabilities={cap.CHAT.value, cap.CODE.value, cap.REASONING.value, cap.TOOL_USE.value, cap.LONG_CONTEXT.value},
            cost_per_1k=3.00, avg_latency_ms=1200, context_window=200000,
            quality_score=0.93, available=False,
        ),
        # ── Cloud: Google ────────────────────────────────────────────────
        ModelCandidate(
            provider="google", model="gemini-2.5-flash", is_local=False,
            capabilities={cap.CHAT.value, cap.CODE.value, cap.REASONING.value, cap.VISION.value, cap.LONG_CONTEXT.value},
            cost_per_1k=0.15, avg_latency_ms=600, context_window=1000000,
            quality_score=0.78, available=False,
        ),
        # ── Cloud: Groq ─────────────────────────────────────────────────
        ModelCandidate(
            provider="groq", model="llama-3.3-70b-versatile", is_local=False,
            capabilities={cap.CHAT.value, cap.CODE.value, cap.REASONING.value, cap.TOOL_USE.value},
            cost_per_1k=0.59, avg_latency_ms=250, context_window=128000,
            quality_score=0.75, available=False,
        ),
    ])
    return p


__all__ = [
    "CapabilityTag",
    "Complexity",
    "ModelCandidate",
    "ModelDecision",
    "ModelSelectionPolicy",
    "PrivacyLevel",
    "SelectionRequest",
    "get_model_selection_policy",
    "register_default_candidates",
]
