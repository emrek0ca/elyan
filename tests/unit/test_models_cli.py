"""Unit tests for CLI model command consistency behavior."""

from types import SimpleNamespace

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
    monkeypatch.setattr(models, "_sync_default_to_runtime", lambda provider, model: True)
    monkeypatch.setattr(models, "_sync_default_to_gateway", lambda provider, model, role_map: False)
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
    monkeypatch.setattr(models, "_sync_default_to_runtime", lambda provider, model: True)
    monkeypatch.setattr(models, "_sync_default_to_gateway", lambda provider, model, role_map: False)
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
    monkeypatch.setattr(models, "_sync_default_to_runtime", lambda provider, model: True)
    monkeypatch.setattr(models, "_sync_default_to_gateway", lambda provider, model, role_map: False)

    models._use("ollama/qwen3.5-0.8b")

    assert captured["models.default.provider"] == "ollama"
    assert captured["models.default.model"] == QWEN_LIGHT_OLLAMA_MODEL
    assert captured["models.local.provider"] == "ollama"
    assert captured["models.local.model"] == QWEN_LIGHT_OLLAMA_MODEL
    roles = captured["models.roles"]
    assert roles["router"] == {"provider": "ollama", "model": QWEN_LIGHT_OLLAMA_MODEL}
    assert roles["inference"] == {"provider": "ollama", "model": QWEN_LIGHT_OLLAMA_MODEL}


def test_models_run_supports_switch_alias(monkeypatch):
    captured = {}

    monkeypatch.setattr(models, "_use", lambda name: captured.setdefault("name", name))

    models.run(SimpleNamespace(subcommand="switch", name="openai/gpt-4o"))

    assert captured["name"] == "openai/gpt-4o"


def test_models_use_syncs_runtime_and_gateway(monkeypatch):
    captured = {}
    config_values = {
        "models.local.provider": "ollama",
        "models.local.model": "llama3.1:8b",
        "agent.model.local_first": True,
    }

    def fake_set(key, value):
        captured[key] = value

    def fake_runtime_sync(provider, model):
        captured["runtime_sync"] = (provider, model)

    def fake_gateway_sync(provider, model, role_map):
        captured["gateway_sync"] = {
            "provider": provider,
            "model": model,
            "roles": role_map,
        }
        return True

    monkeypatch.setattr(models.elyan_config, "set", fake_set)
    monkeypatch.setattr(models.elyan_config, "get", lambda key, default=None: config_values.get(key, default))
    monkeypatch.setattr(models, "_sync_default_to_runtime", fake_runtime_sync)
    monkeypatch.setattr(models, "_sync_default_to_gateway", fake_gateway_sync)

    models._use("openai/gpt-4o")

    assert captured["runtime_sync"] == ("openai", "gpt-4o")
    assert captured["gateway_sync"]["provider"] == "openai"
    assert captured["gateway_sync"]["model"] == "gpt-4o"
    assert captured["gateway_sync"]["roles"]["router"] == {"provider": "ollama", "model": "llama3.1:8b"}
    assert captured["gateway_sync"]["roles"]["inference"] == {"provider": "ollama", "model": "llama3.1:8b"}
