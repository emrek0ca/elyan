from __future__ import annotations

from typing import Any, Dict, List

from core.compat.legacy_tool_wrappers import normalize_legacy_tool_payload
from core.skills.base import BaseSkill
from core.skills.tool_runtime import execute_registered_tool


class CloudflareAgentsSkill(BaseSkill):
    @property
    def name(self) -> str:
        return "cloudflare_agents"

    @property
    def description(self) -> str:
        return "Cloudflare Agents starter, durable state, chat UI, workflows and MCP scaffolding."

    @property
    def version(self) -> str:
        return "1.0.0"

    async def setup(self) -> bool:
        return True

    async def shutdown(self):
        pass

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {"name": "cloudflare_agents_status", "description": "Inspect a Cloudflare Agents project."},
            {"name": "cloudflare_agents_project", "description": "Prepare or scaffold a Cloudflare Agents app."},
            {"name": "cloudflare_agents_scaffold", "description": "Create a starter app for Cloudflare Agents."},
            {"name": "cloudflare_agents_workflow", "description": "Build a starter or deployment workflow bundle."},
        ]

    async def execute_tool(self, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if tool_name in {
            "cloudflare_agents_status",
            "cloudflare_agents_project",
            "cloudflare_agents_scaffold",
            "cloudflare_agents_workflow",
        }:
            return await execute_registered_tool(tool_name, params, source="cloudflare_agents_skill", skill_name=self.name)
        return normalize_legacy_tool_payload(
            {
                "success": False,
                "status": "failed",
                "error": f"Tool {tool_name} not found in cloudflare_agents skill",
                "errors": ["UNKNOWN_TOOL"],
                "data": {"error_code": "UNKNOWN_TOOL"},
            },
            tool=tool_name,
            source="cloudflare_agents_skill",
        )


def get_skill(config):
    return CloudflareAgentsSkill(config)
