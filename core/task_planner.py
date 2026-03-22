from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.runtime.live_planner import LiveOperatorTaskPlanner


@dataclass
class TaskPlan:
    goal: str
    name: str
    steps: list[dict[str, Any]]
    constraints: list[str]
    dependencies: list[str]
    evidence: list[str]
    exit_criteria: list[str]
    approvals: list[str]
    parallel_steps: list[dict[str, Any]]
    rationale: str
    planning_trace: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "name": self.name,
            "steps": list(self.steps),
            "constraints": list(self.constraints),
            "dependencies": list(self.dependencies),
            "evidence": list(self.evidence),
            "exit_criteria": list(self.exit_criteria),
            "approvals": list(self.approvals),
            "parallel_steps": list(self.parallel_steps),
            "rationale": self.rationale,
            "planning_trace": dict(self.planning_trace),
        }


class TaskPlanner:
    """Canonical task planning wrapper around the live planner."""

    def __init__(self, live_planner: LiveOperatorTaskPlanner | None = None) -> None:
        self._live = live_planner or LiveOperatorTaskPlanner()

    def plan(self, request: str, *, context: dict[str, Any] | None = None) -> dict[str, Any]:
        raw = self._live.plan_request(str(request or ""))
        steps = [dict(item) for item in list(raw.get("steps") or []) if isinstance(item, dict)]
        constraints: list[str] = []
        approvals: list[str] = []
        dependencies: list[str] = []
        evidence: list[str] = []
        exit_criteria: list[str] = []
        parallel_steps: list[dict[str, Any]] = []
        for step in steps:
            kind = str(step.get("kind") or "").strip().lower()
            if kind in {"browser", "screen", "system"} and str(step.get("name") or "").startswith("open_"):
                dependencies.append(str(step.get("name") or ""))
            if kind in {"browser", "screen"} and str(step.get("action") or step.get("mode") or "").strip().lower() in {"click", "type", "submit"}:
                evidence.append(f"{step.get('name')}: verification required")
            if bool(step.get("native_dialog_expected")) or str(step.get("verify", {}).get("fallback_used", "")).lower() == "true":
                approvals.append(str(step.get("name") or ""))
            if kind in {"browser", "screen"} and str(step.get("repair_policy", {}).get("max_retries", 0)) and int(step.get("repair_policy", {}).get("max_retries", 0) or 0) > 0:
                exit_criteria.append(f"{step.get('name')}: verifiable outcome")
        if not exit_criteria:
            exit_criteria.append("Artifact veya doğrulama kanıtı oluşturulmalı.")
        if len(steps) > 1:
            parallel_steps = [dict(step) for step in steps if str(step.get("kind") or "") == "system"]
        task_plan = TaskPlan(
            goal=str(raw.get("goal") or request or ""),
            name=str(raw.get("name") or "operator-task"),
            steps=steps,
            constraints=constraints,
            dependencies=dependencies,
            evidence=evidence,
            exit_criteria=exit_criteria,
            approvals=approvals,
            parallel_steps=parallel_steps,
            rationale=str(raw.get("rationale") or ""),
            planning_trace=dict(raw.get("planning_trace") or {}),
        )
        payload = task_plan.to_dict()
        if context:
            payload["context"] = dict(context)
        return payload


_TASK_PLANNER: TaskPlanner | None = None


def get_task_planner() -> TaskPlanner:
    global _TASK_PLANNER
    if _TASK_PLANNER is None:
        _TASK_PLANNER = TaskPlanner()
    return _TASK_PLANNER


__all__ = ["TaskPlan", "TaskPlanner", "get_task_planner"]
