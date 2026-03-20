"""Office skill - wraps document and office tools."""

from typing import List, Dict, Any
from core.skills.base import BaseSkill
from core.compat.legacy_tool_wrappers import normalize_legacy_tool_payload
from core.skills.tool_runtime import execute_registered_tool, wrap_skill_tool_result


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
                data = params.get("data", {})
                path = params.get("path", "")
                result = await execute_registered_tool(
                    "write_excel",
                    {"path": path, "data": data},
                    source="builtin_office_skill",
                    skill_name=self.name,
                )
                return wrap_skill_tool_result(result)
            elif command == "pdf":
                path = params.get("path", "")
                result = normalize_legacy_tool_payload(
                    {
                        "success": False,
                        "status": "failed",
                        "error": "Tool not found: create_pdf",
                        "errors": ["UNKNOWN_TOOL"],
                        "data": {"error_code": "UNKNOWN_TOOL", "requested_path": path},
                    },
                    tool="create_pdf",
                    source="builtin_office_skill",
                )
                return wrap_skill_tool_result(result)
            else:
                return {"success": False, "error": f"Unknown command: {command}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_commands(self) -> List[Dict[str, Any]]:
        return [
            {"name": "excel", "description": "Excel dosyasi olustur", "params": ["data", "path"]},
            {"name": "pdf", "description": "PDF olustur", "params": ["content", "path"]},
        ]
