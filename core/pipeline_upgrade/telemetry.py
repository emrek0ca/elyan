from __future__ import annotations

import time
from typing import Any


class JobTelemetryAccumulator:
    def __init__(self) -> None:
        self._started_at = time.time()
        self._first_artifact_at: float | None = None

    def mark_first_artifact(self) -> None:
        if self._first_artifact_at is None:
            self._first_artifact_at = time.time()

    def snapshot(
        self,
        *,
        complexity_score: float,
        token_cost_estimate: int,
        tool_results: list[dict[str, Any]],
        verified: bool,
        repair_loops: int,
    ) -> dict[str, Any]:
        total_tools = len(tool_results or [])
        success_tools = 0
        for row in tool_results or []:
            if isinstance(row, dict):
                ok = row.get("success")
                if ok is True:
                    success_tools += 1
                elif isinstance(row.get("result"), dict) and row["result"].get("success") is True:
                    success_tools += 1
        tool_success_rate = (success_tools / total_tools) if total_tools else 0.0
        verify_pass_rate = 1.0 if verified else 0.0
        ttfa_ms = int(((self._first_artifact_at or time.time()) - self._started_at) * 1000)

        return {
            "complexity_score": round(float(complexity_score or 0.0), 3),
            "token_cost_estimate": int(max(0, token_cost_estimate)),
            "tool_success_rate": round(tool_success_rate, 3),
            "verify_pass_rate": round(verify_pass_rate, 3),
            "repair_loops": int(max(0, repair_loops)),
            "ttfa_ms": ttfa_ms,
        }


def estimate_token_cost(*, user_input: str, memory_context: str, plan: list[dict[str, Any]]) -> int:
    # Cheap heuristic to avoid extra LLM calls.
    raw = len(str(user_input or "")) + len(str(memory_context or "")) + (len(plan or []) * 120)
    return int(max(200, raw // 3))
