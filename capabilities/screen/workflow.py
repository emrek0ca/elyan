from __future__ import annotations

from typing import Any, Callable

from .schema import build_screen_contract
from .verifier import verify_screen_runtime
from .repair import repair_screen_runtime


def evaluate_screen_runtime(
    ctx: Any,
    *,
    synthesize_summary: Callable[[Any], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    intent = getattr(ctx, "intent", {}) if isinstance(getattr(ctx, "intent", {}), dict) else {}
    params = intent.get("params", {}) if isinstance(intent.get("params"), dict) else {}
    contract = build_screen_contract(action=str(getattr(ctx, "action", "") or ""), params=params)
    verify = verify_screen_runtime(ctx)
    repair = repair_screen_runtime(ctx, verify, synthesize_summary=synthesize_summary)
    return {"contract": contract, "verify": verify, "repair": repair}

