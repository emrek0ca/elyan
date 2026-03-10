from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PlanCondition:
    code: str
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "payload": dict(self.payload)}


@dataclass
class PlanStep:
    step_id: str
    capability: str
    action: str
    params: dict[str, Any] = field(default_factory=dict)
    preconditions: list[PlanCondition] = field(default_factory=list)
    postconditions: list[PlanCondition] = field(default_factory=list)
    timeout_ms: int = 0
    repair_policy: dict[str, Any] = field(default_factory=dict)
    verify_policy: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "capability": self.capability,
            "action": self.action,
            "params": dict(self.params),
            "preconditions": [item.to_dict() for item in self.preconditions],
            "postconditions": [item.to_dict() for item in self.postconditions],
            "timeout_ms": int(self.timeout_ms or 0),
            "repair_policy": dict(self.repair_policy),
            "verify_policy": dict(self.verify_policy),
        }


@dataclass
class ExecutionPlan:
    request_id: str
    workflow_path: list[str] = field(default_factory=list)
    steps: list[PlanStep] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "workflow_path": list(self.workflow_path),
            "steps": [item.to_dict() for item in self.steps],
            "metadata": dict(self.metadata),
        }


__all__ = ["ExecutionPlan", "PlanCondition", "PlanStep"]
