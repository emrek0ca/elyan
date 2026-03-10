from __future__ import annotations

from typing import Any, Callable


def repair_screen_runtime(
    ctx: Any,
    verify_result: dict[str, Any] | None = None,
    *,
    synthesize_summary: Callable[[Any], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    result = dict(verify_result or {})
    failed = list(result.get("failed") or [])
    if "summary_present" in failed and callable(synthesize_summary):
        return synthesize_summary(ctx)
    if failed:
        return {
            "repaired": False,
            "strategy": "controlled_screen_failure",
            "failed": failed,
            "message": "Screen capability doğrulanabilir sonuç üretemedi.",
        }
    return {"repaired": False, "strategy": "noop", "failed": []}

