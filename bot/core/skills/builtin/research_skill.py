"""Research skill - wraps research and web tools."""

from typing import List, Dict, Any
from core.skills.base import BaseSkill


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
                from tools.web_tools.search_engine import web_search
                query = params.get("query", "")
                result = await web_search(query)
                return {"success": True, "result": result}
            elif command == "deep":
                from tools.research_tools.advanced_research import advanced_research
                topic = params.get("topic", "")
                depth = params.get("depth", "medium")
                result = await advanced_research(topic, depth=depth)
                return {"success": True, "result": result}
            elif command == "scrape":
                from tools.web_tools.web_scraper import scrape_url
                url = params.get("url", "")
                result = await scrape_url(url)
                return {"success": True, "result": result}
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
