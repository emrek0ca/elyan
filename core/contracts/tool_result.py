from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .execution_result import ArtifactRecord, ExecutionResult, ToolResult, coerce_execution_result
from .failure_taxonomy import FailureCode


ALLOWED_TOOL_STATUSES = frozenset({"success", "partial", "failed", "blocked", "needs_input", "noop"})


@dataclass(frozen=True)
class ToolContractViolation:
    tool: str
    reason: str
    error_code: str = FailureCode.TOOL_CONTRACT_VIOLATION.value

    def to_dict(self) -> dict[str, Any]:
        return {"tool": self.tool, "reason": self.reason, "error_code": self.error_code}


def normalize_tool_status(status: Any) -> str:
    clean = str(status or "").strip().lower()
    return clean if clean in ALLOWED_TOOL_STATUSES else "failed"


def _has_observable_payload(result: ExecutionResult) -> bool:
    return bool(
        str(result.message or "").strip()
        or list(result.artifacts or [])
        or dict(result.data or {})
        or list(result.errors or [])
        or list(result.evidence or [])
    )


def tool_contract_violation(*, tool: str = "", reason: str, raw: Any = None) -> ExecutionResult:
    violation = ToolContractViolation(tool=str(tool or ""), reason=str(reason or "legacy_tool_contract_violation"))
    return ExecutionResult(
        status="failed",
        message=violation.reason,
        artifacts=[],
        evidence=[violation.to_dict()],
        data={"error_code": violation.error_code, "tool": violation.tool},
        errors=[violation.error_code],
        metrics={},
        raw=raw,
    )


def coerce_tool_result(payload: Any, *, tool: str = "", source: str = "execution") -> ExecutionResult:
    if payload is None:
        return tool_contract_violation(tool=tool, reason="legacy tool returned None", raw=payload)

    normalized = coerce_execution_result(payload, tool=tool, source=source)
    normalized.status = normalize_tool_status(normalized.status)

    if not _has_observable_payload(normalized) and normalized.status == "success":
        return tool_contract_violation(tool=tool, reason="legacy tool returned ambiguous success payload", raw=payload)

    return normalized


def coerce_tool_results(rows: Iterable[Any], *, tool: str = "", source: str = "execution") -> list[ExecutionResult]:
    return [coerce_tool_result(row, tool=tool, source=source) for row in rows]


__all__ = [
    "ALLOWED_TOOL_STATUSES",
    "ArtifactRecord",
    "ExecutionResult",
    "ToolContractViolation",
    "ToolResult",
    "coerce_tool_result",
    "coerce_tool_results",
    "normalize_tool_status",
    "tool_contract_violation",
]
