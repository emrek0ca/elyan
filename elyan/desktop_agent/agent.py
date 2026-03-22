import asyncio
import json
import socket
import platform
import time
import uuid
import os
from typing import Dict, Any, List, Optional
import websockets
from utils.logger import get_logger
from core.observability.logger import get_structured_logger

logger = get_logger("desktop_agent")
slog = get_structured_logger("desktop_agent")

class DesktopAgent:
    """
    The local execution authority for Elyan.
    Runs on the user's machine and executes local capabilities.
    """
    def __init__(self, gateway_url: str = "ws://localhost:18789/ws/node"):
        self.gateway_url = gateway_url
        self.node_id = f"node_{socket.gethostname().split('.')[0]}_{uuid.uuid4().hex[:6]}"
        self.is_running = False
        self.capabilities = ["filesystem", "terminal", "screen", "clipboard", "search"]
        self._ws: Optional[websockets.WebSocketClientProtocol] = None

    async def start(self):
        """Starts the desktop agent and connects to the gateway."""
        self.is_running = True
        slog.log_event("agent_starting", {"node_id": self.node_id, "platform": platform.system()})
        
        # Start background indexing of Home directory
        asyncio.create_task(self._initial_indexing())
        
        while self.is_running:
            try:
                async with websockets.connect(self.gateway_url) as ws:
                    self._ws = ws
                    await self._register_node()
                    
                    # Start heartbeat task
                    heartbeat_task = asyncio.create_task(self._heartbeat_loop())
                    
                    try:
                        await self._listen_for_actions()
                    finally:
                        heartbeat_task.cancel()
                        
            except Exception as e:
                logger.warning(f"Connection failed: {e}. Retrying in 5 seconds...")
                await asyncio.sleep(5)

    async def _heartbeat_loop(self):
        """Periodically sends health updates to the gateway."""
        import psutil
        while self.is_running:
            try:
                health_data = {
                    "event_type": "NodeHealthUpdated",
                    "data": {
                        "node_id": self.node_id,
                        "status": "healthy",
                        "cpu_usage": psutil.cpu_percent(),
                        "memory_usage": psutil.virtual_memory().percent,
                        "timestamp": time.time()
                    }
                }
                await self._ws.send(json.dumps(health_data))
            except Exception as e:
                logger.debug(f"Heartbeat failed: {e}")
            await asyncio.sleep(30)

    async def _initial_indexing(self):
        """Indexes the home directory in the background."""
        from elyan.desktop_agent.indexer import file_indexer
        # Run in executor to not block the event loop
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(None, file_indexer.index_path, "~")
        except Exception as e:
            logger.error(f"Initial indexing failed: {e}")

    async def stop(self):
        self.is_running = False
        if self._ws:
            await self._ws.close()
        slog.log_event("agent_stopped", {"node_id": self.node_id})

    async def _register_node(self):
        """Registers this node and its capabilities with the gateway."""
        registration = {
            "event_type": "NodeRegistered",
            "data": {
                "node_id": self.node_id,
                "node_type": "desktop",
                "capabilities": self.capabilities,
                "hostname": socket.gethostname(),
                "platform": platform.system(),
                "os_version": platform.version()
            }
        }
        await self._ws.send(json.dumps(registration))
        logger.info(f"Node registered: {self.node_id}")

    async def _listen_for_actions(self):
        """Listens for action requests from the gateway."""
        async for message in self._ws:
            try:
                event = json.loads(message)
                await self._handle_event(event)
            except Exception as e:
                logger.error(f"Error handling event: {e}")

    async def _handle_event(self, event: Dict[str, Any]):
        event_type = event.get("event_type")
        if event_type == "ActionRequest":
            await self._execute_action(event.get("data", {}))
        elif event_type == "Ping":
            await self._ws.send(json.dumps({"event_type": "Pong", "timestamp": time.time()}))

    async def _execute_action(self, data: Dict[str, Any]):
        """Executes a capability action."""
        action_id = data.get("action_id")
        capability = data.get("capability")
        action = data.get("action")
        params = data.get("params", {})

        slog.log_event("action_received", {"action_id": action_id, "capability": capability, "action": action})

        result_data = {"status": "error", "error": "Unknown capability"}
        
        try:
            if capability == "filesystem":
                from core.capabilities.filesystem import filesystem_capability
                if action == "list_directory":
                    result_data = await filesystem_capability.list_directory(**params)
                elif action == "read_file":
                    result_data = await filesystem_capability.read_file(**params)
                elif action == "write_file":
                    result_data = await filesystem_capability.write_file(**params)
                elif action == "trash_file":
                    result_data = await filesystem_capability.trash_file(**params)
                elif action == "search":
                    from elyan.desktop_agent.indexer import file_indexer
                    result_data = {"items": file_indexer.search(**params)}
                else:
                    result_data = {"status": "error", "error": f"Unknown action: {action}"}
            
            elif capability == "terminal":
                from core.capabilities.terminal import terminal_capability
                if action == "execute":
                    result_data = await terminal_capability.execute(**params)
                else:
                    result_data = {"status": "error", "error": f"Unknown action: {action}"}
            
            if "status" not in result_data:
                result_data["status"] = "success"
                
        except Exception as e:
            logger.error(f"Action execution failed: {e}")
            result_data = {"status": "error", "error": str(e)}
        
        result = {
            "event_type": "ActionResult",
            "data": {
                "action_id": action_id,
                **result_data
            }
        }
        await self._ws.send(json.dumps(result))

if __name__ == "__main__":
    agent = DesktopAgent()
    try:
        asyncio.run(agent.start())
    except KeyboardInterrupt:
        asyncio.run(agent.stop())
