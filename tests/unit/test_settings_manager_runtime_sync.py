import json

from config import settings_manager as settings_module


class _FakeRuntimeConfig:
    def __init__(self, initial=None):
        self.data = dict(initial or {})

    def get(self, key, default=None):
        if key in self.data:
            return self.data[key]
        parts = str(key).split(".")
        value = self.data
        for part in parts:
            if not isinstance(value, dict) or part not in value:
                return default
            value = value[part]
        return value

    def set(self, key, value):
        parts = str(key).split(".")
        ref = self.data
        for part in parts[:-1]:
            if part not in ref or not isinstance(ref[part], dict):
                ref[part] = {}
            ref = ref[part]
        ref[parts[-1]] = value


def test_settings_panel_loads_runtime_model_selection(tmp_path, monkeypatch):
    fake_runtime = _FakeRuntimeConfig(
        {
            "models": {
                "default": {"provider": "google", "model": "gemini-2.0-flash"},
                "fallback": {"provider": "anthropic", "model": "claude-3-5-sonnet-latest"},
                "local": {"provider": "ollama", "model": "llama3.1:8b", "baseUrl": "http://127.0.0.1:11434"},
                "providers": {"google": {"apiKey": "resolved-google-key"}},
            }
        }
    )
    cfg_path = tmp_path / "settings.json"
    cfg_path.write_text(json.dumps({"llm_provider": "groq", "llm_model": "llama-3.3-70b-versatile"}), encoding="utf-8")

    monkeypatch.setattr(settings_module, "elyan_config", fake_runtime)

    panel = settings_module.SettingsPanel(config_path=str(cfg_path))

    assert panel.get("llm_provider") == "gemini"
    assert panel.get("llm_model") == "gemini-2.0-flash"
    assert panel.get("api_key") == "resolved-google-key"
    assert panel.get("ollama_host") == "http://127.0.0.1:11434"
    assert panel.get("llm_fallback_order")[:3] == ["gemini", "anthropic", "groq"]


def test_settings_panel_update_syncs_runtime_models_and_env(tmp_path, monkeypatch):
    fake_runtime = _FakeRuntimeConfig(
        {
            "models": {
                "default": {"provider": "openai", "model": "gpt-4o"},
                "fallback": {"provider": "groq", "model": "llama-3.3-70b-versatile"},
                "registry": [],
                "providers": {},
                "local": {"provider": "ollama", "model": "llama3", "baseUrl": "http://localhost:11434"},
            }
        }
    )
    cfg_path = tmp_path / "settings.json"
    cfg_path.write_text("{}", encoding="utf-8")
    env_path = tmp_path / ".env"
    env_path.write_text("", encoding="utf-8")

    monkeypatch.setattr(settings_module, "elyan_config", fake_runtime)
    monkeypatch.setattr(settings_module.platform, "system", lambda: "Linux")

    panel = settings_module.SettingsPanel(config_path=str(cfg_path))
    panel.env_path = env_path

    panel.update(
        {
            "llm_provider": "anthropic",
            "llm_model": "claude-3-5-sonnet-latest",
            "api_key": "anthropic-secret",
            "ollama_host": "http://localhost:11434",
            "llm_fallback_order": ["anthropic", "openai", "ollama"],
        }
    )

    assert fake_runtime.get("models.default.provider") == "anthropic"
    assert fake_runtime.get("models.default.model") == "claude-3-5-sonnet-latest"
    assert fake_runtime.get("models.fallback.provider") == "openai"
    assert fake_runtime.get("models.providers.anthropic.model") == "claude-3-5-sonnet-latest"
    assert fake_runtime.get("models.providers.anthropic.apiKey") == "$ANTHROPIC_API_KEY"

    registry = fake_runtime.get("models.registry")
    assert any(
        item.get("provider") == "anthropic" and item.get("model") == "claude-3-5-sonnet-latest"
        for item in registry
    )

    env_content = env_path.read_text(encoding="utf-8")
    assert "LLM_TYPE=anthropic" in env_content
    assert "MODEL_NAME=claude-3-5-sonnet-latest" in env_content
    assert "ANTHROPIC_API_KEY=anthropic-secret" in env_content


def test_settings_panel_update_syncs_openrouter_models_and_env(tmp_path, monkeypatch):
    fake_runtime = _FakeRuntimeConfig(
        {
            "models": {
                "default": {"provider": "openai", "model": "gpt-4o"},
                "fallback": {"provider": "groq", "model": "llama-3.3-70b-versatile"},
                "registry": [],
                "providers": {},
                "local": {"provider": "ollama", "model": "llama3", "baseUrl": "http://localhost:11434"},
            }
        }
    )
    cfg_path = tmp_path / "settings.json"
    cfg_path.write_text("{}", encoding="utf-8")
    env_path = tmp_path / ".env"
    env_path.write_text("", encoding="utf-8")

    monkeypatch.setattr(settings_module, "elyan_config", fake_runtime)
    monkeypatch.setattr(settings_module.platform, "system", lambda: "Linux")

    panel = settings_module.SettingsPanel(config_path=str(cfg_path))
    panel.env_path = env_path

    panel.update(
        {
            "llm_provider": "openrouter",
            "llm_model": "openai/gpt-4o-mini",
            "api_key": "openrouter-secret",
            "ollama_host": "http://localhost:11434",
            "llm_fallback_order": ["openrouter", "openai", "ollama"],
        }
    )

    assert fake_runtime.get("models.default.provider") == "openrouter"
    assert fake_runtime.get("models.default.model") == "openai/gpt-4o-mini"
    assert fake_runtime.get("models.providers.openrouter.model") == "openai/gpt-4o-mini"
    assert fake_runtime.get("models.providers.openrouter.apiKey") == "$OPENROUTER_API_KEY"

    env_content = env_path.read_text(encoding="utf-8")
    assert "LLM_TYPE=openrouter" in env_content
    assert "MODEL_NAME=openai/gpt-4o-mini" in env_content
    assert "OPENROUTER_API_KEY=openrouter-secret" in env_content
