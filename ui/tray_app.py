"""System tray application for Elyan."""
import traceback

from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon
from PyQt6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PyQt6.QtCore import QObject, Qt

from utils.logger import get_logger
from ui.branding import load_brand_icon

logger = get_logger("ui.tray")

class TrayApp(QObject):
    """System Tray Icon for Elyan Background Engine"""

    def __init__(self, agent=None):
        super().__init__()
        self.agent = agent
        self.settings_window = None
        self.tray_icon = None
        self.menu = None
        self.status_action = None
        self._setup_tray()

    def _setup_tray(self):
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(self._build_tray_icon())
        self.menu = self._build_menu()
        self.tray_icon.setContextMenu(self.menu)
        self.tray_icon.show()
        self.tray_icon.setToolTip("Elyan: Hazır")
        logger.info("Tray icon initialized")

    def _build_tray_icon(self) -> QIcon:
        brand_icon = load_brand_icon(size=64)
        if not brand_icon.isNull():
            return brand_icon

        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor("#7196A2"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(8, 8, 48, 48)
        painter.end()
        return QIcon(pixmap)

    def _build_menu(self) -> QMenu:
        menu = QMenu()

        companion_action = QAction(load_brand_icon(size=24), "Elyan Yanında", self)
        companion_action.setEnabled(False)
        menu.addAction(companion_action)
        menu.addSeparator()

        self.status_action = QAction("Elyan Durum: Hazır", self)
        self.status_action.setEnabled(False)
        menu.addAction(self.status_action)
        menu.addSeparator()

        settings_action = menu.addAction("Ayarlar")
        settings_action.triggered.connect(lambda: self._safe_call(self.show_settings))

        restart_action = menu.addAction("Botu Yeniden Başlat")
        restart_action.triggered.connect(lambda: self._safe_call(self.restart_bot))

        menu.addSeparator()

        quit_action = menu.addAction("Çıkış")
        quit_action.triggered.connect(lambda: self._safe_call(self.quit_app))
        return menu

    def _safe_call(self, fn):
        """Prevent Qt slot exceptions from aborting the whole process."""
        try:
            fn()
        except Exception as exc:
            logger.error(f"Tray action failed: {exc}")
            logger.debug(traceback.format_exc())

    def show_settings(self):
        """Open the professional settings panel"""
        from ui.settings_panel import SettingsWindow
        if not self.settings_window:
            self.settings_window = SettingsWindow(agent=self.agent)

        self.settings_window.show()
        self.settings_window.raise_()
        self.settings_window.activateWindow()

    def restart_bot(self):
        """Signal agent to restart"""
        logger.info("Restart requested from tray")
        # Implementation depends on how we want to handle the process restart
        # Usually, we'd emit a signal or call agent.restart()

    def quit_app(self):
        """Clean shutdown"""
        logger.info("Shutdown requested from tray")
        QApplication.quit()

    def update_status(self, status: str):
        """Update the status text in the menu"""
        if self.status_action:
            self.status_action.setText(f"Elyan Durum: {status}")

        if status.lower() == "meşgul":
            self.tray_icon.setToolTip("Elyan: İşlem yapılıyor...")
        else:
            self.tray_icon.setToolTip("Elyan: Hazır")
