from __future__ import annotations

from typing import Any, Dict, List

from core.compat.legacy_tool_wrappers import normalize_legacy_tool_payload
from core.skills.base import BaseSkill
from core.skills.tool_runtime import execute_registered_tool


class QuivrSkill(BaseSkill):
    @property
    def name(self) -> str:
        return "quivr"

    @property
    def description(self) -> str:
        return "Quivr second-brain scaffolding, grounded Q&A, retrieval workflow and local fallback RAG."

    @property
    def version(self) -> str:
        return "1.0.0"

    async def setup(self) -> bool:
        return True

    async def shutdown(self):
        pass

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {"name": "quivr_status", "description": "Inspect a Quivr second-brain project."},
            {"name": "quivr_project", "description": "Prepare, scaffold, or query a Quivr app."},
            {"name": "quivr_scaffold", "description": "Create a Quivr starter app."},
            {"name": "quivr_brain_ask", "description": "Ask a question against a Quivr brain."},
        ]

    async def execute_tool(self, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if tool_name in {
            "quivr_status",
            "quivr_project",
            "quivr_scaffold",
            "quivr_brain_ask",
        }:
            return await execute_registered_tool(tool_name, params, source="quivr_skill", skill_name=self.name)
        return normalize_legacy_tool_payload(
            {
                "success": False,
                "status": "failed",
                "error": f"Tool {tool_name} not found in quivr skill",
                "errors": ["UNKNOWN_TOOL"],
                "data": {"error_code": "UNKNOWN_TOOL"},
            },
            tool=tool_name,
            source="quivr_skill",
        )


def get_skill(config):
    return QuivrSkill(config)
