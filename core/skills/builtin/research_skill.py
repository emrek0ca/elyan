"""Research skill - wraps research and web tools."""

from typing import List, Dict, Any
from core.skills.base import BaseSkill
from core.skills.tool_runtime import execute_registered_tool, wrap_skill_tool_result


class ResearchSkill(BaseSkill):
    @property
    def name(self) -> str:
        return "research"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def description(self) -> str:
        return "Web arastirma, derin analiz ve rapor olusturma"

    @property
    def required_tools(self) -> List[str]:
        return ["web_search", "research"]

    async def setup(self) -> bool:
        return True

    async def execute(self, command: str, context: Dict[str, Any]) -> Dict[str, Any]:
        try:
            params = context.get("params", {})

            if command == "search":
                query = params.get("query", "")
                result = await execute_registered_tool("web_search", {"query": query}, source="builtin_research_skill")
                return wrap_skill_tool_result(result)
            elif command == "deep":
                topic = params.get("topic", "")
                depth = params.get("depth", "medium")
                result = await execute_registered_tool(
                    "advanced_research",
                    {"topic": topic, "depth": depth},
                    source="builtin_research_skill",
                )
                return wrap_skill_tool_result(result)
            elif command == "scrape":
                url = params.get("url", "")
                result = await execute_registered_tool("scrape_page", {"url": url}, source="builtin_research_skill")
                return wrap_skill_tool_result(result)
            else:
                return {"success": False, "error": f"Unknown command: {command}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_commands(self) -> List[Dict[str, Any]]:
        return [
            {"name": "search", "description": "Web'de arama yap", "params": ["query"]},
            {"name": "deep", "description": "Derin arastirma yap", "params": ["topic", "depth"]},
            {"name": "scrape", "description": "Web sayfasi icerigi cikar", "params": ["url"]},
        ]
