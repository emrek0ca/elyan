import asyncio
import json
import uuid
from typing import Any, Dict, List, Optional
from core.runtime.negotiator import capability_negotiator
from core.protocol.shared_types import RunStatus
from core.observability.logger import get_structured_logger

slog = get_structured_logger("execution_hub")

class RemoteExecutionHub:
    """
    Orchestrates the execution of actions across remote nodes.
    Bridges the gap between the Planner and the Node Fabric.
    """
    def __init__(self, gateway_server):
        self.gateway = gateway_server
        self._pending_actions: Dict[str, asyncio.Future] = {}

    async def execute_action(self, tool_name: str, params: Dict[str, Any], session_id: str, run_id: str) -> Dict[str, Any]:
        """
        Negotiates, dispatches, and waits for an action result.
        """
        tool, node = capability_negotiator.negotiate(tool_name)
        
        if not tool:
            return {"status": "error", "error": f"Tool {tool_name} not found"}
        
        if not node:
            return {"status": "error", "error": f"No node available for capability {tool.capability}"}

        action_id = f"act_{uuid.uuid4().hex[:8]}"
        
        # 1. Prepare Action Request
        request = {
            "event_type": "ActionRequest",
            "data": {
                "action_id": action_id,
                "capability": tool.capability,
                "action": tool_name.split(".")[-1],
                "params": params,
                "session_id": session_id,
                "run_id": run_id
            }
        }

        # 2. Find node WebSocket
        ws = self.gateway.connected_nodes.get(node.node_id)
        if not ws:
            return {"status": "error", "error": f"Node {node.node_id} WebSocket not found"}

        # 3. Dispatch and Wait
        future = asyncio.get_event_loop().create_future()
        self._pending_actions[action_id] = future
        
        try:
            await ws.send_str(json.dumps(request))
            slog.log_event("action_dispatched", {"action_id": action_id, "node_id": node.node_id}, session_id=session_id, run_id=run_id)
            
            # Wait for result with timeout
            result = await asyncio.wait_for(future, timeout=60.0)
            return result
        except asyncio.TimeoutError:
            return {"status": "error", "error": "Action timed out"}
        except Exception as e:
            return {"status": "error", "error": str(e)}
        finally:
            self._pending_actions.pop(action_id, None)

    def resolve_action(self, action_id: str, result: Dict[str, Any]):
        """Called when a result is received via WebSocket."""
        future = self._pending_actions.get(action_id)
        if future and not future.done():
            future.set_result(result)

# Note: This will be instantiated by the GatewayServer
