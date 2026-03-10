"""Browser skill - wraps browser automation tools."""

from typing import List, Dict, Any
from core.skills.base import BaseSkill
from core.skills.tool_runtime import execute_registered_tool, wrap_skill_tool_result


class BrowserSkill(BaseSkill):
    @property
    def name(self) -> str:
        return "browser"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def description(self) -> str:
        return "Web tarayici otomasyonu, sayfa gezinme ve veri cikarma"

    @property
    def required_tools(self) -> List[str]:
        return ["open_url", "browser_screenshot"]

    async def setup(self) -> bool:
        return True

    async def execute(self, command: str, context: Dict[str, Any]) -> Dict[str, Any]:
        try:
            params = context.get("params", {})

            if command == "navigate":
                url = params.get("url", "")
                result = await execute_registered_tool("open_url", {"url": url}, source="builtin_browser_skill")
                return wrap_skill_tool_result(result)
            elif command == "screenshot":
                result = await execute_registered_tool("browser_screenshot", {}, source="builtin_browser_skill")
                return wrap_skill_tool_result(result)
            else:
                return {"success": False, "error": f"Unknown command: {command}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_commands(self) -> List[Dict[str, Any]]:
        return [
            {"name": "navigate", "description": "URL'ye git", "params": ["url"]},
            {"name": "screenshot", "description": "Tarayici ekran goruntusu", "params": []},
        ]
