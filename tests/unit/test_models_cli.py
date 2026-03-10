"""Unit tests for CLI model command consistency behavior."""

from cli.commands import models
from core.model_catalog import QWEN_LIGHT_OLLAMA_MODEL


def test_models_use_syncs_roles(monkeypatch):
    captured = {}
    config_values = {
        "models.local.provider": "ollama",
        "models.local.model": "llama3.1:8b",
        "agent.model.local_first": True,
    }

    def fake_set(key, value):
        captured[key] = value

    monkeypatch.setattr(models.elyan_config, "set", fake_set)
    monkeypatch.setattr(models.elyan_config, "get", lambda key, default=None: config_values.get(key, default))
    models._use("openai/gpt-4o")

    assert captured["models.default.provider"] == "openai"
    assert captured["models.default.model"] == "gpt-4o"
    roles = captured["models.roles"]
    assert roles["router"] == {"provider": "ollama", "model": "llama3.1:8b"}
    assert roles["inference"] == {"provider": "ollama", "model": "llama3.1:8b"}
    assert roles["reasoning"] == {"provider": "openai", "model": "gpt-4o"}
    assert roles["planning"] == {"provider": "openai", "model": "gpt-4o"}
    assert roles["creative"] == {"provider": "openai", "model": "gpt-4o"}
    assert roles["code"] == {"provider": "openai", "model": "gpt-4o"}
    assert roles["critic"] == {"provider": "openai", "model": "gpt-4o"}
    assert roles["qa"] == {"provider": "openai", "model": "gpt-4o"}
    assert roles["research_worker"] == {"provider": "openai", "model": "gpt-4o"}
    assert roles["code_worker"] == {"provider": "openai", "model": "gpt-4o"}


def test_models_use_provider_only_sets_default_model(monkeypatch):
    captured = {}

    def fake_set(key, value):
        captured[key] = value

    monkeypatch.setattr(models.elyan_config, "set", fake_set)
    models._use("openai")

    assert captured["models.default.provider"] == "openai"
    assert captured["models.default.model"] == "gpt-4o"


def test_models_use_normalizes_qwen_alias_and_syncs_local_router(monkeypatch):
    captured = {}
    config_values = {
        "models.local.provider": "ollama",
        "models.local.model": "llama3.1:8b",
        "agent.model.local_first": True,
    }

    def fake_set(key, value):
        captured[key] = value

    monkeypatch.setattr(models.elyan_config, "set", fake_set)
    monkeypatch.setattr(models.elyan_config, "get", lambda key, default=None: config_values.get(key, default))

    models._use("ollama/qwen3.5-0.8b")

    assert captured["models.default.provider"] == "ollama"
    assert captured["models.default.model"] == QWEN_LIGHT_OLLAMA_MODEL
    assert captured["models.local.provider"] == "ollama"
    assert captured["models.local.model"] == QWEN_LIGHT_OLLAMA_MODEL
    roles = captured["models.roles"]
    assert roles["router"] == {"provider": "ollama", "model": QWEN_LIGHT_OLLAMA_MODEL}
    assert roles["inference"] == {"provider": "ollama", "model": QWEN_LIGHT_OLLAMA_MODEL}
