"""settings_panel.py — backward-compat shim (Sprint J)"""

from config.settings_manager import SettingsPanel  # noqa: F401

# SettingsWindow -> SettingsPanelUI (canonical UI widget)
try:
    from ui.settings_panel_ui import SettingsPanelUI as SettingsWindow  # noqa: F401
except Exception:
    SettingsWindow = None  # type: ignore
