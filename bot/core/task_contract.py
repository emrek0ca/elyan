"""
Task Contract primitives for delivery-oriented execution.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


@dataclass
class TaskContract:
    objective: str
    capability_domain: str
    output_artifacts: list[str]
    quality_checklist: list[str]
    verification_method: str
    failure_conditions: list[str]
    retry_strategy: str
    security_level: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_task_contract(execution_requirements: dict[str, Any], task_count: int) -> TaskContract:
    req = execution_requirements or {}
    domain = str(req.get("capability_domain", "general"))
    objective = str(req.get("primary_objective", "solve_user_task_reliably"))
    artifacts = req.get("output_artifacts", ["result"])
    if not isinstance(artifacts, list) or not artifacts:
        artifacts = ["result"]
    quality = req.get("quality_checklist", ["correctness", "clarity"])
    if not isinstance(quality, list) or not quality:
        quality = ["correctness", "clarity"]

    security_level = "safe"
    if task_count >= 4:
        security_level = "system"
    if domain in {"code", "website"} and task_count >= 6:
        security_level = "destructive"

    verification_method = "artifact_and_result_validation"
    failure_conditions = [
        "required_artifact_missing",
        "execution_error",
        "quality_checklist_not_met",
    ]
    retry_strategy = "auto_replan_once_then_report"

    return TaskContract(
        objective=objective,
        capability_domain=domain,
        output_artifacts=[str(x) for x in artifacts],
        quality_checklist=[str(x) for x in quality],
        verification_method=verification_method,
        failure_conditions=failure_conditions,
        retry_strategy=retry_strategy,
        security_level=security_level,
    )

