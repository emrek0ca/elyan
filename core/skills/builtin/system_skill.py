"""System skill - wraps system_tools for volume, brightness, screenshot, etc."""

from typing import List, Dict, Any
from core.skills.base import BaseSkill
from core.skills.tool_runtime import execute_registered_tool, wrap_skill_tool_result


class SystemSkill(BaseSkill):
    @property
    def name(self) -> str:
        return "system"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def description(self) -> str:
        return "Sistem bilgisi, ekran goruntusu, ses ve parlaklik kontrolu"

    @property
    def required_tools(self) -> List[str]:
        return ["set_volume", "set_brightness", "screenshot", "system_info"]

    async def setup(self) -> bool:
        return True

    async def execute(self, command: str, context: Dict[str, Any]) -> Dict[str, Any]:
        try:
            params = context.get("params", {})

            if command == "volume":
                level = params.get("level", 50)
                result = await execute_registered_tool("set_volume", {"level": level}, source="builtin_system_skill")
                return wrap_skill_tool_result(result)
            elif command == "brightness":
                level = params.get("level", 50)
                result = await execute_registered_tool("set_brightness", {"level": level}, source="builtin_system_skill")
                return wrap_skill_tool_result(result)
            elif command == "screenshot":
                result = await execute_registered_tool("take_screenshot", {}, source="builtin_system_skill")
                return wrap_skill_tool_result(result)
            elif command == "sysinfo":
                result = await execute_registered_tool("get_system_info", {}, source="builtin_system_skill")
                return wrap_skill_tool_result(result)
            elif command == "battery":
                result = await execute_registered_tool("get_battery_status", {}, source="builtin_system_skill")
                return wrap_skill_tool_result(result)
            else:
                return {"success": False, "error": f"Unknown command: {command}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_commands(self) -> List[Dict[str, Any]]:
        return [
            {"name": "volume", "description": "Ses seviyesini ayarla", "params": ["level"]},
            {"name": "brightness", "description": "Parlaklik ayarla", "params": ["level"]},
            {"name": "screenshot", "description": "Ekran goruntusu al", "params": []},
            {"name": "sysinfo", "description": "Sistem bilgisi goster", "params": []},
            {"name": "battery", "description": "Pil durumu goster", "params": []},
        ]
