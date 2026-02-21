from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional

class BaseSkill(ABC):
    """Abstract base class for all Elyan skills."""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.is_enabled = True

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier for the skill (e.g., 'system_core')."""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Human readable description of what the skill does."""
        pass

    @property
    def version(self) -> str:
        return "1.0.0"

    @abstractmethod
    async def setup(self) -> bool:
        """Initialization logic (e.g., checking API keys, starting services)."""
        pass

    @abstractmethod
    async def shutdown(self):
        """Cleanup logic when skill is disabled or agent stops."""
        pass

    @abstractmethod
    def get_tools(self) -> List[Dict[str, Any]]:
        """Return a list of tool definitions provided by this skill."""
        pass

    @abstractmethod
    async def execute_tool(self, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Entry point for tool execution."""
        pass
