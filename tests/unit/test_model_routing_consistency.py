"""Unit tests for model/provider routing consistency."""

from core.model_catalog import QWEN_LIGHT_OLLAMA_MODEL
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


def test_model_normalization_maps_qwen_alias_for_ollama():
    orchestrator = ModelOrchestrator()
    normalized = orchestrator._normalize_model_for_provider("ollama", "qwen3.5-0.8b")
    assert normalized == QWEN_LIGHT_OLLAMA_MODEL


def test_neural_router_normalizes_qwen_alias_in_role_map(monkeypatch):
    config_values = {
        "router.enabled": True,
        "models.default.provider": "ollama",
        "models.default.model": "qwen3.5-0.8b",
        "models.roles": {
            "router": {"provider": "ollama", "model": "qwen3.5-0.8b"},
        },
        "models.providers.ollama.model": "",
        "models.providers.ollama.default_model": "",
        "models.local.model": "qwen3.5-0.8b",
    }
    monkeypatch.setattr(
        "core.neural_router.elyan_config.get",
        lambda key, default=None: config_values.get(key, default),
    )
    mapper = NeuralRoleMapper()
    selected = mapper.get_model_for_role("router")
    assert selected["provider"] == "ollama"
    assert selected["model"] == QWEN_LIGHT_OLLAMA_MODEL


def test_model_orchestrator_collaboration_pool_prefers_role_matched_registry(monkeypatch):
    values = {
        "models.default.provider": "openai",
        "models.default.model": "gpt-4o",
        "models.fallback.provider": "groq",
        "models.fallback.model": "llama-3.3-70b-versatile",
        "models.local.provider": "ollama",
        "models.local.model": "llama3.1:8b",
        "models.providers.openai": {"apiKey": "x"},
        "models.providers.groq": {"apiKey": "y"},
        "models.providers.ollama": {"endpoint": "http://localhost:11434"},
        "models.registry": [
            {"id": "planner", "provider": "openai", "model": "gpt-4o", "enabled": True, "roles": ["reasoning"], "priority": 10},
            {"id": "coder", "provider": "groq", "model": "llama-3.3-70b-versatile", "enabled": True, "roles": ["code"], "priority": 20},
        ],
        "models.collaboration": {"enabled": True, "max_models": 3, "roles": ["reasoning", "code"]},
    }
    monkeypatch.setattr(
        "core.model_orchestrator.elyan_config.get",
        lambda key, default=None: values.get(key, default),
    )
    monkeypatch.setattr(
        "core.model_orchestrator.neural_router.get_model_for_role",
        lambda role: {"provider": "openai", "model": "gpt-4o"} if role == "reasoning" else {"provider": "groq", "model": "llama-3.3-70b-versatile"},
    )
    orchestrator = ModelOrchestrator()
    pool = orchestrator.get_collaboration_pool("reasoning", max_models=2)

    assert pool[0]["type"] == "openai"
    assert pool[0]["model"] == "gpt-4o"
