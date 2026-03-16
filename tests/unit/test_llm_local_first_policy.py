import pytest

from core.llm_client import LLMClient


@pytest.mark.asyncio
async def test_generate_blocks_cloud_when_local_first_and_no_cloud_fallback(monkeypatch):
    client = LLMClient()

    class _Orchestrator:
        def get_best_available(self, role, exclude=None):
            _ = role
            if exclude:
                return {"type": "none"}
            return {"type": "openai", "model": "gpt-4o"}

    client.orchestrator = _Orchestrator()

    def _cfg_get(key, default=None):
        data = {
            "agent.model.local_first": True,
            "security.kvkk.strict": True,
            "security.kvkk.redactCloudPrompts": True,
            "security.kvkk.allowCloudFallback": False,
        }
        return data.get(key, default)

    monkeypatch.setattr("core.llm_client.elyan_config.get", _cfg_get)
    monkeypatch.setattr("core.llm.token_budget.token_budget.is_within_budget", lambda user_id: True)

    out = await client.generate("Merhaba", user_id="u1")
    assert "fallback kapalı" in out.lower()


@pytest.mark.asyncio
async def test_generate_accepts_legacy_model_keyword(monkeypatch):
    client = LLMClient()

    monkeypatch.setattr("core.llm.token_budget.token_budget.is_within_budget", lambda user_id: True)

    class _Orchestrator:
        def get_best_available(self, role, exclude=None):
            _ = (role, exclude)
            return {"type": "openai", "model": "gpt-4o-mini"}

        def find_provider_for_model(self, model):
            _ = model
            return "openai"

        def _normalize_provider(self, provider):
            return str(provider or "").strip().lower()

        def get_provider_config(self, provider, role="inference", model=None):
            _ = role
            return {"type": provider, "provider": provider, "model": model or "gpt-4o", "apiKey": "test-key"}

        def _normalize_model_for_provider(self, provider, model):
            _ = provider
            return model

        def record_metric(self, provider, success, latency):
            _ = (provider, success, latency)

    client.orchestrator = _Orchestrator()

    async def _fake_openai(prompt, system_prompt, cfg, history=None, user_id="local"):
        _ = (prompt, system_prompt, history, user_id)
        return f"model={cfg.get('model')}"

    monkeypatch.setattr(client, "_call_openai", _fake_openai)
    monkeypatch.setattr(client, "_provider_runtime_ready", lambda provider, cfg=None: (True, "ok"))
    monkeypatch.setattr("core.llm.quality_gate.quality_gate.validate", lambda response: {"valid": True, "reason": ""})
    monkeypatch.setattr("core.resilience.circuit_breaker.resilience_manager.can_call", lambda provider: True)
    monkeypatch.setattr("core.resilience.circuit_breaker.resilience_manager.record_success", lambda provider: None)
    monkeypatch.setattr("core.llm_client.is_external_provider", lambda provider: False)

    out = await client.generate("Merhaba", user_id="u1", model="gpt-4o")
    assert "gpt-4o" in out
