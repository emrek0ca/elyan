from __future__ import annotations

from typing import Any, Dict, List

from core.compat.legacy_tool_wrappers import normalize_legacy_tool_payload
from core.skills.base import BaseSkill
from core.skills.tool_runtime import execute_registered_tool


class LeanSkill(BaseSkill):
    @property
    def name(self) -> str:
        return "lean"

    @property
    def description(self) -> str:
        return "Lean 4 theorem proving, project-scoped formalization and swarm orchestration."

    @property
    def version(self) -> str:
        return "1.0.0"

    async def setup(self) -> bool:
        return True

    async def shutdown(self):
        pass

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {"name": "lean_status", "description": "Inspect Lean project and toolchain readiness."},
            {"name": "lean_project", "description": "Register, activate, or inspect Lean projects."},
            {"name": "lean_workflow", "description": "Run prove/draft/formalize workflows."},
            {"name": "lean_swarm", "description": "List or manage Lean workflow sessions."},
        ]

    async def execute_tool(self, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if tool_name in {"lean_status", "lean_project", "lean_workflow", "lean_swarm"}:
            return await execute_registered_tool(tool_name, params, source="lean_skill", skill_name=self.name)
        return normalize_legacy_tool_payload(
            {
                "success": False,
                "status": "failed",
                "error": f"Tool {tool_name} not found in lean skill",
                "errors": ["UNKNOWN_TOOL"],
                "data": {"error_code": "UNKNOWN_TOOL"},
            },
            tool=tool_name,
            source="lean_skill",
        )


def get_skill(config):
    return LeanSkill(config)
