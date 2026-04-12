"""Shared skill health summary for CLI, gateway, and desktop surfaces."""
from __future__ import annotations

from typing import Any

from core.skills.manager import skill_manager


def build_skills_summary(*, query: str = "", available: bool = True, enabled_only: bool = False) -> dict[str, Any]:
    items = skill_manager.list_skills(available=available, enabled_only=enabled_only, query=query or "")
    installed = [item for item in items if item.get("installed")]
    enabled = [item for item in installed if item.get("enabled")]
    unhealthy = [item for item in installed if not item.get("health_ok")]
    runtime_ready = [item for item in installed if item.get("runtime_ready")]
    workflows = skill_manager.list_workflows()
    workflows_enabled = [workflow for workflow in workflows if workflow.get("enabled")]
    return {
        "skills": items,
        "summary": {
            "total": len(items),
            "installed": len(installed),
            "enabled": len(enabled),
            "issues": len(unhealthy),
            "runtime_ready": len(runtime_ready),
            "workflows_total": len(workflows),
            "workflows_enabled": len(workflows_enabled),
        },
    }
