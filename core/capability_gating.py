"""
Capability Gating System
Controls whether advanced features can be invoked.
"""

from enum import Enum
import os
from utils.logger import get_logger

logger = get_logger("capability_gating")


class OperatorMode(Enum):
    """Execution mode for the operator."""
    OPERATOR = "operator"  # Default: core operator only
    ADVANCED = "advanced"  # Full features including Phase 6


class CapabilityGate:
    """
    Gates advanced capabilities based on operator mode.

    In OPERATOR mode (default):
    - Research engine DISABLED
    - Visual Intelligence DISABLED
    - Code Intelligence DISABLED
    - Workflow Orchestration DISABLED
    - Premium UX DISABLED (conversational features only)

    In ADVANCED mode:
    - All Phase 6 features ENABLED
    """

    def __init__(self):
        mode_str = os.getenv("ELYAN_OPERATOR_MODE", "operator").lower()
        self.mode = (
            OperatorMode.ADVANCED
            if mode_str == "advanced"
            else OperatorMode.OPERATOR
        )
        logger.info(f"CapabilityGate initialized in {self.mode.value} mode")

    def check_research_enabled(self) -> bool:
        """Check if research engine is enabled."""
        return self.mode == OperatorMode.ADVANCED

    def check_vision_enabled(self) -> bool:
        """Check if visual intelligence is enabled."""
        return self.mode == OperatorMode.ADVANCED

    def check_code_intel_enabled(self) -> bool:
        """Check if code intelligence is enabled."""
        return self.mode == OperatorMode.ADVANCED

    def check_workflow_enabled(self) -> bool:
        """Check if workflow orchestration is enabled."""
        return self.mode == OperatorMode.ADVANCED

    def check_premium_ux_enabled(self) -> bool:
        """Check if premium UX features are enabled."""
        return self.mode == OperatorMode.ADVANCED

    def should_use_research(self, intent: str) -> bool:
        """Determine if research should be triggered for intent."""
        if not self.check_research_enabled():
            return False
        return "research" in intent.lower() or "search" in intent.lower()

    def should_use_vision(self, intent: str) -> bool:
        """Determine if visual intelligence should be triggered."""
        if not self.check_vision_enabled():
            return False
        return (
            "screen" in intent.lower()
            or "visual" in intent.lower()
            or "see" in intent.lower()
        )

    def should_use_code_intel(self, intent: str) -> bool:
        """Determine if code intelligence should be triggered."""
        if not self.check_code_intel_enabled():
            return False
        return (
            "code" in intent.lower()
            or "analyze" in intent.lower()
            or "test" in intent.lower()
        )

    def should_use_workflow(self, intent: str) -> bool:
        """Determine if workflow orchestration should be triggered."""
        if not self.check_workflow_enabled():
            return False
        return (
            "workflow" in intent.lower()
            or "automate" in intent.lower()
            or "multi-step" in intent.lower()
        )

    def is_operator_mode(self) -> bool:
        """Check if in operator mode (default, restricted)."""
        return self.mode == OperatorMode.OPERATOR

    def is_advanced_mode(self) -> bool:
        """Check if in advanced mode (Phase 6 enabled)."""
        return self.mode == OperatorMode.ADVANCED

    def get_mode_string(self) -> str:
        """Get current mode as string."""
        return self.mode.value

    def __repr__(self) -> str:
        return f"CapabilityGate({self.mode.value})"


# Singleton instance
_capability_gate: CapabilityGate | None = None


def get_capability_gate() -> CapabilityGate:
    """Get or create the singleton CapabilityGate."""
    global _capability_gate
    if _capability_gate is None:
        _capability_gate = CapabilityGate()
    return _capability_gate


def is_operator_mode() -> bool:
    """Check if running in operator mode (default, restricted)."""
    return get_capability_gate().is_operator_mode()


def is_advanced_mode() -> bool:
    """Check if running in advanced mode."""
    return get_capability_gate().is_advanced_mode()


def check_phase6_enabled() -> bool:
    """Check if any Phase 6 features are enabled."""
    gate = get_capability_gate()
    return (
        gate.check_research_enabled()
        or gate.check_vision_enabled()
        or gate.check_code_intel_enabled()
        or gate.check_workflow_enabled()
    )


__all__ = [
    "OperatorMode",
    "CapabilityGate",
    "get_capability_gate",
    "is_operator_mode",
    "is_advanced_mode",
    "check_phase6_enabled",
]
