from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ToolSpec:
    requested_name: str
    resolved_name: str
    params: dict[str, Any] = field(default_factory=dict)
    source: str = "agent"
    requires_approval: bool = False
    risk_level: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ExecutionRequest:
    tool_name: str
    params: dict[str, Any]
    user_input: str = ""
    step_name: str = ""
    pipeline_state: Any = None
    action_aliases: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class VerificationEnvelope:
    verified: bool | None = None
    warning: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_result(cls, result: Any) -> "VerificationEnvelope":
        if not isinstance(result, dict):
            return cls()
        return cls(
            verified=(bool(result.get("verified")) if "verified" in result else None),
            warning=str(result.get("verification_warning") or ""),
            evidence=dict(result.get("_proof") or {}) if isinstance(result.get("_proof"), dict) else {},
            metadata={
                "error_code": str(result.get("error_code") or ""),
                "status": str(result.get("status") or ""),
            },
        )


@dataclass(slots=True)
class ExecutionOutcome:
    spec: ToolSpec
    result: dict[str, Any]
    success: bool
    error_text: str = ""
    latency_ms: int = 0
    source: str = "tool_runtime_executor"
    verification: VerificationEnvelope = field(default_factory=VerificationEnvelope)
