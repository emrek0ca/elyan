"""Settings Window - Apple-style configuration panel"""

import sys
from PyQt6.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QPushButton, QHBoxLayout
from PyQt6.QtCore import Qt, QTimer

from utils.logger import get_logger
from config.settings_manager import SettingsPanel
from ui.components import WiqoTheme as T, AnimatedButton

logger = get_logger("ui.settings")


class SettingsWindow(QMainWindow):
    """Apple-style Settings Window"""
    def __init__(self, agent=None):
        super().__init__()
        self.agent = agent
        self.manager = SettingsPanel()
        self._pending_settings = {}
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._flush_pending_settings)
        self.setWindowTitle("Elyan Ayarlar")
        self.setFixedSize(780, 560)
        self._setup_ui()

    def _setup_ui(self):
        from .settings_panel_ui import SettingsPanelUI

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)

        main_layout = QVBoxLayout(self.central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.ui = SettingsPanelUI(config=self.manager._settings)
        self.ui.settings_changed.connect(self._on_settings_saved)
        main_layout.addWidget(self.ui)

        # Bottom bar
        footer = QWidget()
        footer.setFixedHeight(60)
        footer.setStyleSheet(f"background: {T.BG_SECONDARY}; border-top: 1px solid {T.BORDER_LIGHT};")
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(24, 0, 24, 0)

        save_btn = AnimatedButton("Save", primary=True)
        save_btn.setFixedHeight(36)
        save_btn.clicked.connect(self._save_and_close)
        fl.addStretch()
        fl.addWidget(save_btn)
        main_layout.addWidget(footer)

        if sys.platform == "darwin":
            self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)

    def _on_settings_saved(self, settings):
        """Merge UI changes and debounce disk writes."""
        self._pending_settings.update(settings)
        self._save_timer.start(250)

    def _flush_pending_settings(self):
        if not self._pending_settings:
            return
        self.manager.update(self._pending_settings)
        self._pending_settings.clear()
        logger.info("Settings saved")

    def _save_and_close(self):
        self._save_timer.stop()
        self._flush_pending_settings()
        self.close()
