from typing import Callable, Dict, Any, Optional
from dataclasses import dataclass
import inspect
from utils.logger import get_logger

logger = get_logger("registry")

@dataclass
class ToolDefinition:
    name: str
    description: str
    func: Callable
    parameters: Dict[str, Any]
    requires_approval: bool = False

class ToolRegistry:
    """Central repository for all agent capabilities."""
    
    def __init__(self):
        self._tools: Dict[str, ToolDefinition] = {}

    def register(self, name: str, description: str = "", approval: bool = False):
        """Decorator to register a function as a tool."""
        def decorator(func: Callable):
            sig = inspect.signature(func)
            params = {
                k: str(v.annotation) if v.annotation != inspect.Parameter.empty else "Any"
                for k, v in sig.parameters.items()
            }
            
            tool_def = ToolDefinition(
                name=name,
                description=description or func.__doc__ or "",
                func=func,
                parameters=params,
                requires_approval=approval
            )
            self._tools[name] = tool_def
            return func
        return decorator

    def get_tool(self, name: str) -> Optional[ToolDefinition]:
        return self._tools.get(name)

    def list_tools(self) -> Dict[str, str]:
        return {name: t.description for name, t in self._tools.items()}

    async def execute(self, tool_name: str, params: Dict[str, Any]) -> Any:
        tool = self.get_tool(tool_name)
        if not tool:
            raise ValueError(f"Tool not found: {tool_name}")
        
        # Here we could add parameter validation based on type hints
        try:
            # Check if function is async
            if inspect.iscoroutinefunction(tool.func):
                return await tool.func(**params)
            else:
                return tool.func(**params)
        except TypeError as e:
            raise ValueError(f"Invalid parameters for {tool_name}: {e}")
        except Exception as e:
            logger.error(f"Tool Execution Error ({tool_name}): {e}")
            raise

# Global Instance
registry = ToolRegistry()
# Alias for decorator
tool = registry.register
