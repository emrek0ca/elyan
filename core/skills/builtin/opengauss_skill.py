from __future__ import annotations

from typing import Any, Dict, List

from core.compat.legacy_tool_wrappers import normalize_legacy_tool_payload
from core.skills.base import BaseSkill
from core.skills.tool_runtime import execute_registered_tool


class OpenGaussSkill(BaseSkill):
    @property
    def name(self) -> str:
        return "opengauss"

    @property
    def description(self) -> str:
        return "OpenGauss database scaffolding, schema bootstrap, query planning and backup-oriented workflows."

    @property
    def version(self) -> str:
        return "1.0.0"

    async def setup(self) -> bool:
        return True

    async def shutdown(self):
        pass

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {"name": "opengauss_status", "description": "Inspect an OpenGauss project or database workspace."},
            {"name": "opengauss_project", "description": "Prepare, scaffold, or query an OpenGauss workspace."},
            {"name": "opengauss_scaffold", "description": "Create an OpenGauss starter workspace."},
            {"name": "opengauss_query", "description": "Prepare an OpenGauss SQL query plan or command."},
            {"name": "opengauss_workflow", "description": "Build an OpenGauss workflow bundle."},
        ]

    async def execute_tool(self, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if tool_name in {
            "opengauss_status",
            "opengauss_project",
            "opengauss_scaffold",
            "opengauss_query",
            "opengauss_workflow",
        }:
            return await execute_registered_tool(tool_name, params, source="opengauss_skill", skill_name=self.name)
        return normalize_legacy_tool_payload(
            {
                "success": False,
                "status": "failed",
                "error": f"Tool {tool_name} not found in opengauss skill",
                "errors": ["UNKNOWN_TOOL"],
                "data": {"error_code": "UNKNOWN_TOOL"},
            },
            tool=tool_name,
            source="opengauss_skill",
        )


def get_skill(config):
    return OpenGaussSkill(config)
