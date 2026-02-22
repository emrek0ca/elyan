"""
core/net/abstract_gateway.py
─────────────────────────────────────────────────────────────────────────────
Omni-Channel Abstract Ingress (Singularity 2.0).
Provides a unified interface (WhatsApp, Telegram, Discord, Slack) to the 
Elyan Neural Router. This ensures the agent perfectly shares context across 
platforms. E.g., You send a dataset on Telegram, and ask Elyan on WhatsApp
to analyze it 3 hours later.
"""

import asyncio
from typing import Dict, Any, Callable
from utils.logger import get_logger

logger = get_logger("abstract_gateway")

class OmniContext:
    def __init__(self, platform: str, user_id: str, message: str, meta: Dict = None):
        self.platform = platform
        self.user_id = user_id     # Must be normalized mapped to a single "Elyan Owner ID"
        self.message = message
        self.meta = meta or {}

class OmniChannelGateway:
    def __init__(self, agent_instance):
        self.agent = agent_instance
        self.registered_platforms = ["telegram", "discord", "slack", "whatsapp"]
        self.callbacks = {}

    def bind_platform(self, platform_name: str, callback: Callable):
        """Binds a specific messaging SDK webhook router to this Singleton Ingress."""
        if platform_name not in self.registered_platforms:
            self.registered_platforms.append(platform_name)
        self.callbacks[platform_name] = callback
        logger.info(f"🌐 [Omni-Channel] Successfully bound ingress for: {platform_name.upper()}")

    async def _normalize_user(self, platform: str, raw_user_id: str) -> str:
        """
        Critical piece matching cross-platform IDs (Slack ID vs Telegram ID)
        to the universal semantic vault ID in `MemoryDB`.
        """
        # In a real deployed DB, map cross-app tokens. Defaulting to Singleton Owner for MVP.
        return "ELYAN_GLOBAL_OWNER"

    async def ingest_message(self, platform: str, raw_user_id: str, message: str, attachments: list = None) -> str:
        """
        The Universal Entrypoint for all external text spanning the universe.
        Applies prompt injection defense (Phase 25 placeholder) and routes to Orchestrator.
        """
        global_user = await self._normalize_user(platform, raw_user_id)
        context = OmniContext(platform, global_user, message, meta={"attachments": attachments})
        
        logger.info(f"📥 [OMNI-IN] ({platform.upper()}) User {raw_user_id}: {message[:50]}...")
        
        # 1. Thread context parsing
        # (Elyan pulls the last 5 memory segments for 'global_user' regardless of what platform they came from)
        
        # 2. Sentience Routing
        try:
            from core.multi_agent.neural_router import NeuralRouter
            from core.multi_agent.orchestrator import AgentOrchestrator
            
            router = NeuralRouter(self.agent)
            
            # Injecting cross-platform awareness
            intent_with_context = f"[Gelen Platform: {platform}] {message}"
            template = await router.route_request(intent_with_context)
            
            orchestrator = AgentOrchestrator(self.agent)
            response = await orchestrator.manage_flow(template, intent_with_context)
            
            # 3. Native Callback Dispatch (e.g. answering on Slack if request came from Slack)
            if platform in self.callbacks:
                await self.callbacks[platform](raw_user_id, response)
                
            return response
            
        except Exception as e:
            err = f"Omni-Channel Routing Error: {str(e)}"
            logger.error(err)
            if platform in self.callbacks:
                await self.callbacks[platform](raw_user_id, err)
            return err

omni_gateway = None

def get_omni_gateway(agent) -> OmniChannelGateway:
    global omni_gateway
    if not omni_gateway:
        omni_gateway = OmniChannelGateway(agent)
    return omni_gateway
