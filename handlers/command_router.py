from typing import Any
from tools import AVAILABLE_TOOLS
from utils.logger import get_logger

logger = get_logger("command_router")

class CommandRouter:
    def __init__(self):
        self.tools = AVAILABLE_TOOLS

    def get_available_tools(self) -> list[str]:
        return list(self.tools.keys())

    def has_tool(self, tool_name: str) -> bool:
        return tool_name in self.tools

    def get_tool(self, tool_name: str):
        return self.tools.get(tool_name)

    def parse_quick_command(self, text: str) -> dict[str, Any] | None:
        text = text.strip().lower()

        if text in ["sistem", "sistem bilgisi", "system", "info"]:
            return {"tool": "get_system_info", "params": {}}

        if text.startswith("listele ") or text.startswith("ls "):
            path = text.split(" ", 1)[1].strip()
            return {"tool": "list_files", "params": {"path": path}}

        if text in ["listele", "ls", "dosyalar"]:
            return {"tool": "list_files", "params": {"path": "."}}

        if text.startswith("oku ") or text.startswith("read "):
            path = text.split(" ", 1)[1].strip()
            return {"tool": "read_file", "params": {"path": path}}

        if text.startswith("ara ") or text.startswith("search "):
            pattern = text.split(" ", 1)[1].strip()
            return {"tool": "search_files", "params": {"pattern": pattern, "directory": "."}}

        if text.startswith("çalıştır ") or text.startswith("run "):
            command = text.split(" ", 1)[1].strip()
            return {"tool": "run_command", "params": {"command": command}}

        return None
