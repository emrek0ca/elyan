"""
core/timeout_guard.py
─────────────────────────────────────────────────────────────────────────────
Hiçbir işlem sonsuza kadar takılmasın.

Kullanım:
    result = await with_timeout(some_coro(), seconds=30, fallback="Zaman aşımı.")
"""
from __future__ import annotations

import asyncio
import functools
from typing import Any, Callable, Coroutine, Optional, TypeVar

from utils.logger import get_logger

logger = get_logger("timeout_guard")

T = TypeVar("T")

# ── Varsayılan limitler (saniye) ─────────────────────────────────────────────
LLM_TIMEOUT       = 45   # LLM cevap üretimi
PLANNER_TIMEOUT   = 35   # Plan oluşturma
TOOL_TIMEOUT      = 60   # Tek araç çalıştırma
RESEARCH_TIMEOUT  = 90   # Web araştırması (daha uzun sürebilir)
STEP_TIMEOUT      = 120  # Planner adımı (araştırma içerebilir)
TOTAL_TIMEOUT     = 180  # Tüm process() — mutlak üst sınır


async def with_timeout(
    coro: Coroutine[Any, Any, T],
    seconds: float,
    fallback: Optional[T] = None,
    context: str = "",
) -> T:
    """
    Coroutine'i `seconds` içinde tamamlamaya zorla.
    Aşılırsa `fallback` döner (None ise TimeoutError'ı ilet).
    """
    try:
        return await asyncio.wait_for(coro, timeout=seconds)
    except asyncio.TimeoutError:
        label = f"[{context}] " if context else ""
        logger.warning(f"{label}Timeout after {seconds}s")
        if fallback is not None:
            return fallback  # type: ignore[return-value]
        raise


def timeout_wrap(seconds: float, fallback: Any = None, context: str = ""):
    """
    Decorator: async fonksiyona timeout ekler.

    @timeout_wrap(seconds=30, fallback="timeout")
    async def my_func(...): ...
    """
    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            return await with_timeout(
                fn(*args, **kwargs),
                seconds=seconds,
                fallback=fallback,
                context=context or fn.__name__,
            )
        return wrapper
    return decorator


def friendly_timeout_message(context: str = "") -> str:
    """Kullanıcıya gösterilen zaman aşımı mesajı."""
    if "planner" in context or "plan" in context:
        return "Bu istek biraz karmaşık, biraz daha basit ifade edebilir misin?"
    if "research" in context or "araştır" in context:
        return "Araştırma zaman aşımına uğradı. Konuyu biraz daraltmayı dene."
    if "llm" in context or "chat" in context:
        return "AI yanıt üretirken zaman aşımına uğradı. Tekrar dener misin?"
    return "İşlem zaman aşımına uğradı. Lütfen tekrar dene."
