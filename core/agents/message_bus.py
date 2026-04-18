from __future__ import annotations

from core.multi_agent.message_bus import AgentMessage, AgentMessageBus, MessageHandler, get_message_bus


def get_agent_bus() -> AgentMessageBus:
    """Compatibility alias for the canonical message bus singleton."""
    return get_message_bus()


__all__ = [
    "AgentMessage",
    "AgentMessageBus",
    "MessageHandler",
    "get_agent_bus",
    "get_message_bus",
]
