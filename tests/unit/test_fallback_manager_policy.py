import pytest

from core.resilience.fallback_manager import FallbackManager


def test_get_best_provider_respects_allowed_providers(monkeypatch):
    fm = FallbackManager()

    monkeypatch.setattr(
        "core.resilience.fallback_manager.resilience_manager.can_call",
        lambda provider: provider in {"openai", "ollama"},
    )

    selected = fm.get_best_provider("openai", allowed_providers=["ollama"])
    assert selected == "ollama"


@pytest.mark.asyncio
async def test_execute_with_fallback_uses_allowed_provider_only(monkeypatch):
    fm = FallbackManager()

    class _LLM:
        def __init__(self):
            self.calls = []

        async def generate(self, prompt, model_config=None, **kwargs):
            _ = (prompt, kwargs)
            provider = str((model_config or {}).get("type") or "")
            self.calls.append(provider)
            if provider == "openai":
                raise RuntimeError("openai failed")
            return "ok"

    class _Agent:
        def __init__(self):
            self.llm = _LLM()

    monkeypatch.setattr(
        "core.resilience.fallback_manager.resilience_manager.can_call",
        lambda provider: provider in {"openai", "ollama"},
    )
    monkeypatch.setattr(
        "core.resilience.fallback_manager.resilience_manager.record_failure",
        lambda provider: None,
    )

    agent = _Agent()
    result = await fm.execute_with_fallback(
        agent,
        {"type": "openai", "model": "gpt-4o"},
        "test",
        allowed_providers=["ollama"],
    )
    assert result == "ok"
    assert agent.llm.calls == ["openai", "ollama"]

