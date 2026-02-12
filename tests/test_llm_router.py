import asyncio

import httpx

from core.llm_client import LLMClient


def test_llm_router_aggressive_fallback_timeout_then_success():
    client = LLMClient()
    client.llm_type = "groq"
    client.fallback_mode = "aggressive"
    client.fallback_order = ["groq", "openai", "ollama"]

    async def run_case():
        def fake_available(provider: str) -> bool:
            return provider in {"groq", "openai"}

        async def fake_call_provider(provider: str, prompt: str, user_message: str, temp: float, max_tokens=None):
            if provider == "groq":
                raise httpx.TimeoutException("timeout")
            if provider == "openai":
                return "ok from openai"
            return None

        client._is_provider_available = fake_available
        client._call_provider = fake_call_provider

        text = await client._call_any_provider("prompt", user_message="hello", temp=0.2)
        trace = client.get_last_router_trace()
        return text, trace

    text, trace = asyncio.run(run_case())

    assert text == "ok from openai"
    assert trace[0]["provider"] == "groq"
    assert trace[0]["reason"] == "timeout"
    assert trace[1]["provider"] == "openai"
    assert trace[1]["status"] == "success"


def test_chat_uses_single_router_path():
    client = LLMClient()

    async def run_case():
        async def fake_call_any_provider(prompt: str, user_message: str = "", temp: float = 0.3, max_tokens=None):
            assert "Kullanıcı:" in prompt
            return "Merhaba, yardımcı olayım."

        client._call_any_provider = fake_call_any_provider
        return await client.chat("selam")

    result = asyncio.run(run_case())
    assert "Merhaba" in result


def test_generate_cost_guard_caps_temperature_and_tokens():
    client = LLMClient()
    client.cost_guard = True

    async def run_case():
        captured = {}

        async def fake_call_any_provider(prompt: str, user_message: str = "", temp: float = 0.3, max_tokens=None):
            captured["temp"] = temp
            captured["max_tokens"] = max_tokens
            return "ok"

        client._call_any_provider = fake_call_any_provider
        await client.generate("test prompt", temperature=0.9)
        return captured

    captured = asyncio.run(run_case())
    assert captured["temp"] <= 0.35
    assert captured["max_tokens"] == 320


def test_chat_cost_guard_uses_short_token_budget():
    client = LLMClient()
    client.cost_guard = True

    async def run_case():
        captured = {}

        async def fake_call_any_provider(prompt: str, user_message: str = "", temp: float = 0.3, max_tokens=None):
            captured["max_tokens"] = max_tokens
            return "ok"

        client._call_any_provider = fake_call_any_provider
        await client.chat("selam")
        return captured

    captured = asyncio.run(run_case())
    assert captured["max_tokens"] == 260
