"""Office skill - wraps document and office tools."""

from typing import List, Dict, Any
from core.skills.base import BaseSkill


class OfficeSkill(BaseSkill):
    @property
    def name(self) -> str:
        return "office"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def description(self) -> str:
        return "Excel, PDF ve belge isleme araclari"

    @property
    def required_tools(self) -> List[str]:
        return ["create_excel", "create_pdf"]

    async def setup(self) -> bool:
        return True

    async def execute(self, command: str, context: Dict[str, Any]) -> Dict[str, Any]:
        try:
            params = context.get("params", {})

            if command == "excel":
                from tools.office_tools.excel_tools import create_excel
                data = params.get("data", {})
                path = params.get("path", "")
                result = await create_excel(data, path)
                return {"success": True, "result": result}
            elif command == "pdf":
                from tools.office_tools.pdf_tools import create_pdf
                content = params.get("content", "")
                path = params.get("path", "")
                result = await create_pdf(content, path)
                return {"success": True, "result": result}
            else:
                return {"success": False, "error": f"Unknown command: {command}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_commands(self) -> List[Dict[str, Any]]:
        return [
            {"name": "excel", "description": "Excel dosyasi olustur", "params": ["data", "path"]},
            {"name": "pdf", "description": "PDF olustur", "params": ["content", "path"]},
        ]
