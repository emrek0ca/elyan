"""
tests/unit/test_timeout_guard.py
timeout_guard modülü için birim testleri.
"""
import asyncio
import pytest


# ── with_timeout ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_with_timeout_completes_normally():
    from core.timeout_guard import with_timeout

    async def fast():
        return "done"

    result = await with_timeout(fast(), seconds=5.0)
    assert result == "done"


@pytest.mark.asyncio
async def test_with_timeout_returns_fallback_on_timeout():
    from core.timeout_guard import with_timeout

    async def slow():
        await asyncio.sleep(10)
        return "too late"

    result = await with_timeout(slow(), seconds=0.01, fallback="timed_out")
    assert result == "timed_out"


@pytest.mark.asyncio
async def test_with_timeout_raises_when_no_fallback():
    from core.timeout_guard import with_timeout

    async def slow():
        await asyncio.sleep(10)

    with pytest.raises(asyncio.TimeoutError):
        await with_timeout(slow(), seconds=0.01, fallback=None)


@pytest.mark.asyncio
async def test_with_timeout_passes_context_to_log(caplog):
    import logging
    from core.timeout_guard import with_timeout

    async def slow():
        await asyncio.sleep(10)

    with caplog.at_level(logging.WARNING, logger="timeout_guard"):
        result = await with_timeout(slow(), seconds=0.01, fallback="fallback", context="test_ctx")
    assert result == "fallback"
    assert "test_ctx" in caplog.text


# ── timeout_wrap decorator ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_timeout_wrap_decorator_completes():
    from core.timeout_guard import timeout_wrap

    @timeout_wrap(seconds=5.0, fallback="nope")
    async def fast(x):
        return f"val:{x}"

    result = await fast(42)
    assert result == "val:42"


@pytest.mark.asyncio
async def test_timeout_wrap_decorator_returns_fallback():
    from core.timeout_guard import timeout_wrap

    @timeout_wrap(seconds=0.01, fallback="timeout_fallback")
    async def slow():
        await asyncio.sleep(10)

    result = await slow()
    assert result == "timeout_fallback"


@pytest.mark.asyncio
async def test_timeout_wrap_preserves_function_name():
    from core.timeout_guard import timeout_wrap

    @timeout_wrap(seconds=5.0)
    async def my_function():
        pass

    assert my_function.__name__ == "my_function"


# ── friendly_timeout_message ──────────────────────────────────────────────────

def test_friendly_message_planner():
    from core.timeout_guard import friendly_timeout_message
    msg = friendly_timeout_message("planner")
    assert "basit" in msg.lower() or "karmaşık" in msg.lower()


def test_friendly_message_research():
    from core.timeout_guard import friendly_timeout_message
    msg = friendly_timeout_message("research")
    assert "araştırma" in msg.lower()


def test_friendly_message_llm():
    from core.timeout_guard import friendly_timeout_message
    msg = friendly_timeout_message("llm")
    assert "ai" in msg.lower() or "yanıt" in msg.lower() or "zaman" in msg.lower()


def test_friendly_message_unknown():
    from core.timeout_guard import friendly_timeout_message
    msg = friendly_timeout_message("unknown_ctx")
    assert msg  # Non-empty fallback


# ── Constants sanity ─────────────────────────────────────────────────────────

def test_timeout_constants_ordered():
    from core.timeout_guard import (
        LLM_TIMEOUT, PLANNER_TIMEOUT, TOOL_TIMEOUT,
        RESEARCH_TIMEOUT, STEP_TIMEOUT, TOTAL_TIMEOUT,
    )
    # Research should be longer than a single tool
    assert RESEARCH_TIMEOUT >= TOOL_TIMEOUT
    # Total should be the largest
    assert TOTAL_TIMEOUT >= STEP_TIMEOUT
    assert TOTAL_TIMEOUT >= RESEARCH_TIMEOUT
    # All positive
    assert all(t > 0 for t in [LLM_TIMEOUT, PLANNER_TIMEOUT, TOOL_TIMEOUT,
                                RESEARCH_TIMEOUT, STEP_TIMEOUT, TOTAL_TIMEOUT])
