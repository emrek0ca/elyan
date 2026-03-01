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

