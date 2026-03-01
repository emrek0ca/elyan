"""
Unified repair state machine for Elyan.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List
from core.repair.error_codes import PLAN_ERROR, TOOL_ERROR, ENV_ERROR, VALIDATION_ERROR, RETRYABLE


@dataclass
class RepairOutcome:
    success: bool
    attempts: int
    last_error: str = ""
    error_code: str = ""
    history: List[Dict[str, Any]] = field(default_factory=list)


class RepairStateMachine:
    def __init__(self, max_attempts: int = 2):
        self.max_attempts = max_attempts

    async def run(self, error_code: str, attempt_fn, *, context: Dict[str, Any] | None = None) -> RepairOutcome:
        """
        attempt_fn: async callable (attempt_idx, context) -> {"success": bool, "error": str}
        """
        attempts = 0
        history: List[Dict[str, Any]] = []
        if error_code not in RETRYABLE:
            return RepairOutcome(False, attempts, last_error="non-retryable", error_code=error_code)
        for idx in range(1, self.max_attempts + 1):
            attempts = idx
            res = await attempt_fn(idx, context or {})
            success = bool(res.get("success"))
            err = str(res.get("error", "")) if isinstance(res, dict) else ""
            history.append({"attempt": idx, "success": success, "error": err})
            if success:
                return RepairOutcome(True, attempts, history=history)
        return RepairOutcome(False, attempts, last_error=history[-1]["error"] if history else "", error_code=error_code, history=history)


def classify_error(exc: Exception) -> str:
    msg = str(exc).lower()
    if "plan" in msg or "invalid task" in msg:
        return PLAN_ERROR
    if "permission" in msg or "not found" in msg or "path" in msg:
        return ENV_ERROR
    if "validation" in msg or "assert" in msg or "failed check" in msg:
        return VALIDATION_ERROR
    return TOOL_ERROR


__all__ = ["RepairStateMachine", "RepairOutcome", "classify_error"]
