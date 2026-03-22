import time
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from core.protocol.shared_types import HealthStatus, NodeType
from core.observability.logger import get_structured_logger

slog = get_structured_logger("node_manager")

class NodeInfo(BaseModel):
    node_id: str
    node_type: NodeType
    capabilities: List[str]
    hostname: str
    platform: str
    status: HealthStatus = HealthStatus.HEALTHY
    last_seen: float = Field(default_factory=time.time)
    metadata: Dict[str, Any] = Field(default_factory=dict)

class NodeManager:
    """
    Registry and health tracker for all execution nodes (Desktop, VPS, etc.)
    """
    def __init__(self):
        self._nodes: Dict[str, NodeInfo] = {}

    def register_node(self, info: NodeInfo):
        self._nodes[info.node_id] = info
        slog.log_event("node_registered", info.model_dump())

    def update_health(self, node_id: str, status: HealthStatus):
        if node_id in self._nodes:
            self._nodes[node_id].status = status
            self._nodes[node_id].last_seen = time.time()
            slog.log_event("node_health_updated", {"node_id": node_id, "status": status.value})

    def list_nodes(self, capability: Optional[str] = None) -> List[NodeInfo]:
        if capability:
            return [n for n in self._nodes.values() if capability in n.capabilities]
        return list(self._nodes.values())

    def get_best_node_for(self, capability: str) -> Optional[NodeInfo]:
        """Finds the healthiest node that supports the required capability."""
        eligible = self.list_nodes(capability)
        # Filter for healthy ones
        healthy = [n for n in eligible if n.status == HealthStatus.HEALTHY]
        if not healthy:
            return None
        # Simple heuristic: most recently seen
        return sorted(healthy, key=lambda x: x.last_seen, reverse=True)[0]

# Global instance
node_manager = NodeManager()
