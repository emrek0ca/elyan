from typing import List, Dict, Any
from .base import BaseSkill
from tools.system_tools import get_system_info, take_screenshot

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
            return await get_system_info()
        elif tool_name == "take_screenshot":
            return await take_screenshot()
        return {"success": False, "error": f"Tool {tool_name} not found in system skill"}

def get_skill(config):
    return SystemSkill(config)
