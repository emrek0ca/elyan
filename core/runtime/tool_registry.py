from typing import Any, Dict, List, Optional, Callable
from pydantic import BaseModel, Field
from core.protocol.shared_types import RiskLevel
from core.observability.logger import get_structured_logger

slog = get_structured_logger("tool_registry")

class ToolDefinition(BaseModel):
    name: str
    capability: str
    description: str
    input_schema: Dict[str, Any]
    output_schema: Dict[str, Any]
    risk_level: RiskLevel = RiskLevel.READ_ONLY

class ToolRegistry:
    """
    Central registry for all executable tools in Elyan v2.
    Decouples tool definitions from their node-specific implementations.
    """
    def __init__(self):
        self._tools: Dict[str, ToolDefinition] = {}

    def register_tool(self, tool: ToolDefinition):
        self._tools[tool.name] = tool
        slog.log_event("tool_registered", {"name": tool.name, "capability": tool.capability})

    def get_tool(self, name: str) -> Optional[ToolDefinition]:
        return self._tools.get(name)

    def list_tools(self, capability: Optional[str] = None) -> List[ToolDefinition]:
        if capability:
            return [t for t in self._tools.values() if t.capability == capability]
        return list(self._tools.values())

# Global instance
tool_registry = ToolRegistry()

# Initialize with core tools
def _init_core_tools():
    core_tools = [
        ToolDefinition(
            name="filesystem.list_directory",
            capability="filesystem",
            description="Lists items in a directory",
            input_schema={"path": {"type": "string"}},
            output_schema={"items": {"type": "array"}}
        ),
        ToolDefinition(
            name="filesystem.read_file",
            capability="filesystem",
            description="Reads content of a file",
            input_schema={"path": {"type": "string"}},
            output_schema={"content": {"type": "string"}}
        ),
        ToolDefinition(
            name="filesystem.write_file",
            capability="filesystem",
            description="Writes content to a file",
            input_schema={"path": {"type": "string"}, "content": {"type": "string"}},
            output_schema={"status": {"type": "string"}},
            risk_level=RiskLevel.WRITE_SAFE
        ),
        ToolDefinition(
            name="terminal.execute",
            capability="terminal",
            description="Executes a shell command",
            input_schema={"command": {"type": "string"}, "cwd": {"type": "string", "optional": True}},
            output_schema={"stdout": {"type": "string"}, "stderr": {"type": "string"}, "exit_code": {"type": "integer"}},
            risk_level=RiskLevel.WRITE_SENSITIVE
        )
    ]
    for tool in core_tools:
        tool_registry.register_tool(tool)

_init_core_tools()
