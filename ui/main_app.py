"""
Main Application Window - Elyan Desktop Application
Modern desktop interface with all features integrated
"""

import sys
import os
import asyncio
import json
from pathlib import Path
from typing import Optional, Callable

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QStackedWidget, QLabel, QPushButton, QFrame, QSystemTrayIcon,
    QMenu, QMessageBox, QSplashScreen, QProgressBar
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QThread, QSize
from PyQt6.QtGui import QIcon, QPixmap, QAction, QFont, QColor, QPalette

from utils.logger import get_logger
from ui.branding import load_brand_icon

logger = get_logger("main_app")


class BotWorker(QThread):
    """Background worker for bot operations"""

    message_received = pyqtSignal(str)
    status_changed = pyqtSignal(str, bool)
    error_occurred = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._running = False
        self._agent = None

    def initialize_agent(self):
        """Initialize the bot agent"""
        try:
            from core.agent import Agent
            self._agent = Agent()
            return True
        except Exception as e:
            logger.error(f"Agent initialization error: {e}")
            return False

    async def process_message(self, message: str) -> str:
        """Process a message through the agent"""
        if self._agent is None:
            return "Bot henüz başlatılmadı. Lütfen bekleyin."

        try:
            response = await self._agent.process(message)
            return response
        except Exception as e:
            logger.error(f"Message processing error: {e}")
            return f"Hata oluştu: {str(e)}"

    def run(self):
        """Run the bot worker"""
        self._running = True
        self.status_changed.emit("Bot başlatılıyor...", False)

        if self.initialize_agent():
            self.status_changed.emit("Bot hazır", True)
        else:
            self.error_occurred.emit("Bot başlatılamadı")

    def stop(self):
        self._running = False


