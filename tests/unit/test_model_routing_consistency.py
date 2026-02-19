"""Unit tests for model/provider routing consistency."""

from core.model_orchestrator import ModelOrchestrator
from core.neural_router import NeuralRoleMapper


def test_neural_router_respects_default_when_disabled(monkeypatch):
    config_values = {
        "router.enabled": False,
        "models.default.provider": "openai",
        "models.default.model": "gpt-4o",
        "models.roles": None,
    }
    monkeypatch.setattr(
        "core.neural_router.elyan_config.get",
        lambda key, default=None: config_values.get(key, default),
    )
    mapper = NeuralRoleMapper()
    selected = mapper.get_model_for_role("code")
    assert selected["provider"] == "openai"
    assert selected["model"] == "gpt-4o"


def test_model_orchestrator_fallback_if_router_has_no_method(monkeypatch):
    orchestrator = ModelOrchestrator()
    orchestrator.providers = {
        "openai": {"type": "openai", "model": "gpt-4o", "status": "configured"},
    }
    orchestrator.active_provider = "openai"
    monkeypatch.setattr("core.model_orchestrator.neural_router", object())
    selected = orchestrator.get_best_available("inference")
    assert selected["type"] == "openai"
    assert selected["model"] == "gpt-4o"


def test_neural_router_enabled_without_roles_uses_default(monkeypatch):
    config_values = {
        "router.enabled": True,
        "models.default.provider": "openai",
        "models.default.model": "gpt-4o",
        "models.roles": {},
    }
    monkeypatch.setattr(
        "core.neural_router.elyan_config.get",
        lambda key, default=None: config_values.get(key, default),
    )
    mapper = NeuralRoleMapper()
    selected = mapper.get_model_for_role("reasoning")
    assert selected["provider"] == "openai"
    assert selected["model"] == "gpt-4o"


def test_model_normalization_prevents_openai_llama_mismatch():
    orchestrator = ModelOrchestrator()
    normalized = orchestrator._normalize_model_for_provider("openai", "llama3")
    assert normalized == "gpt-4o"
