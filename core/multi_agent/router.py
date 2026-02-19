from typing import Dict, List, Any
from config.elyan_config import elyan_config
from .pool import agent_pool
from utils.logger import get_logger

logger = get_logger("agent_router")

class AgentRouter:
    """Decides which agent handles a specific message based on channel or user rules."""
    
    def __init__(self):
        self.routes: Dict[str, str] = {} # channel_type -> agent_id
        self.user_routes: Dict[str, str] = {} # user_id -> agent_id

    def build_routes(self):
        """Build routing map from config."""
        config_agents = elyan_config.get("agents", [])
        for ag in config_agents:
            aid = ag.get("id")
            for channel in ag.get("routes", []):
                self.routes[channel] = aid
            for user in ag.get("user_routes", []):
                self.user_routes[str(user)] = aid
        
        logger.info(f"Routing table built: {len(self.routes)} channels, {len(self.user_routes)} users.")

    async def route_message(self, channel_type: str, user_id: str):
        """Determine the correct agent_id for the given context."""
        # 1. User specific route wins
        if user_id in self.user_routes:
            return await agent_pool.get_agent(self.user_routes[user_id])
            
        # 2. Channel specific route
        if channel_type in self.routes:
            return await agent_pool.get_agent(self.routes[channel_type])
            
        # 3. Fallback to default
        return await agent_pool.get_agent("default")

# Global instance
agent_router = AgentRouter()
