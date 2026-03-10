from core.llm_client import LLMClient
import pytest


def test_resolve_system_prompt_uses_custom_override(monkeypatch):
    values = {
        "agent.system_prompt": "Custom system prompt.",
        "agent.systemPrompt": "",
    }
    monkeypatch.setattr("core.llm_client.elyan_config.get", lambda key, default=None: values.get(key, default))
    client = LLMClient()
    assert client._resolve_system_prompt() == "Custom system prompt."


def test_resolve_system_prompt_builds_from_profile(monkeypatch):
    values = {
        "agent.system_prompt": "",
        "agent.systemPrompt": "",
        "agent.name": "ElyanX",
        "agent.personality": "technical",
        "agent.language": "en",
    }
    monkeypatch.setattr("core.llm_client.elyan_config.get", lambda key, default=None: values.get(key, default))
    client = LLMClient()
    prompt = client._resolve_system_prompt()
    assert "ElyanX" in prompt
    assert "Respond in English" in prompt
    assert "teknik" in prompt.lower() or "technical" in prompt.lower()


def test_openai_provider_marked_unavailable_without_sdk(monkeypatch):
    client = LLMClient()
    client.orchestrator.providers = {
        "openai": {"type": "openai", "apiKey": "x", "model": "gpt-4o"},
    }
    monkeypatch.setattr("core.llm_client.importlib.util.find_spec", lambda name: None if name == "openai" else object())
    assert client._is_provider_available("openai") is False


@pytest.mark.asyncio
async def test_call_provider_uses_provider_specific_config(monkeypatch):
    client = LLMClient()
    client.orchestrator.providers = {
        "groq": {"type": "groq", "apiKey": "groq-key", "model": "llama-3.3-70b-versatile"},
        "openai": {"type": "openai", "apiKey": "openai-key", "model": "gpt-4o"},
    }

    async def _fake_call_groq(prompt, system_prompt, cfg, history=None, user_id="local"):
        assert cfg.get("type") == "groq"
        assert cfg.get("apiKey") == "groq-key"
        return "ok"

    monkeypatch.setattr(client, "_call_groq", _fake_call_groq)
    out = await client._call_provider("groq", "selam")
    assert out == "ok"
