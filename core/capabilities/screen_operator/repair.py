from __future__ import annotations

from typing import Any, Callable

from core.contracts.failure_taxonomy import FailureCode
from core.repair.policies import get_repair_policy


def repair_screen_operator_runtime(
    ctx: Any,
    verify_result: dict[str, Any] | None = None,
    *,
    synthesize_summary: Callable[[Any], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    result = dict(verify_result or {})
    failed = list(result.get("failed") or [])
    failure_codes = list(result.get("failed_codes") or [])
    if FailureCode.SCREEN_SUMMARY_MISSING.value in failure_codes and callable(synthesize_summary):
        repaired = synthesize_summary(ctx)
        if isinstance(repaired, dict):
            repaired.setdefault("repaired", True)
            repaired.setdefault("strategy", "synthesize_screen_summary")
            repaired.setdefault("failed_codes", failure_codes)
            return repaired
    if failed or failure_codes:
        primary_code = failure_codes[0] if failure_codes else FailureCode.ARTIFACT_MISSING.value
        policy = get_repair_policy(primary_code)
        return {
            "repaired": False,
            "strategy": "controlled_screen_failure",
            "recommended_strategy": policy.strategy,
            "retry_budget": int(policy.retry_budget),
            "failure_code": primary_code,
            "failed": failed,
            "failed_codes": failure_codes or [primary_code],
            "message": "Screen capability doğrulanabilir sonuç üretemedi.",
        }
    return {"repaired": False, "strategy": "noop", "failed": [], "failed_codes": []}
