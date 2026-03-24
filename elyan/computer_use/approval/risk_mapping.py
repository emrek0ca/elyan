"""Risk Level Mapping for Computer Use Actions

Maps action types to security risk levels for approval gating.
"""

from enum import Enum
from typing import Dict, Tuple
from core.protocol.shared_types import RiskLevel


class ActionRiskLevel(Enum):
    """Risk categories for Computer Use actions"""
    SYSTEM_CRITICAL = "system_critical"    # System restart, password change, file deletion
    DESTRUCTIVE = "destructive"            # File operations, app termination
    WRITE_SENSITIVE = "write_sensitive"    # Form fill, text input with credentials
    WRITE_SAFE = "write_safe"              # Text input, normal typing
    READ_ONLY = "read_only"                # Screenshots, navigation, clicking


# Action type → (risk_level, reason)
ACTION_RISK_MAP: Dict[str, Tuple[ActionRiskLevel, str]] = {
    # System-critical actions
    "system_restart": (ActionRiskLevel.SYSTEM_CRITICAL, "System restart is irreversible"),
    "system_shutdown": (ActionRiskLevel.SYSTEM_CRITICAL, "System shutdown will terminate all processes"),

    # Destructive file operations
    "delete_file": (ActionRiskLevel.DESTRUCTIVE, "File deletion is permanent"),
    "delete_folder": (ActionRiskLevel.DESTRUCTIVE, "Folder deletion is permanent"),
    "move_file": (ActionRiskLevel.DESTRUCTIVE, "File move may break dependencies"),
    "format_disk": (ActionRiskLevel.DESTRUCTIVE, "Disk format is irreversible"),

    # App termination / processes
    "kill_process": (ActionRiskLevel.DESTRUCTIVE, "Process termination may lose data"),
    "uninstall_app": (ActionRiskLevel.DESTRUCTIVE, "App uninstall is permanent"),

    # Credential/sensitive input
    "type_password": (ActionRiskLevel.WRITE_SENSITIVE, "Password entry requires verification"),
    "type_credit_card": (ActionRiskLevel.WRITE_SENSITIVE, "Credit card entry requires verification"),
    "type_api_key": (ActionRiskLevel.WRITE_SENSITIVE, "API key entry requires verification"),
    "type_token": (ActionRiskLevel.WRITE_SENSITIVE, "Authentication token entry requires verification"),

    # Normal text input
    "type": (ActionRiskLevel.WRITE_SAFE, "Standard text input"),
    "type_email": (ActionRiskLevel.WRITE_SAFE, "Email address entry"),
    "type_name": (ActionRiskLevel.WRITE_SAFE, "Name/text entry"),

    # Click/navigation
    "left_click": (ActionRiskLevel.READ_ONLY, "Button/link click"),
    "right_click": (ActionRiskLevel.READ_ONLY, "Context menu"),
    "double_click": (ActionRiskLevel.READ_ONLY, "Double click"),

    # Screen/input interaction
    "scroll": (ActionRiskLevel.READ_ONLY, "Page scroll"),
    "drag": (ActionRiskLevel.READ_ONLY, "Drag operation"),
    "mouse_move": (ActionRiskLevel.READ_ONLY, "Mouse movement"),
    "hotkey": (ActionRiskLevel.WRITE_SAFE, "Keyboard shortcut"),

    # Wait/no-op
    "wait": (ActionRiskLevel.READ_ONLY, "Wait operation"),
    "noop": (ActionRiskLevel.READ_ONLY, "No operation"),
}


def get_action_risk_level(action_type: str) -> Tuple[RiskLevel, str]:
    """
    Get risk level and reason for an action type.

    Args:
        action_type: Computer use action type (e.g., "left_click", "type_password")

    Returns:
        (RiskLevel, reason_string) tuple
    """
    if action_type in ACTION_RISK_MAP:
        action_risk, reason = ACTION_RISK_MAP[action_type]
        # Convert ActionRiskLevel to RiskLevel
        risk_level_map = {
            ActionRiskLevel.SYSTEM_CRITICAL: RiskLevel.SYSTEM_CRITICAL,
            ActionRiskLevel.DESTRUCTIVE: RiskLevel.DESTRUCTIVE,
            ActionRiskLevel.WRITE_SENSITIVE: RiskLevel.WRITE_SENSITIVE,
            ActionRiskLevel.WRITE_SAFE: RiskLevel.WRITE_SAFE,
            ActionRiskLevel.READ_ONLY: RiskLevel.READ_ONLY,
        }
        return risk_level_map[action_risk], reason

    # Default: treat unknown actions as write_safe
    return RiskLevel.WRITE_SAFE, f"Unknown action type: {action_type}"


def should_require_approval(action_type: str, approval_level: str) -> bool:
    """
    Determine if action requires approval based on approval level.

    Args:
        action_type: Computer use action type
        approval_level: Approval level (AUTO, CONFIRM, SCREEN, TWO_FA)

    Returns:
        True if action requires approval, False otherwise
    """
    if approval_level == "AUTO":
        # AUTO: Only critical actions require approval
        risk_level, _ = get_action_risk_level(action_type)
        return risk_level == RiskLevel.SYSTEM_CRITICAL

    elif approval_level == "CONFIRM":
        # CONFIRM: Destructive and critical require approval
        risk_level, _ = get_action_risk_level(action_type)
        return risk_level in (RiskLevel.SYSTEM_CRITICAL, RiskLevel.DESTRUCTIVE)

    elif approval_level == "SCREEN":
        # SCREEN: Sensitive writes and above require approval
        risk_level, _ = get_action_risk_level(action_type)
        return risk_level in (
            RiskLevel.SYSTEM_CRITICAL,
            RiskLevel.DESTRUCTIVE,
            RiskLevel.WRITE_SENSITIVE
        )

    elif approval_level == "TWO_FA":
        # TWO_FA: All non-read-only actions require approval
        risk_level, _ = get_action_risk_level(action_type)
        return risk_level != RiskLevel.READ_ONLY

    # Default: no approval
    return False
