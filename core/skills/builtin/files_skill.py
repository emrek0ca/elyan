"""Files skill - wraps file_tools for file operations."""

from typing import List, Dict, Any
from core.skills.base import BaseSkill
from core.skills.tool_runtime import execute_registered_tool, wrap_skill_tool_result


class FilesSkill(BaseSkill):
    @property
    def name(self) -> str:
        return "files"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def description(self) -> str:
        return "Dosya okuma, yazma, arama ve duzenleme islemleri"

    @property
    def required_tools(self) -> List[str]:
        return ["read_file", "write_file", "list_files", "search_files"]

    async def setup(self) -> bool:
        return True

    async def execute(self, command: str, context: Dict[str, Any]) -> Dict[str, Any]:
        try:
            params = context.get("params", {})

            if command == "read":
                path = params.get("path", "")
                result = await execute_registered_tool("read_file", {"path": path}, source="builtin_files_skill")
                return wrap_skill_tool_result(result)
            elif command == "write":
                path = params.get("path", "")
                content = params.get("content", "")
                result = await execute_registered_tool("write_file", {"path": path, "content": content}, source="builtin_files_skill")
                return wrap_skill_tool_result(result)
            elif command == "list":
                path = params.get("path", "~/Desktop")
                result = await execute_registered_tool("list_files", {"path": path}, source="builtin_files_skill")
                return wrap_skill_tool_result(result)
            elif command == "search":
                query = params.get("query", "")
                path = params.get("path", "~")
                result = await execute_registered_tool("search_files", {"pattern": query, "directory": path}, source="builtin_files_skill")
                return wrap_skill_tool_result(result)
            elif command == "mkdir":
                path = params.get("path", "")
                result = await execute_registered_tool("create_folder", {"path": path}, source="builtin_files_skill")
                return wrap_skill_tool_result(result)
            elif command == "delete":
                path = params.get("path", "")
                result = await execute_registered_tool("delete_file", {"path": path}, source="builtin_files_skill")
                return wrap_skill_tool_result(result)
            else:
                return {"success": False, "error": f"Unknown command: {command}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_commands(self) -> List[Dict[str, Any]]:
        return [
            {"name": "read", "description": "Dosya oku", "params": ["path"]},
            {"name": "write", "description": "Dosya yaz", "params": ["path", "content"]},
            {"name": "list", "description": "Dosyalari listele", "params": ["path"]},
            {"name": "search", "description": "Dosya ara", "params": ["query", "path"]},
            {"name": "mkdir", "description": "Klasor olustur", "params": ["path"]},
            {"name": "delete", "description": "Dosya sil", "params": ["path"]},
        ]
