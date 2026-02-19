"""Files skill - wraps file_tools for file operations."""

from typing import List, Dict, Any
from core.skills.base import BaseSkill


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
            from tools.file_tools import (
                read_file, write_file, list_files, search_files,
                create_directory, delete_file,
            )
            params = context.get("params", {})

            if command == "read":
                path = params.get("path", "")
                result = await read_file(path)
                return {"success": True, "result": result}
            elif command == "write":
                path = params.get("path", "")
                content = params.get("content", "")
                result = await write_file(path, content)
                return {"success": True, "result": result}
            elif command == "list":
                path = params.get("path", "~/Desktop")
                result = await list_files(path)
                return {"success": True, "result": result}
            elif command == "search":
                query = params.get("query", "")
                path = params.get("path", "~")
                result = await search_files(query, path)
                return {"success": True, "result": result}
            elif command == "mkdir":
                path = params.get("path", "")
                result = await create_directory(path)
                return {"success": True, "result": result}
            elif command == "delete":
                path = params.get("path", "")
                result = await delete_file(path)
                return {"success": True, "result": result}
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
