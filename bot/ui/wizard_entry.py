"""
Unified setup wizard entrypoint.

This keeps a single import path for onboarding while allowing safe fallbacks.
"""

from utils.logger import get_logger

logger = get_logger("wizard_entry")


def get_setup_wizard_class():
    """Return canonical setup wizard class (latest-first, no legacy fallback)."""
    try:
        from .apple_setup_wizard import AppleSetupWizard
        return AppleSetupWizard
    except Exception as exc:
        logger.warning(f"Apple setup wizard unavailable, falling back: {exc}")

    try:
        from .enhanced_setup_wizard import EnhancedSetupWizard
        return EnhancedSetupWizard
    except Exception as exc:
        logger.error(f"Enhanced setup wizard unavailable: {exc}")
        raise RuntimeError(
            "No modern setup wizard available (apple/enhanced). "
            "Legacy wizard fallback disabled intentionally."
        ) from exc


SetupWizard = get_setup_wizard_class()
