"""
Unified repair state machine for Elyan.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List
from core.repair.error_codes import PLAN_ERROR, TOOL_ERROR, ENV_ERROR, VALIDATION_ERROR, RETRYABLE
from core.telemetry.events import TelemetryEvent
from core.telemetry.run_store import TelemetryRunStore


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

    @staticmethod
    def _telemetry_store(context: Dict[str, Any] | None) -> TelemetryRunStore | None:
        if not isinstance(context, dict):
            return None
        request_id = str(context.get("request_id") or context.get("run_id") or "").strip()
        if not request_id:
            return None
        return TelemetryRunStore(request_id)

    async def run(self, error_code: str, attempt_fn, *, context: Dict[str, Any] | None = None) -> RepairOutcome:
        """
        attempt_fn: async callable (attempt_idx, context) -> {"success": bool, "error": str}
        """
        attempts = 0
        history: List[Dict[str, Any]] = []
        telemetry_store = self._telemetry_store(context)
        if telemetry_store is not None:
            telemetry_store.record_event(
                TelemetryEvent(
                    event="repair.started",
                    request_id=telemetry_store.run_id,
                    tool_name=str((context or {}).get("tool") or ""),
                    status="started",
                    retry_count=0,
                    payload={"error_code": error_code, "max_attempts": int(self.max_attempts)},
                )
            )
        if error_code not in RETRYABLE:
            if telemetry_store is not None:
                telemetry_store.record_event(
                    TelemetryEvent(
                        event="repair.finished",
                        request_id=telemetry_store.run_id,
                        tool_name=str((context or {}).get("tool") or ""),
                        status="non_retryable",
                        retry_count=0,
                        payload={
                            "error_code": error_code,
                            "attempts_used": 0,
                            "max_attempts": int(self.max_attempts),
                            "retry_budget_remaining": int(self.max_attempts),
                        },
                    )
                )
            return RepairOutcome(False, attempts, last_error="non-retryable", error_code=error_code)
        for idx in range(1, self.max_attempts + 1):
            attempts = idx
            res = await attempt_fn(idx, context or {})
            success = bool(res.get("success"))
            err = str(res.get("error", "")) if isinstance(res, dict) else ""
            history.append({"attempt": idx, "success": success, "error": err})
            if success:
                if telemetry_store is not None:
                    telemetry_store.record_event(
                        TelemetryEvent(
                            event="repair.finished",
                            request_id=telemetry_store.run_id,
                            tool_name=str((context or {}).get("tool") or ""),
                            status="success",
                            retry_count=int(idx),
                            payload={
                                "error_code": error_code,
                                "attempts_used": int(idx),
                                "max_attempts": int(self.max_attempts),
                                "retry_budget_remaining": max(0, int(self.max_attempts) - int(idx)),
                                "history": list(history),
                            },
                        )
                    )
                return RepairOutcome(True, attempts, history=history)
        if telemetry_store is not None:
            telemetry_store.record_event(
                TelemetryEvent(
                    event="repair.finished",
                    request_id=telemetry_store.run_id,
                    tool_name=str((context or {}).get("tool") or ""),
                    status="failed",
                    retry_count=int(attempts),
                    payload={
                        "error_code": error_code,
                        "attempts_used": int(attempts),
                        "max_attempts": int(self.max_attempts),
                        "retry_budget_remaining": max(0, int(self.max_attempts) - int(attempts)),
                        "history": list(history),
                    },
                )
            )
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
