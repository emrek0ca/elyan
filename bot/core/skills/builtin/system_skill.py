"""System skill - wraps system_tools for volume, brightness, screenshot, etc."""

from typing import List, Dict, Any
from core.skills.base import BaseSkill


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
            from tools.system_tools import (
                set_volume, set_brightness, take_screenshot,
                get_system_info, get_battery_status,
            )
            params = context.get("params", {})

            if command == "volume":
                level = params.get("level", 50)
                result = await set_volume(level)
                return {"success": True, "result": result}
            elif command == "brightness":
                level = params.get("level", 50)
                result = await set_brightness(level)
                return {"success": True, "result": result}
            elif command == "screenshot":
                result = await take_screenshot()
                return {"success": True, "result": result}
            elif command == "sysinfo":
                result = await get_system_info()
                return {"success": True, "result": result}
            elif command == "battery":
                result = await get_battery_status()
                return {"success": True, "result": result}
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
