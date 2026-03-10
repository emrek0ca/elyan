from __future__ import annotations

from typing import Any

from core.contracts.failure_taxonomy import FailureCode
from core.repair.policies import get_repair_policy


def repair_file_ops_runtime(ctx: Any, verify_result: dict[str, Any] | None = None) -> dict[str, Any]:
    result = dict(verify_result or {})
    failed = list(result.get("failed") or [])
    failure_codes = list(result.get("failed_codes") or [])
    if not failed and not failure_codes:
        return {"repaired": False, "strategy": "noop", "failed": [], "failed_codes": []}

    primary_code = failure_codes[0] if failure_codes else FailureCode.ARTIFACT_MISSING.value
    policy = get_repair_policy(primary_code)
    return {
        "repaired": False,
        "strategy": "controlled_file_ops_failure",
        "recommended_strategy": policy.strategy,
        "retry_budget": int(policy.retry_budget),
        "failure_code": primary_code,
        "failed": failed,
        "failed_codes": failure_codes or [primary_code],
        "message": "Dosya sistemi görevi doğrulama kapısından geçmedi.",
    }
