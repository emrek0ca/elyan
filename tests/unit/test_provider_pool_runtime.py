from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.llm.provider_pool import ProviderPool
from core.model_orchestrator import ModelOrchestrator
from core.unified_model_gateway import UnifiedModelGateway, UnifiedModelRequest


def test_provider_pool_enters_cooldown_after_repeated_failures():
    pool = ProviderPool(base_cooldown_seconds=5.0, max_cooldown_seconds=60.0, failure_threshold=2)

    assert pool.can_attempt("openai", "gpt-4o") is True
    pool.record_outcome("openai", "gpt-4o", success=False, error_text="timeout")
    assert pool.can_attempt("openai", "gpt-4o") is True
    pool.record_outcome("openai", "gpt-4o", success=False, error_text="timeout")

    state = pool.get_provider_state("openai", "gpt-4o")
    assert state["cooldown_active"] is True
    assert pool.can_attempt("openai", "gpt-4o") is False


def test_model_orchestrator_skips_provider_in_cooldown():
    orchestrator = ModelOrchestrator()
    orchestrator.providers = {
        "ollama": {"type": "ollama", "provider": "ollama", "model": "llama3.1:8b", "status": "configured"},
        "openai": {"type": "openai", "provider": "openai", "model": "gpt-4o", "status": "configured", "apiKey": "test"},
    }
    orchestrator.registry = [
        {"id": "openai:gpt-4o", "provider": "openai", "type": "openai", "model": "gpt-4o", "enabled": True, "priority": 10, "roles": []},
        {"id": "ollama:llama3.1:8b", "provider": "ollama", "type": "ollama", "model": "llama3.1:8b", "enabled": True, "priority": 20, "roles": []},
    ]
    orchestrator.provider_pool.record_outcome("openai", "gpt-4o", success=False, error_text="timeout")
    orchestrator.provider_pool.record_outcome("openai", "gpt-4o", success=False, error_text="timeout")

    selected = orchestrator.get_best_available("inference")

    assert selected["type"] == "ollama"


@pytest.mark.asyncio
async def test_unified_model_gateway_skips_candidates_in_cooldown():
    orchestrator = ModelOrchestrator()
    orchestrator.providers = {
        "ollama": {"type": "ollama", "provider": "ollama", "model": "llama3.1:8b", "status": "configured"},
        "openai": {"type": "openai", "provider": "openai", "model": "gpt-4o", "status": "configured", "apiKey": "test"},
    }
    orchestrator.registry = [
        {"id": "openai:gpt-4o", "provider": "openai", "type": "openai", "model": "gpt-4o", "enabled": True, "priority": 5, "roles": []},
        {"id": "ollama:llama3.1:8b", "provider": "ollama", "type": "ollama", "model": "llama3.1:8b", "enabled": True, "priority": 10, "roles": []},
    ]
    orchestrator.provider_pool.record_outcome("openai", "gpt-4o", success=False, error_text="timeout")
    orchestrator.provider_pool.record_outcome("openai", "gpt-4o", success=False, error_text="timeout")

    gateway = UnifiedModelGateway(
        orchestrator=orchestrator,
        specialist_registry=SimpleNamespace(
            get=lambda key: None,
            get_provider_chain=lambda key: ["openai", "ollama"],
            get_nextgen_team=lambda: {},
        ),
    )

    candidates = gateway.build_candidates(UnifiedModelRequest(role="inference", specialist_key=""))

    assert candidates
    assert candidates[0].provider == "ollama"
