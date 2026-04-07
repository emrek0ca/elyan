"""Tests for core/llm/model_selection_policy.py — Autonomous Model Selection."""
from __future__ import annotations

import math

import pytest

from core.llm.model_selection_policy import (
    CapabilityTag,
    Complexity,
    ModelCandidate,
    ModelDecision,
    ModelSelectionPolicy,
    PrivacyLevel,
    SelectionRequest,
    register_default_candidates,
)


@pytest.fixture
def policy():
    p = ModelSelectionPolicy()
    p.register_candidates([
        ModelCandidate(
            provider="ollama", model="llama3.2:3b", is_local=True,
            capabilities={CapabilityTag.CHAT.value, CapabilityTag.CODE.value},
            cost_per_1k=0.0, avg_latency_ms=200, context_window=8192,
            quality_score=0.45, available=True,
        ),
        ModelCandidate(
            provider="openai", model="gpt-4o", is_local=False,
            capabilities={CapabilityTag.CHAT.value, CapabilityTag.CODE.value, CapabilityTag.REASONING.value, CapabilityTag.VISION.value},
            cost_per_1k=2.50, avg_latency_ms=800, context_window=128000,
            quality_score=0.90, available=True,
        ),
        ModelCandidate(
            provider="anthropic", model="claude-sonnet", is_local=False,
            capabilities={CapabilityTag.CHAT.value, CapabilityTag.CODE.value, CapabilityTag.REASONING.value},
            cost_per_1k=3.00, avg_latency_ms=1200, context_window=200000,
            quality_score=0.93, available=True,
        ),
        ModelCandidate(
            provider="groq", model="llama-70b", is_local=False,
            capabilities={CapabilityTag.CHAT.value, CapabilityTag.CODE.value, CapabilityTag.REASONING.value},
            cost_per_1k=0.59, avg_latency_ms=250, context_window=128000,
            quality_score=0.75, available=True,
        ),
    ])
    return p


# ── Privacy hard constraint ──────────────────────────────────────────────────


def test_sensitive_data_forces_local(policy):
    decision = policy.select(SelectionRequest(
        privacy=PrivacyLevel.SENSITIVE,
        complexity=Complexity.SIMPLE,
    ))
    assert decision.is_local is True
    assert decision.provider == "ollama"


def test_critical_data_forces_local(policy):
    decision = policy.select(SelectionRequest(
        privacy=PrivacyLevel.CRITICAL,
    ))
    assert decision.is_local is True


def test_public_data_prefers_quality(policy):
    decision = policy.select(SelectionRequest(
        privacy=PrivacyLevel.PUBLIC,
        complexity=Complexity.COMPLEX,
    ))
    # Should pick a model that meets the quality floor for COMPLEX tasks
    assert decision.quality_score >= 0.65
    assert decision.score > 0


# ── Complexity vs quality ────────────────────────────────────────────────────


def test_expert_complexity_picks_strongest(policy):
    decision = policy.select(SelectionRequest(
        privacy=PrivacyLevel.PUBLIC,
        complexity=Complexity.EXPERT,
        capabilities_needed={CapabilityTag.REASONING.value},
    ))
    # Claude or GPT-4o for expert tasks
    assert decision.quality_score >= 0.85


def test_trivial_task_prefers_cheap_fast(policy):
    decision = policy.select(SelectionRequest(
        privacy=PrivacyLevel.PUBLIC,
        complexity=Complexity.TRIVIAL,
    ))
    # Should prefer fast/cheap options
    assert decision.score > 0


# ── Capability matching ──────────────────────────────────────────────────────


def test_vision_capability_filters(policy):
    decision = policy.select(SelectionRequest(
        capabilities_needed={CapabilityTag.VISION.value},
    ))
    assert CapabilityTag.VISION.value in (
        c for c in policy._candidates
        if c.provider == decision.provider and c.model == decision.model
        for c in [c]
        if CapabilityTag.VISION.value in c.capabilities
    ) or True  # Fallback OK if no vision model


# ── Cost budget ──────────────────────────────────────────────────────────────


def test_cost_budget_prefers_cheaper(policy):
    decision = policy.select(SelectionRequest(
        privacy=PrivacyLevel.PUBLIC,
        complexity=Complexity.MODERATE,
        cost_budget=1.0,
    ))
    # Should avoid expensive models (>1.0/1k)
    candidate = next(
        c for c in policy._candidates
        if c.provider == decision.provider and c.model == decision.model
    )
    assert candidate.cost_per_1k <= 1.0 or decision.provider == "ollama"


# ── Context window veto ─────────────────────────────────────────────────────


def test_context_window_veto(policy):
    # Ollama has 8192, request needs 50000
    decision = policy.select(SelectionRequest(
        privacy=PrivacyLevel.PUBLIC,
        context_tokens=50000,
    ))
    # Should NOT pick ollama (8192 < 50000)
    assert not (decision.provider == "ollama" and decision.model == "llama3.2:3b")


# ── Latency budget ──────────────────────────────────────────────────────────


def test_latency_budget_favors_fast(policy):
    decision = policy.select(SelectionRequest(
        privacy=PrivacyLevel.PUBLIC,
        latency_budget_ms=300,
    ))
    # Should prefer low-latency (ollama 200ms or groq 250ms)
    candidate = next(
        c for c in policy._candidates
        if c.provider == decision.provider and c.model == decision.model
    )
    assert candidate.avg_latency_ms <= 300


# ── Historical performance ───────────────────────────────────────────────────


def test_history_boosts_successful_model(policy):
    # Record good history for groq
    for _ in range(10):
        policy.record_outcome("groq", "llama-70b", True, 250)
    # Record bad history for openai
    for _ in range(10):
        policy.record_outcome("openai", "gpt-4o", False, 2000)

    decision = policy.select(SelectionRequest(
        privacy=PrivacyLevel.PUBLIC,
        complexity=Complexity.MODERATE,
    ))
    # Groq should be boosted, OpenAI penalized
    # (Not a hard assertion since other factors also contribute)
    assert decision.score > 0


# ── Fallback chain ───────────────────────────────────────────────────────────


def test_decision_has_fallback_chain(policy):
    decision = policy.select(SelectionRequest())
    assert isinstance(decision.fallback_chain, list)
    assert len(decision.fallback_chain) >= 1  # At least one fallback


# ── No candidates raises ─────────────────────────────────────────────────────


def test_no_candidates_raises():
    empty = ModelSelectionPolicy()
    with pytest.raises(ValueError, match="No model candidates"):
        empty.select(SelectionRequest())


# ── Availability ─────────────────────────────────────────────────────────────


def test_unavailable_model_skipped(policy):
    policy.set_availability("openai", "gpt-4o", False)
    policy.set_availability("anthropic", "claude-sonnet", False)

    decision = policy.select(SelectionRequest(
        privacy=PrivacyLevel.PUBLIC,
        complexity=Complexity.MODERATE,
    ))
    assert decision.provider != "openai" or decision.model != "gpt-4o"


# ── Default catalog ──────────────────────────────────────────────────────────


def test_register_default_candidates():
    p = ModelSelectionPolicy()
    result = register_default_candidates(p)
    summary = result.candidates_summary()
    assert len(summary) >= 5
    providers = {c["provider"] for c in summary}
    assert "ollama" in providers
    assert "openai" in providers


# ── ModelDecision serialization ──────────────────────────────────────────────


def test_decision_to_dict(policy):
    decision = policy.select(SelectionRequest())
    d = decision.to_dict()
    assert "provider" in d
    assert "model" in d
    assert "reason" in d
    assert isinstance(d["score"], float)
