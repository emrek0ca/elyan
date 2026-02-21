from core.llm_client import LLMClient


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
