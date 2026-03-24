"""Computer Use Router — Integrates Computer Use Tool with main agent router

Provides router middleware for detecting and routing computer_use actions.
"""

from typing import Optional, Dict, Any
from core.observability.logger import get_structured_logger

slog = get_structured_logger("computer_use_router")


class ComputerUseRouter:
    """Router for Computer Use actions"""

    # Action types that trigger Computer Use Tool
    COMPUTER_USE_ACTIONS = {
        "computer_use",
        "screen_control",
        "ui_automation",
        "visual_task",
        "use_computer"
    }

    @classmethod
    def should_route_to_computer_use(cls, action_type: Optional[str]) -> bool:
        """
        Determine if action should be routed to Computer Use Tool

        Args:
            action_type: Action type from LLM or intent parser

        Returns:
            True if action should be routed to Computer Use Tool
        """
        if not action_type:
            return False

        action_lower = action_type.lower().strip()
        return action_lower in cls.COMPUTER_USE_ACTIONS

    @classmethod
    def extract_computer_use_intent(cls, action: Dict[str, Any]) -> Optional[str]:
        """
        Extract user intent from computer_use action

        Args:
            action: Action dict from LLM response

        Returns:
            User intent string or None
        """
        # Try different field names
        intent = (
            action.get("user_intent") or
            action.get("intent") or
            action.get("description") or
            action.get("task") or
            action.get("reason")
        )

        return intent if isinstance(intent, str) else None

    @classmethod
    def extract_approval_level(cls, action: Dict[str, Any]) -> str:
        """
        Extract approval level from action

        Args:
            action: Action dict

        Returns:
            Approval level (AUTO, CONFIRM, SCREEN, TWO_FA) or CONFIRM as default
        """
        approval_level = action.get("approval_level", "CONFIRM")

        # Normalize to valid levels
        valid_levels = {"AUTO", "CONFIRM", "SCREEN", "TWO_FA"}
        if approval_level.upper() in valid_levels:
            return approval_level.upper()

        return "CONFIRM"

    @classmethod
    def route_action(cls, action_type: str, action_params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Route action to Computer Use Tool if applicable

        Args:
            action_type: Type of action
            action_params: Action parameters

        Returns:
            Routing decision dict with tool name and params
        """
        if cls.should_route_to_computer_use(action_type):
            intent = cls.extract_computer_use_intent(action_params)
            approval_level = cls.extract_approval_level(action_params)

            if not intent:
                intent = action_params.get("params", {}).get("description", "Perform task")

            return {
                "tool": "computer_use",
                "intent": intent,
                "approval_level": approval_level,
                "original_action": action_type,
                "params": action_params
            }

        # Not a computer_use action
        return {
            "tool": None,
            "reason": f"Action type '{action_type}' not routed to computer_use"
        }


# Singleton router instance
_router: Optional[ComputerUseRouter] = None


def get_computer_use_router() -> ComputerUseRouter:
    """Get Computer Use Router singleton"""
    global _router
    if _router is None:
        _router = ComputerUseRouter()
    return _router
