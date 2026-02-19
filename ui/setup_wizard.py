"""setup_wizard.py — backward-compat shim (Sprint J)"""

from ui.apple_setup_wizard import AppleSetupWizard as SetupWizard  # noqa: F401

__all__ = ["SetupWizard"]
