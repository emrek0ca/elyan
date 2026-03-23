"""
Release Mode Configuration
Controls which features are exposed based on release maturity level.
"""

from enum import Enum
from typing import Set
import os


class ReleaseMode(Enum):
    """Release maturity levels."""
    V0_1_0_MVP = "v0.1.0"  # Minimal viable operator (Telegram + core execution)
    EXPERIMENTAL = "experimental"  # Phase 6 features included but unstable
    FULL = "full"  # All features


class FeatureSet:
    """Defines which features are available in each release mode."""

    # v0.1.0 MVP: Core operator only
    MVP_FEATURES = {
        # Core Operator
        "intent_routing",
        "session_management",
        "task_execution",
        "approval_gates",
        "filesystem_operations",
        "terminal_execution",
        "memory_system",
        "error_recovery",

        # Channels
        "telegram_channel",

        # Cognitive Layer
        "ceo_planner",
        "adaptive_tuning",
        "deadlock_detection",
    }

    # Phase 6: Competitive Edge (experimental)
    PHASE6_FEATURES = {
        "research_engine",
        "visual_intelligence",
        "code_intelligence",
        "workflow_orchestration",
        "premium_ux",
    }

    # Additional channels (post-v0.1.0)
    ADDITIONAL_CHANNELS = {
        "discord_channel",
        "slack_channel",
        "whatsapp_channel",
        "signal_channel",
        "matrix_channel",
        "teams_channel",
        "google_chat_channel",
        "imessage_channel",
    }

    # Advanced features (post-v0.1.0)
    ADVANCED_FEATURES = {
        "multi_user_organization",
        "plugin_system",
        "scaling_infrastructure",
        "team_approvals",
    }


class ReleaseManager:
    """Manages release mode and feature availability."""

    def __init__(self):
        # Determine mode from environment or default to MVP
        mode_str = os.getenv("ELYAN_RELEASE_MODE", "v0.1.0").lower()

        if mode_str == "experimental":
            self.mode = ReleaseMode.EXPERIMENTAL
        elif mode_str == "full":
            self.mode = ReleaseMode.FULL
        else:
            self.mode = ReleaseMode.V0_1_0_MVP

        self.active_features = self._get_active_features()

    def _get_active_features(self) -> Set[str]:
        """Return set of active features for current mode."""
        if self.mode == ReleaseMode.V0_1_0_MVP:
            return FeatureSet.MVP_FEATURES
        elif self.mode == ReleaseMode.EXPERIMENTAL:
            return (
                FeatureSet.MVP_FEATURES
                | FeatureSet.PHASE6_FEATURES
            )
        else:  # FULL
            return (
                FeatureSet.MVP_FEATURES
                | FeatureSet.PHASE6_FEATURES
                | FeatureSet.ADDITIONAL_CHANNELS
                | FeatureSet.ADVANCED_FEATURES
            )

    def is_feature_enabled(self, feature: str) -> bool:
        """Check if feature is enabled in current mode."""
        return feature in self.active_features

    def require_feature(self, feature: str) -> None:
        """Raise error if feature is not available."""
        if not self.is_feature_enabled(feature):
            raise FeatureNotAvailableError(
                f"Feature '{feature}' is not available in {self.mode.value} mode. "
                f"Set ELYAN_RELEASE_MODE=experimental or ELYAN_RELEASE_MODE=full to enable."
            )

    def get_mode_string(self) -> str:
        """Get human-readable mode string."""
        return self.mode.value

    def __repr__(self) -> str:
        return f"ReleaseManager({self.mode.value})"


class FeatureNotAvailableError(Exception):
    """Raised when a feature is not available in current release mode."""
    pass


# Singleton instance
_release_manager: ReleaseManager | None = None


def get_release_manager() -> ReleaseManager:
    """Get or create the singleton ReleaseManager."""
    global _release_manager
    if _release_manager is None:
        _release_manager = ReleaseManager()
    return _release_manager


def is_v0_1_0_mode() -> bool:
    """Check if running in v0.1.0 MVP mode."""
    return get_release_manager().mode == ReleaseMode.V0_1_0_MVP


def is_phase6_enabled() -> bool:
    """Check if Phase 6 features are enabled."""
    return get_release_manager().is_feature_enabled("research_engine")


__all__ = [
    "ReleaseMode",
    "ReleaseManager",
    "FeatureSet",
    "FeatureNotAvailableError",
    "get_release_manager",
    "is_v0_1_0_mode",
    "is_phase6_enabled",
]
