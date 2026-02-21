import asyncio
from typing import Dict, Any, Optional
from pathlib import Path
from core.agent import Agent
from config.elyan_config import elyan_config
from utils.logger import get_logger

logger = get_logger("agent_pool")

class AgentPool:
    """Manages multiple named Agent instances with isolated environments."""
    
    def __init__(self):
        self.agents: Dict[str, Agent] = {}
        self.base_dir = Path.home() / ".elyan" / "agents"
        self.base_dir.mkdir(parents=True, exist_ok=True)

    async def get_agent(self, agent_id: str = "default") -> Agent:
        """Get an existing agent or create a new one."""
        if agent_id in self.agents:
            return self.agents[agent_id]

        logger.info(f"Initializing new agent instance: {agent_id}")
        
        # Isolation: Set custom home/workspace for this instance
        # Note: In a production version, we would inject these paths into Agent.__init__
        agent = Agent()
        
        # Future: inject workspace-specific paths
        # agent.set_workspace(self.base_dir / agent_id)
        
        await agent.initialize()
        self.agents[agent_id] = agent
        return agent

    async def shutdown_all(self):
        for aid, agent in self.agents.items():
            logger.info(f"Shutting down agent: {aid}")
            await agent.shutdown()
        self.agents.clear()

# Global instance
agent_pool = AgentPool()
