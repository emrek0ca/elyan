"""Unit tests for CLI model command consistency behavior."""

from cli.commands import models


def test_models_use_syncs_roles(monkeypatch):
    captured = {}

    def fake_set(key, value):
        captured[key] = value

    monkeypatch.setattr(models.elyan_config, "set", fake_set)
    models._use("openai/gpt-4o")

    assert captured["models.default.provider"] == "openai"
    assert captured["models.default.model"] == "gpt-4o"
    roles = captured["models.roles"]
    assert roles["reasoning"] == {"provider": "openai", "model": "gpt-4o"}
    assert roles["inference"] == {"provider": "openai", "model": "gpt-4o"}
    assert roles["creative"] == {"provider": "openai", "model": "gpt-4o"}
    assert roles["code"] == {"provider": "openai", "model": "gpt-4o"}


def test_models_use_provider_only_sets_default_model(monkeypatch):
    captured = {}

    def fake_set(key, value):
        captured[key] = value

    monkeypatch.setattr(models.elyan_config, "set", fake_set)
    models._use("openai")

    assert captured["models.default.provider"] == "openai"
    assert captured["models.default.model"] == "gpt-4o"
