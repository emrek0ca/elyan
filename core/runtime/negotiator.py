from typing import Any, Dict, List, Optional, Tuple
from core.runtime.tool_registry import tool_registry, ToolDefinition
from core.runtime.node_manager import node_manager, NodeInfo
from core.observability.logger import get_structured_logger

slog = get_structured_logger("capability_negotiator")

class CapabilityNegotiator:
    """
    Matches requested tools to the best available execution node.
    Handles the "Where does this run?" logic.
    """
    def negotiate(self, tool_name: str) -> Tuple[Optional[ToolDefinition], Optional[NodeInfo]]:
        """
        Finds the tool definition and the best node to execute it.
        """
        tool = tool_registry.get_tool(tool_name)
        if not tool:
            slog.log_event("negotiation_failed", {"tool_name": tool_name, "reason": "tool_not_found"}, level="warning")
            return None, None

        node = node_manager.get_best_node_for(tool.capability)
        if not node:
            slog.log_event("negotiation_failed", {
                "tool_name": tool_name, 
                "capability": tool.capability,
                "reason": "no_eligible_node"
            }, level="warning")
            return tool, None

        slog.log_event("negotiation_success", {
            "tool_name": tool_name,
            "node_id": node.node_id,
            "capability": tool.capability
        })
        
        return tool, node

# Global instance
capability_negotiator = CapabilityNegotiator()
