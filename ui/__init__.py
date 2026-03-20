"""
Elyan Desktop UI - Modern PyQt6 based user interface
"""

from core.dependencies.autoinstall_hook import activate as _activate_autoinstall_hook

_activate_autoinstall_hook()

# Original components
from .app import DesktopApp
from .qr_generator import QRGenerator
from .settings_panel import SettingsWindow

# New modern UI components
from .chat_widget import ChatWidget, MessageBubble, TypingIndicator
from .wizard_entry import SetupWizard
from .settings_panel_ui import SettingsPanelUI
from .ollama_manager import OllamaManager, OllamaStatus
from .main_app import MainWindow, main as run_app

__all__ = [
    # Original
    "DesktopApp",
    "QRGenerator",
    "SettingsWindow",
    # New UI
    "ChatWidget",
    "MessageBubble",
    "TypingIndicator",
    "SetupWizard",
    "SettingsPanelUI",
    "OllamaManager",
    "OllamaStatus",
    "MainWindow",
    "run_app",
]
