import asyncio

from bot.core.intelligent_planner import IntelligentPlanner


class _BadLLM:
    async def generate(self, prompt, max_tokens=600, **kwargs):
        _ = (prompt, max_tokens, kwargs)
        return "not json"


def test_decompose_task_falls_back_on_invalid_json(monkeypatch):
    monkeypatch.setattr("core.llm_client.LLMClient", lambda: _BadLLM())

    planner = IntelligentPlanner()
    subtasks = asyncio.run(planner.decompose_task("kemal", use_llm=True))
    assert len(subtasks) == 1
    assert subtasks[0].name == "kemal"
