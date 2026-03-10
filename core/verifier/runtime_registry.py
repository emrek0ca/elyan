from __future__ import annotations

from typing import Any, Callable

from core.capabilities.registry import evaluate_capability_runtime


def evaluate_runtime_capability(
    ctx: Any,
    *,
    synthesize_screen_summary: Callable[[Any], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return evaluate_capability_runtime(
        ctx,
        synthesize_screen_summary=synthesize_screen_summary,
    )
