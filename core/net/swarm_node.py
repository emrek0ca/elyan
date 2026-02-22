"""
core/net/swarm_node.py
─────────────────────────────────────────────────────────────────────────────
Distributed Swarm Node Daemon.
Runs on remote devices (VPS, secondary laptops, etc.) to form a Cluster.
Accepts authenticated JWT payloads from the Master Orchestrator, executes 
tools locally, and returns the artifacts through WebSockets.
"""

import asyncio
import json
import jwt
from typing import Dict, Any, Optional
from utils.logger import get_logger

logger = get_logger("swarm_node")

# A mock secret for demonstration. In production, load from ENV.
SWARM_SECRET = "elyan-hyper-swarm-secret-key-2026"

class SwarmNode:
    def __init__(self, agent_instance, host: str = "0.0.0.0", port: int = 8765):
        self.agent = agent_instance
        self.host = host
        self.port = port
        self.server = None
        self._running = False
        
    def _verify_auth(self, token: str) -> bool:
        """Verify the payload signature to prevent unauthorized executions."""
        try:
            jwt.decode(token, SWARM_SECRET, algorithms=["HS256"])
            return True
        except jwt.InvalidTokenError:
            logger.warning("Swarm Node rejected unauthorized connection.")
            return False

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        addr = writer.get_extra_info('peername')
        logger.info(f"🌐 Swarm Node connection established from {addr}")
        
        try:
            data = await reader.read(4096)
            if not data:
                return
                
            payload = json.loads(data.decode('utf-8'))
            token = payload.get("auth_token", "")
            
            if not self._verify_auth(token):
                writer.write(json.dumps({"error": "Unauthorized"}).encode())
                await writer.drain()
                return
                
            intent = payload.get("intent", "")
            logger.info(f"👽 Remote Swarm Execution Triggered: {intent}")
            
            # Route and execute locally on this node
            from core.multi_agent.neural_router import NeuralRouter
            from core.multi_agent.orchestrator import AgentOrchestrator
            
            router = NeuralRouter(self.agent)
            template = await router.route_request(intent)
            orch = AgentOrchestrator(self.agent)
            
            result = await orch.manage_flow(template, intent)
            
            response = {"status": "success", "result": result}
            writer.write(json.dumps(response).encode())
            await writer.drain()
            
        except ConnectionResetError:
            pass
        except Exception as e:
            logger.error(f"Swarm Node Error: {e}")
            writer.write(json.dumps({"status": "fail", "error": str(e)}).encode())
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()
            
    async def start(self):
        """Starts the TCP server socket."""
        self.server = await asyncio.start_server(
            self._handle_client, self.host, self.port
        )
        self._running = True
        logger.info(f"🔗 Swarm Node listening on {self.host}:{self.port}")
        
        async with self.server:
            await self.server.serve_forever()
            
    def stop(self):
        if self.server:
            self.server.close()
        self._running = False
        logger.info("🛑 Swarm Node offline.")
