"""
core/ux_engine — Premium UX Layer
Conversational flow, real-time streaming, proactive suggestions, context continuity, multi-modal input.
"""

from __future__ import annotations

from .engine import UXEngine
from .engine import ConversationProfile, DeliveryPlan, UXResult
from .conversation_flow import ConversationFlowManager
from .suggestion_engine import SuggestionEngine
from .context_continuity import ContextContinuityTracker

_ux_engine: UXEngine | None = None


def get_ux_engine() -> UXEngine:
    """Singleton: get or create UXEngine."""
    global _ux_engine
    if _ux_engine is None:
        _ux_engine = UXEngine()
    return _ux_engine


__all__ = [
    "UXEngine",
    "UXResult",
    "ConversationProfile",
    "DeliveryPlan",
    "ConversationFlowManager",
    "SuggestionEngine",
    "ContextContinuityTracker",
    "get_ux_engine",
]
