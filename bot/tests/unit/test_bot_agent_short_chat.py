import asyncio
from types import SimpleNamespace

from bot.core.agent import Agent
from core.quick_intent import IntentCategory


class _DummyMemory:
    def get_recent_conversations(self, user_id, limit=5):
        _ = (user_id, limit)
        return []

    def store_conversation(self, user_id, user_input, bot_response):
        _ = (user_id, user_input, bot_response)
        return None


class _DummyTools:
    async def execute(self, tool_name, params):
        raise ValueError(f"not found: {tool_name}")


class _DummyLLM:
    async def generate(self, prompt, role="inference", history=None, **kwargs):
        _ = (prompt, role, history, kwargs)
        return "ok"


class _DummyQuickIntentUnknown:
    def detect(self, _text):
        return SimpleNamespace(category=IntentCategory.UNKNOWN)


def test_short_chat_like_input_bypasses_planner(monkeypatch):
    agent = Agent()
    agent.llm = _DummyLLM()
    agent.kernel = SimpleNamespace(memory=_DummyMemory(), tools=_DummyTools())
    agent.quick_intent = _DummyQuickIntentUnknown()
    agent.intent_parser = SimpleNamespace(parse=lambda _text: {"action": "unknown", "params": {}})

    class _UnexpectedPlanner:
        async def create_plan(self, *_args, **_kwargs):
            raise AssertionError("planner must not run for short chat-like input")

        def evaluate_plan_quality(self, *_args, **_kwargs):
            return {"safe_to_run": True}

    agent.planner = _UnexpectedPlanner()
    response = asyncio.run(agent.process("kemal"))
    assert response == "ok"
