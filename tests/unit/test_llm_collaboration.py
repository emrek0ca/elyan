import pytest

from core.llm_client import LLMClient
from core.sub_agent.executor import SubAgentExecutor
from core.sub_agent.session import SubAgentSession, SubAgentTask


@pytest.mark.asyncio
async def test_generate_collaborative_runs_parallel_views_and_synthesis():
    client = LLMClient()
    client.orchestrator.get_collaboration_settings = lambda: {
        "enabled": True,
        "strategy": "synthesize",
        "max_models": 2,
        "roles": ["reasoning"],
    }
    client.orchestrator.get_collaboration_pool = lambda role="reasoning", max_models=None: [
        {"type": "openai", "provider": "openai", "model": "gpt-4o"},
        {"type": "groq", "provider": "groq", "model": "llama-3.3-70b-versatile"},
    ]

    calls = []

    async def _fake_generate(prompt, system_prompt=None, model_config=None, role="reasoning", **kwargs):
        calls.append({"prompt": prompt, "model": (model_config or {}).get("model"), "role": role})
        if "paralel görüşleri var" in prompt:
            return "final-synthesis"
        return f"draft:{(model_config or {}).get('type')}:{role}"

    client.generate = _fake_generate  # type: ignore[method-assign]
    result = await LLMClient.generate_collaborative(client, "kullanici istegi", role="reasoning")

    assert result == "final-synthesis"
    assert len(calls) == 3
    assert calls[0]["model"] == "gpt-4o"
    assert calls[1]["model"] == "llama-3.3-70b-versatile"


@pytest.mark.asyncio
async def test_sub_agent_executor_uses_specialist_role_for_llm():
    captured = {}

    class _Agent:
        async def _execute_tool(self, *_a, **_k):
            return {"success": True}

    class _LLM:
        async def generate(self, prompt, role="inference", user_id="local", **kwargs):
            _ = (prompt, user_id, kwargs)
            captured["role"] = role
            return '{"final":"ok","done":true}'

    agent = _Agent()
    agent.llm = _LLM()
    sess = SubAgentSession(
        session_id="s-role",
        parent_session_id="p",
        specialist_key="qa",
        task=SubAgentTask(name="t", action="chat", params={"message": "kontrol et"}),
        allowed_tools=frozenset({"chat"}),
    )
    ex = SubAgentExecutor(agent)
    await ex.run(sess)
    assert captured["role"] == "qa"