class Sidebar(QFrame):
    """Modern sidebar navigation"""

    page_changed = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(72)
        self._setup_ui()

    def _setup_ui(self):
        self.setStyleSheet("""
            QFrame {
                background-color: #0f0f0f;
                border-right: 1px solid #1a1a1a;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 16, 0, 16)
        layout.setSpacing(8)

        # Logo
        logo = QLabel("W")
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setStyleSheet("font-size: 32px; padding: 12px; font-weight: 700; color: #7196A2; font-family: 'SF Pro Display';")
        layout.addWidget(logo)

        layout.addSpacing(20)

        # Navigation buttons
        nav_items = [
            ("Chat", "Sohbet", 0),
            ("Research", "Araştırma", 1),
            ("Files", "Dosyalar", 2),
            ("AI", "Ollama", 3),
            ("Settings", "Ayarlar", 4),
        ]

        self._nav_buttons = []

        for text, tooltip, index in nav_items:
            btn = QPushButton(text)
            btn.setFixedSize(72, 48)
            btn.setToolTip(tooltip)
            btn.setStyleSheet("""
                QPushButton {
                    background-color: transparent;
                    border: none;
                    border-radius: 8px;
                    font-size: 11px;
                    font-weight: 500;
                    color: #a1a1aa;
                    font-family: 'SF Pro Text';
                    text-transform: uppercase;
                    letter-spacing: 0.5px;
                }
                QPushButton:hover {
                    background-color: #1a1a1a;
                    color: #ffffff;
                }
                QPushButton:checked {
                    background-color: #7196A2;
                    color: #ffffff;
                }
            """)
            btn.setCheckable(True)
            btn.clicked.connect(lambda checked, i=index: self._on_nav_click(i))
            layout.addWidget(btn, alignment=Qt.AlignmentFlag.AlignHCenter)
            self._nav_buttons.append(btn)

        layout.addStretch()

        # Status indicator
        self._status_dot = QLabel("●")
        self._status_dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_dot.setStyleSheet("color: #ef4444; font-size: 12px;")
        layout.addWidget(self._status_dot)

        # Set first button as active
        self._nav_buttons[0].setChecked(True)

    def _on_nav_click(self, index: int):
        for i, btn in enumerate(self._nav_buttons):
            btn.setChecked(i == index)
        self.page_changed.emit(index)

    def set_status(self, online: bool):
        color = "#10b981" if online else "#ef4444"
        self._status_dot.setStyleSheet(f"color: {color}; font-size: 12px;")


class ResearchPanel(QWidget):
    """Research panel for deep research operations"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)

        # Header
        header = QLabel(" Araştırma Merkezi")
        header.setStyleSheet("""
            QLabel {
                color: #252F33;
                font-size: 24px;
                font-weight: bold;
            }
        """)
        layout.addWidget(header)

        desc = QLabel("Derinlemesine araştırma ve rapor oluşturma")
        desc.setStyleSheet("color: #71717a; font-size: 14px;")
        layout.addWidget(desc)

        layout.addSpacing(20)

        # Research input
        from PyQt6.QtWidgets import QLineEdit, QTextEdit

        input_label = QLabel("Araştırma Konusu:")
        input_label.setStyleSheet("color: #a1a1aa; font-size: 13px;")
        layout.addWidget(input_label)

        self._topic_input = QLineEdit()
        self._topic_input.setPlaceholderText("Araştırmak istediğiniz konuyu yazın...")
        self._topic_input.setMinimumHeight(48)
        self._topic_input.setStyleSheet("""
            QLineEdit {
                background-color: #1a1a1a;
                border: 1px solid #3f3f46;
                border-radius: 12px;
                padding: 12px 16px;
                color: #ffffff;
                font-size: 14px;
            }
            QLineEdit:focus { border-color: #6366f1; }
        """)
        layout.addWidget(self._topic_input)

        layout.addSpacing(16)

        # Depth selection
        from PyQt6.QtWidgets import QComboBox

        depth_label = QLabel("Araştırma Derinliği:")
        depth_label.setStyleSheet("color: #a1a1aa; font-size: 13px;")
        layout.addWidget(depth_label)

        self._depth_combo = QComboBox()
        self._depth_combo.addItems(["Hızlı (Quick)", "Orta (Medium)", "Derin (Deep)"])
        self._depth_combo.setStyleSheet("""
            QComboBox {
                background-color: #1a1a1a;
                border: 1px solid #3f3f46;
                border-radius: 12px;
                padding: 12px 16px;
                color: #ffffff;
                font-size: 14px;
            }
        """)
        layout.addWidget(self._depth_combo)

        layout.addSpacing(20)

        # Start button
        self._start_btn = QPushButton(" Araştırmayı Başlat")
        self._start_btn.setMinimumHeight(52)
        self._start_btn.setStyleSheet("""
            QPushButton {
                background-color: #6366f1;
                color: white;
                border: none;
                border-radius: 12px;
                font-size: 16px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #4f46e5; }
            QPushButton:disabled { background-color: #3f3f46; }
        """)
        layout.addWidget(self._start_btn)

        layout.addSpacing(20)

        # Results area
        results_label = QLabel("Sonuçlar:")
        results_label.setStyleSheet("color: #a1a1aa; font-size: 13px;")
        layout.addWidget(results_label)

        self._results_area = QTextEdit()
        self._results_area.setReadOnly(True)
        self._results_area.setStyleSheet("""
            QTextEdit {
                background-color: #1a1a1a;
                border: 1px solid #3f3f46;
                border-radius: 12px;
                padding: 16px;
                color: #e4e4e7;
                font-size: 13px;
            }
        """)
        layout.addWidget(self._results_area, 1)


class FileManagerPanel(QWidget):
    """File manager panel"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)

        # Header
        header = QLabel("📁 Dosya Yöneticisi")
        header.setStyleSheet("color: #252F33; font-size: 24px; font-weight: bold;")
        layout.addWidget(header)

        desc = QLabel("Dosya ve klasörlerinizi yönetin")
        desc.setStyleSheet("color: #71717a; font-size: 14px;")
        layout.addWidget(desc)

        layout.addSpacing(20)

        # Quick actions
        from PyQt6.QtWidgets import QGridLayout

        actions_layout = QGridLayout()
        actions_layout.setSpacing(12)

        quick_actions = [
            ("", "Masaüstü", "desktop"),
            ("📥", "İndirilenler", "downloads"),
            ("📄", "Belgeler", "documents"),
            ("️", "Resimler", "pictures"),
            ("", "Dosya Ara", "search"),
            ("📦", "Sıkıştır", "compress"),
        ]

        for i, (icon, label, action) in enumerate(quick_actions):
            btn = QPushButton(f"{icon}\n{label}")
            btn.setFixedSize(100, 80)
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #1a1a1a;
                    border: 1px solid #3f3f46;
                    border-radius: 12px;
                    color: #ffffff;
                    font-size: 13px;
                }
                QPushButton:hover { background-color: #27272a; }
            """)
            actions_layout.addWidget(btn, i // 3, i % 3)

        layout.addLayout(actions_layout)
        layout.addStretch()


class MainWindow(QMainWindow):
    """Main application window"""

    def __init__(self):
        super().__init__()

        self.setWindowTitle("Elyan - Akıllı Bilgisayar Asistanı")
        self.setMinimumSize(1200, 800)

        # Load config
        self._config = self._load_config()

        # Setup UI
        self._setup_ui()
        self._setup_tray()

        # Initialize workers
        self._bot_worker = BotWorker()
        self._bot_worker.status_changed.connect(self._on_status_changed)
        self._bot_worker.error_occurred.connect(self._on_error)

        # Start bot
        QTimer.singleShot(500, self._start_bot)

    def _load_config(self) -> dict:
        """Load configuration"""
        config_file = Path.home() / ".wiqo" / "config.json"
        if config_file.exists():
            try:
                with open(config_file, 'r') as f:
                    return json.load(f)
            except:
                pass
        return {}

    def _setup_ui(self):
        """Setup the main UI"""
        # Central widget
        central = QWidget()
        self.setCentralWidget(central)

        # Main layout
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Sidebar
        self._sidebar = Sidebar()
        self._sidebar.page_changed.connect(self._on_page_changed)
        main_layout.addWidget(self._sidebar)

        # Content stack
        self._content_stack = QStackedWidget()
        self._content_stack.setStyleSheet("background-color: #0f0f0f;")

        # Add pages
        from ui.chat_widget import ChatWidget
        from ui.settings_panel_ui import SettingsPanelUI
        from ui.ollama_manager import OllamaManager

        # Chat page
        self._chat_widget = ChatWidget(process_callback=self._process_message)
        self._content_stack.addWidget(self._chat_widget)

        # Research page
        self._research_panel = ResearchPanel()
        self._content_stack.addWidget(self._research_panel)

        # Files page
        self._file_panel = FileManagerPanel()
        self._content_stack.addWidget(self._file_panel)

        # Ollama page
        self._ollama_manager = OllamaManager()
        self._content_stack.addWidget(self._ollama_manager)

        # Settings page
        self._settings_panel = SettingsPanelUI(self._config)
        self._content_stack.addWidget(self._settings_panel)

        main_layout.addWidget(self._content_stack, 1)

        # Apply dark theme
        self._apply_theme()

    def _apply_theme(self):
        """Apply dark theme"""
        self.setStyleSheet("""
            QMainWindow {
                background-color: #0f0f0f;
            }
            QWidget {
                color: #ffffff;
            }
            QScrollBar:vertical {
                background-color: #1a1a1a;
                width: 8px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background-color: #3f3f46;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #6366f1;
            }
        """)

    def _setup_tray(self):
        """Setup system tray"""
        self._tray = QSystemTrayIcon(self)
        tray_icon = load_brand_icon(size=64)
        if not tray_icon.isNull():
            self._tray.setIcon(tray_icon)

        # Create tray menu
        tray_menu = QMenu()

        show_action = QAction("Göster", self)
        show_action.triggered.connect(self.show)
        tray_menu.addAction(show_action)

        tray_menu.addSeparator()

        quit_action = QAction("Çıkış", self)
        quit_action.triggered.connect(self._quit_app)
        tray_menu.addAction(quit_action)

        self._tray.setContextMenu(tray_menu)
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

    def _on_page_changed(self, index: int):
        """Handle page change"""
        self._content_stack.setCurrentIndex(index)

    def _on_status_changed(self, message: str, online: bool):
        """Handle bot status change"""
        self._sidebar.set_status(online)
        self._chat_widget.set_status(online, message)

    def _on_error(self, error: str):
        """Handle bot error"""
        QMessageBox.warning(self, "Hata", f"Bot hatası: {error}")

    def _start_bot(self):
        """Start the bot worker"""
        self._bot_worker.start()

    async def _process_message(self, message: str) -> str:
        """Process a chat message"""
        if self._bot_worker._agent:
            return await self._bot_worker.process_message(message)
        return "Bot henüz hazır değil. Lütfen bekleyin..."

    def _on_tray_activated(self, reason):
        """Handle tray icon activation"""
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show()
            self.activateWindow()

    def _quit_app(self):
        """Quit the application"""
        self._bot_worker.stop()
        QApplication.quit()

    def closeEvent(self, event):
        """Handle close event"""
        if self._config.get("general", {}).get("minimize_to_tray", True):
            event.ignore()
            self.hide()
            self._tray.showMessage(
                "Elyan",
                "Uygulama sistem tepsisinde çalışmaya devam ediyor",
                QSystemTrayIcon.MessageIcon.Information,
                2000
            )
        else:
            self._quit_app()


class SplashScreen(QSplashScreen):
    """Application splash screen"""

    def __init__(self):
        # Create splash pixmap
        pixmap = QPixmap(400, 300)
        pixmap.fill(QColor("#0f0f0f"))

        super().__init__(pixmap)

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Logo
        logo = QLabel("")
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setStyleSheet("font-size: 64px;")
        layout.addWidget(logo)

        # Title
        title = QLabel("Elyan")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("color: #ffffff; font-size: 32px; font-weight: bold;")
        layout.addWidget(title)

        # Subtitle
        subtitle = QLabel("Akıllı Bilgisayar Asistanı")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet("color: #71717a; font-size: 14px;")
        layout.addWidget(subtitle)

        layout.addSpacing(20)

        # Progress bar
        self._progress = QProgressBar()
        self._progress.setMaximumWidth(200)
        self._progress.setStyleSheet("""
            QProgressBar {
                background-color: #27272a;
                border-radius: 4px;
                height: 8px;
            }
            QProgressBar::chunk {
                background-color: #6366f1;
                border-radius: 4px;
            }
        """)
        layout.addWidget(self._progress, alignment=Qt.AlignmentFlag.AlignCenter)

        # Status
        self._status = QLabel("Yükleniyor...")
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status.setStyleSheet("color: #a1a1aa; font-size: 12px;")
        layout.addWidget(self._status)

    def set_progress(self, value: int, message: str = ""):
        self._progress.setValue(value)
        if message:
            self._status.setText(message)
        QApplication.processEvents()


def check_first_run() -> bool:
    """Check if this is the first run"""
    config_dir = Path.home() / ".wiqo"
    return not config_dir.exists()


def run_setup_wizard():
    """Run the setup wizard"""
    from ui.wizard_entry import SetupWizard

    wizard = SetupWizard()
    result = wizard.exec()

    return result == wizard.DialogCode.Accepted


def main():
    """Main entry point"""
    app = QApplication(sys.argv)
    app.setApplicationName("Elyan")
    app.setApplicationVersion("2.0.0")
    app.setOrganizationName("Elyan")

    # Show splash screen
    splash = SplashScreen()
    splash.show()

    # Check first run
    splash.set_progress(10, "Yapılandırma kontrol ediliyor...")

    if check_first_run():
        splash.set_progress(20, "İlk kurulum başlatılıyor...")
        splash.close()

        if not run_setup_wizard():
            return 0

        splash = SplashScreen()
        splash.show()

    # Load components
    splash.set_progress(40, "Bileşenler yükleniyor...")
    QApplication.processEvents()

    splash.set_progress(60, "Arayüz hazırlanıyor...")
    QApplication.processEvents()

    # Create main window
    splash.set_progress(80, "Ana pencere oluşturuluyor...")
    window = MainWindow()

    splash.set_progress(100, "Hazır!")
    QApplication.processEvents()

    # Show main window
    import time
    time.sleep(0.5)
    splash.close()
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
