"""
core/reasoning/trace_logger.py
─────────────────────────────────────────────────────────────────────────────
Captures and broadcasts reasoning traces (<thought> blocks) to the dashboard.
Provides transparency into the Multi-LLM orchestration process.
"""

import re
from typing import Optional, Dict, Any
from utils.logger import get_logger

logger = get_logger("trace_logger")

class TraceLogger:
    """
    Collects thought process blocks and pushes them to telemetry.
    """
    
    def extract_thought(self, raw_text: str) -> Optional[str]:
        """Extracts content within <thought> tags."""
        match = re.search(r"<thought>(.*?)</thought>", raw_text, re.DOTALL)
        if match:
            return match.group(1).strip()
        return None

    def push_trace(self, agent_name: str, thought: str, model_info: Optional[str] = None):
        """
        Broadcasts a reasoning trace to the dashboard.
        """
        if not thought:
            return
            
        clean_thought = thought[:1000] # Limit for UI
        trace_id = f"trace_{id(thought)}"
        
        logger.info(f"🧠 [Trace] {agent_name}: {thought[:100]}...")
        
        try:
            from core.gateway.server import broadcast_to_dashboard
            event_data = {
                "type": "reasoning_trace",
                "agent": agent_name,
                "model": model_info or "unknown",
                "content": clean_thought,
                "timestamp": __import__("time").time()
            }
            # Also push as a hint for immediate visibility
            from core.gateway.server import push_hint
            push_hint(f"{agent_name}: {clean_thought[:120]}...", icon="brain", color="purple")
            
            # Broadcast the full trace event
            broadcast_to_dashboard("telemetry", {"trace": event_data})
        except Exception as e:
            logger.debug(f"Failed to push trace to dashboard: {e}")

# Global instance
trace_logger = TraceLogger()
