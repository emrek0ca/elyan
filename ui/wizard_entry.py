"""
Unified setup wizard entrypoint.

This keeps a single import path for onboarding while allowing safe fallbacks.
"""

from utils.logger import get_logger

logger = get_logger("wizard_entry")


def get_setup_wizard_class():
    """Return canonical setup wizard class with compatibility fallbacks."""
    try:
        from .apple_setup_wizard import SetupWizard as AppleSetupWizard
        return AppleSetupWizard
    except Exception as exc:
        logger.warning(f"Apple setup wizard unavailable, falling back: {exc}")

    try:
        from .enhanced_setup_wizard import SetupWizard as EnhancedSetupWizard
        return EnhancedSetupWizard
    except Exception as exc:
        logger.warning(f"Enhanced setup wizard unavailable, falling back: {exc}")

    from .setup_wizard import SetupWizard as LegacySetupWizard
    return LegacySetupWizard


SetupWizard = get_setup_wizard_class()

