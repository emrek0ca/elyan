from typing import List, Dict, Any
from .base import BaseSkill
from .tool_runtime import execute_registered_tool
from core.compat.legacy_tool_wrappers import normalize_legacy_tool_payload

class SystemSkill(BaseSkill):
    @property
    def name(self) -> str:
        return "system"

    @property
    def description(self) -> str:
        return "Core system monitoring and control tools."

    async def setup(self) -> bool:
        return True

    async def shutdown(self):
        pass

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "get_system_info",
                "description": "Get CPU, RAM and Disk status."
            },
            {
                "name": "take_screenshot",
                "description": "Capture the current screen."
            }
        ]

    async def execute_tool(self, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if tool_name == "get_system_info":
            return await execute_registered_tool("get_system_info", params, source="system_skill")
        elif tool_name == "take_screenshot":
            return await execute_registered_tool("take_screenshot", params, source="system_skill")
        return normalize_legacy_tool_payload(
            {
                "success": False,
                "status": "failed",
                "error": f"Tool {tool_name} not found in system skill",
                "errors": ["UNKNOWN_TOOL"],
                "data": {"error_code": "UNKNOWN_TOOL"},
            },
            tool=tool_name,
            source="system_skill",
        )

def get_skill(config):
    return SystemSkill(config)
