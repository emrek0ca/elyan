"""
core/genesis/context_fusion.py
─────────────────────────────────────────────────────────────────────────────
Context Fusion Engine (Phase 29).
Merges all awareness streams (BioSymbiosis, PreemptiveSubconscious, OmniChannel)
into a single, unified "Consciousness" object that gives the Orchestrator a 
360-degree real-time understanding of the user's world.
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from utils.logger import get_logger

logger = get_logger("context_fusion")

@dataclass
class ConsciousnessState:
    """The unified awareness snapshot available to the Orchestrator at any moment."""
    timestamp: float = field(default_factory=time.time)
    
    # From BioSymbiosis (Phase 19)
    active_app: str = ""
    active_window: str = ""
    
    # From PreemptiveSubconscious (Phase 24)
    unread_emails: int = 0
    pending_actions: List[str] = field(default_factory=list)
    
    # From OmniChannel (Phase 22)
    active_platforms: List[str] = field(default_factory=list)
    last_platform_message: Dict[str, str] = field(default_factory=dict)
    
    # Derived Metrics
    user_focus_score: float = 0.0  # 0-1, how focused the user appears
    urgency_level: str = "normal"  # low, normal, high, critical

class ContextFusionEngine:
    def __init__(self, agent_instance):
        self.agent = agent_instance
        self.state = ConsciousnessState()
        self._running = False
        
    async def _poll_bio_symbiosis(self):
        try:
            from core.os_adapters.window_manager import get_active_window_context
            ctx = get_active_window_context()
            self.state.active_app = ctx.get("app", "")
            self.state.active_window = ctx.get("title", "")
        except:
            pass
    
    async def _poll_preemptive(self):
        try:
            from core.genesis.preemptive_subconscious import PreemptiveSubconscious
            ps = PreemptiveSubconscious(self.agent)
            emails = ps._read_unread_mac_mail()
            self.state.unread_emails = len(emails)
        except:
            pass
    
    async def _derive_focus_score(self):
        """Heuristic: if the user is in a code editor, focus is high. If in social media, low."""
        high_focus_apps = {"code", "cursor", "xcode", "intellij", "pycharm", "vim", "terminal", "iterm"}
        low_focus_apps = {"twitter", "instagram", "tiktok", "youtube", "safari", "chrome"}
        
        app_lower = self.state.active_app.lower()
        if any(a in app_lower for a in high_focus_apps):
            self.state.user_focus_score = 0.9
            self.state.urgency_level = "low"  # Don't interrupt focused work
        elif any(a in app_lower for a in low_focus_apps):
            self.state.user_focus_score = 0.3
            self.state.urgency_level = "normal"
        else:
            self.state.user_focus_score = 0.5
            
        if self.state.unread_emails > 5:
            self.state.urgency_level = "high"

    async def _fusion_loop(self):
        self._running = True
        logger.info("🧠 ContextFusion Engine Online — Merging Awareness Streams...")
        
        while self._running:
            await self._poll_bio_symbiosis()
            await self._poll_preemptive()
            await self._derive_focus_score()
            self.state.timestamp = time.time()
            
            logger.debug(
                f"🌐 Fusion State: App={self.state.active_app}, "
                f"Focus={self.state.user_focus_score:.1f}, "
                f"Urgency={self.state.urgency_level}, "
                f"Emails={self.state.unread_emails}"
            )
            await asyncio.sleep(10.0)
    
    def get_consciousness(self) -> ConsciousnessState:
        return self.state
        
    def start(self):
        if not self._running:
            asyncio.create_task(self._fusion_loop())
            
    def stop(self):
        self._running = False
