"""Legacy PyQt desktop compatibility shell.

This module is kept only for short-lived compatibility and smoke boot flows.
Canonical product UX lives in apps/desktop (React/Tauri).
"""

import sys
import os
import asyncio
import json
import time
import threading
import concurrent.futures
from pathlib import Path
from typing import Optional, List, Dict, Any, Callable
import psutil

from utils.logger import get_logger
logger = get_logger("clean_main_app")
_MONO_FONT_FAMILY = "Menlo"

# Professional macOS Environment Fix (v18.0 Industrial)
if sys.platform == "darwin":
    try:
        import PyQt6
        qt_path = Path(PyQt6.__file__).parent / "Qt6" / "plugins"
        if qt_path.exists():
            os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(qt_path)
    except Exception:
        pass

from core.monitoring import get_monitoring
from core.capability_metrics import get_capability_metrics
from core.pricing_tracker import get_pricing_tracker
from core.artifact_quality_engine import get_artifact_quality_engine
from core.pipeline_state import get_pipeline_state

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QThread, QSize, QObject, QPoint, QEvent
from PyQt6.QtGui import QIcon, QPixmap, QAction, QFont, QFontDatabase, QColor, QPalette, QFileSystemModel
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QFrame, QStackedWidget, QScrollArea,
    QSystemTrayIcon, QMenu, QMessageBox, QLineEdit, QComboBox,
    QFileDialog, QListView, QToolButton,
    QProgressBar, QListWidget, QListWidgetItem, QTextEdit
)
from ui.components import (
    SidebarButton, GlassFrame, StatCard, FileItem, Switch, 
    SectionHeader, Divider, LatencyGraph, AnimatedButton, PulseLabel
)
from ui.branding import load_brand_icon, load_brand_pixmap
from ui.premium_home import PremiumHomeView
from ui.ai_settings_panel import CleanAIPanel
from core.ux_engine import get_ux_engine


def _configure_font_fallbacks(app: QApplication) -> None:
    """Set robust fallback mappings to avoid missing SF font warnings on macOS/Qt."""
    global _MONO_FONT_FAMILY
    try:
        families = set(QFontDatabase.families())
        default_family = app.font().family()

        ui_font = ".AppleSystemUIFont" if ".AppleSystemUIFont" in families else default_family
        display_font = ui_font
        mono_candidates = ("SF Mono", "Menlo", "Monaco", "Courier New", default_family)
        mono_font = next((font for font in mono_candidates if font in families), default_family)

        QFont.insertSubstitution("SF Pro Display", display_font)
        QFont.insertSubstitution("SF Pro Text", ui_font)
        QFont.insertSubstitution("SF Mono", mono_font)
        QFont.insertSubstitution("Sans Serif", ui_font)
        _MONO_FONT_FAMILY = mono_font
        app.setFont(QFont(ui_font, 13))
    except Exception as exc:
        logger.debug(f"Font fallback configuration skipped: {exc}")


def _configure_macos_menu_bar_only() -> None:
    """Hide dock icon and keep Elyan as a menu bar app on macOS."""
    if sys.platform != "darwin":
        return
    try:
        from AppKit import NSApplication, NSApplicationActivationPolicyAccessory

        NSApplication.sharedApplication().setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    except Exception as exc:
        logger.debug(f"macOS activation policy not applied: {exc}")


def _activate_macos_app() -> None:
    """Force foreground activation for accessory-mode macOS app."""
    if sys.platform != "darwin":
        return
    try:
        from AppKit import NSApplication

        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
    except Exception:
        pass

def _is_llm_configured() -> bool:
    """Return True when at least one LLM provider is configured."""
    try:
        from config.settings_manager import SettingsPanel
        settings = SettingsPanel()
        provider = str(settings.get("llm_provider", "")).strip().lower()
        api_key = str(settings.get("api_key", "")).strip()
        if provider == "ollama":
            return True
        if api_key:
            return True
    except Exception:
        pass

    # Environment fallback for compatibility.
    if os.getenv("GROQ_API_KEY") or os.getenv("GOOGLE_API_KEY") or os.getenv("OPENAI_API_KEY"):
        return True
    if str(os.getenv("LLM_TYPE", "")).strip().lower() == "ollama":
        return True
    return False


class _WindowTitleBar(QFrame):
    """Custom frameless title bar with drag and window controls."""

    minimize_requested = pyqtSignal()
    maximize_restore_requested = pyqtSignal()
    close_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._drag_active = False
        self._drag_offset = QPoint()
        self._setup_ui()

    def _setup_ui(self):
        self.setObjectName("window_title_bar")
        self.setFixedHeight(40)
        self.setStyleSheet("""
            QFrame#window_title_bar {
                background: #FBFCFE;
                border: none;
            }
            QLabel {
                background: transparent;
            }
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(6)

        self._min_btn = QToolButton(self)
        self._max_btn = QToolButton(self)
        self._close_btn = QToolButton(self)

        for btn in (self._min_btn, self._max_btn, self._close_btn):
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setAutoRaise(True)
            btn.setFixedSize(30, 22)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self._min_btn.setText("−")
        self._max_btn.setText("□")
        self._close_btn.setText("×")

        self._min_btn.setStyleSheet(self._control_style("#64748b", "#e8ecf2", "#dbe3ee"))
        self._max_btn.setStyleSheet(self._control_style("#64748b", "#e8ecf2", "#dbe3ee"))
        self._close_btn.setStyleSheet(self._control_style("#ef4444", "#fee2e2", "#fecaca"))

        self._min_btn.clicked.connect(lambda: self.minimize_requested.emit())
        self._max_btn.clicked.connect(lambda: self.maximize_restore_requested.emit())
        self._close_btn.clicked.connect(lambda: self.close_requested.emit())

        if sys.platform == "darwin":
            layout.addWidget(self._close_btn)
            layout.addWidget(self._min_btn)
            layout.addWidget(self._max_btn)
            layout.addStretch(1)
        else:
            layout.addStretch(1)
            layout.addWidget(self._min_btn)
            layout.addWidget(self._max_btn)
            layout.addWidget(self._close_btn)

    @staticmethod
    def _control_style(fg: str, hover_bg: str, pressed_bg: str) -> str:
        return f"""
            QToolButton {{
                color: {fg};
                background: transparent;
                border: none;
                border-radius: 10px;
                font-size: 15px;
                font-weight: 600;
                padding: 0 4px;
            }}
            QToolButton:hover {{
                background: {hover_bg};
            }}
            QToolButton:pressed {{
                background: {pressed_bg};
            }}
        """

    def set_title(self, title: str, subtitle: str | None = None):
        return

    def set_maximized(self, maximized: bool):
        self._max_btn.setText("❐" if maximized else "□")

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.maximize_restore_requested.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event):
        clicked = self.childAt(event.position().toPoint())
        if event.button() == Qt.MouseButton.LeftButton and clicked not in {self._min_btn, self._max_btn, self._close_btn}:
            self._drag_active = True
            self._drag_offset = event.globalPosition().toPoint()
            self._drag_offset -= self.window().frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_active and event.buttons() & Qt.MouseButton.LeftButton:
            window = self.window()
            if window.isMaximized():
                return
            window.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_active = False
        super().mouseReleaseEvent(event)


class AgentBridge(QObject):
    """
    Thread-safe bridge between the Agent (async/background) and UI (main thread).
    Prevents QPainter and thread violation errors by using Qt Signals.
    """
    status_updated = pyqtSignal(str)
    history_added = pyqtSignal(str, str)
    activity_logged = pyqtSignal(str, str)
    thought_notified = pyqtSignal(str)
    screenshot_shown = pyqtSignal(str, str)
    approval_requested = pyqtSignal(str, str)

    def update_status(self, message: str):
        self.status_updated.emit(message)

    def add_to_history(self, user_input: str, result: str):
        self.history_added.emit(user_input, result)
    
    def log_activity(self, text: str, time_str: str = "şimdi"):
        self.activity_logged.emit(text, time_str)

    def notify_thought(self, thought: str | dict):
        if isinstance(thought, dict):
            if thought.get("type") == "screenshot":
                self.screenshot_shown.emit(thought.get("path", ""), thought.get("message", ""))
            else:
                # Fallback for other dict-based notifications
                self.status_updated.emit(str(thought))
        else:
            self.thought_notified.emit(thought)

    def show_screenshot(self, path: str, message: str):
        self.screenshot_shown.emit(path, message)

    def request_approval(self, request_id: str, message: str):
        self.approval_requested.emit(request_id, message)


class BotWorker(QThread):
    """Background worker for bot operations with async support"""

    message_received = pyqtSignal(str)
    status_changed = pyqtSignal(str, bool)
    error_occurred = pyqtSignal(str)
    activity_logged = pyqtSignal(str, str) # text, time_str
    research_finished = pyqtSignal(object) # result payload (dict or text)

    def __init__(self):
        super().__init__()
        self._running = False
        self._agent = None
        self._loop = None
        self._telegram_app = None
        self.bridge = AgentBridge()
        self._approval_futures: Dict[str, asyncio.Future] = {}

    async def _initialize_agent(self):
        """Initialize the bot agent asynchronously"""
        try:
            from core.agent import Agent
            from security.approval import get_approval_manager
            self._agent = Agent()
            
            # Connect UI bridge if agent exposes a bridge API (backward-compatible).
            bridge_connected = False
            for method_name in ("connect_ui", "connect_bridge", "set_ui_bridge"):
                method = getattr(self._agent, method_name, None)
                if callable(method):
                    method(self.bridge)
                    bridge_connected = True
                    logger.info(f"Agent UI bridge connected via {method_name}")
                    break
            if not bridge_connected:
                logger.warning("Agent UI bridge API not found; running without direct bridge callbacks")

            # Register desktop approval callback (Telegram setup wraps this as fallback).
            get_approval_manager().set_approval_callback(self._ui_approval_callback)
            
            success = await self._agent.initialize()
            return success
        except Exception as e:
            logger.error(f"Agent initialization error: {e}")
            return False

    async def _ui_approval_callback(self, approval_request):
        """
        Approval callback for desktop UI.
        Returns None for Telegram user IDs so Telegram callback can handle those.
        """
        user_id = int(getattr(approval_request, "user_id", 0) or 0)
        if user_id > 0:
            return None

        if not self._loop:
            return False

        future = self._loop.create_future()
        self._approval_futures[approval_request.id] = future

        message = (
            "Yüksek riskli işlem onayı gerekiyor.\n\n"
            f"İşlem: {approval_request.operation}\n"
            f"Açıklama: {approval_request.description}\n"
            f"Risk: {approval_request.risk_level.value.upper()}\n\n"
            "Devam etmek istiyor musunuz?"
        )
        self.bridge.request_approval(approval_request.id, message)

        try:
            return bool(await future)
        finally:
            self._approval_futures.pop(approval_request.id, None)

    async def _start_telegram(self):
        """Telegram botunu arka planda başlatır"""
        token = ""
        try:
            from config.settings_manager import SettingsPanel
            token = str(SettingsPanel().get("telegram_token", "") or "").strip()
        except Exception:
            token = ""

        if not token:
            token = str(os.getenv("TELEGRAM_BOT_TOKEN", "") or "").strip()

        if not token or token == "YOUR_TOKEN_HERE":
            logger.info("Telegram token ayarlı değil, Telegram botu başlatılmadı")
            return

        try:
            # Silent token validation
            import httpx
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"https://api.telegram.org/bot{token}/getMe")
                if resp.status_code != 200:
                    logger.error(f"Geçersiz Telegram Token: {resp.status_code}")
                    return
            
            from telegram.ext import ApplicationBuilder
            from handlers.telegram_handler import setup_handlers

            self._telegram_app = ApplicationBuilder().token(token).build()
            setup_handlers(self._telegram_app, self._agent)

            await self._telegram_app.initialize()
            await self._telegram_app.start()
            await self._telegram_app.updater.start_polling(drop_pending_updates=True)
            self.activity_logged.emit("Telegram botu aktif edildi ve dinlemeye başladı", "şimdi")
            logger.info("Telegram botu başarıyla başlatıldı ve polling yapıyor")
        except Exception as e:
            logger.error(f"Telegram bot başlatma hatası: {e}")

    async def process_message(self, message: str) -> str:
        """Process a message through the worker's event loop safely."""
        if self._agent is None:
            return "Bot henüz başlatılmadı. Lütfen bekleyin."

        if not self._loop or not self._loop.is_running():
            return "Arka plan döngüsü hazır değil. Lütfen tekrar deneyin."

        self.activity_logged.emit(f"Kullanıcı mesajı işleniyor: {message[:30]}...", "şimdi")

        async def _runner() -> str:
            raw = await self._agent.process(message, metadata={"channel_type": "desktop", "source": "desktop_chat"})
            ux_result = await get_ux_engine().postprocess_response(
                raw_response=raw,
                user_message=message,
                session_id="desktop:local",
                user_id="local",
                channel_type="desktop",
                metadata={"channel_type": "desktop", "source": "desktop_chat"},
            )
            return ux_result.response

        try:
            # Always execute agent processing on BotWorker loop.
            cfut = asyncio.run_coroutine_threadsafe(_runner(), self._loop)
            wrapped = asyncio.wrap_future(cfut)
            response = await wrapped
            self.activity_logged.emit("İşlem başarıyla tamamlandı", "şimdi")
            return response
        except concurrent.futures.CancelledError:
            return "İşlem iptal edildi."
        except Exception as e:
            logger.error(f"Message processing error: {e}")
            return f"Hata oluştu: {str(e)}"

    def trigger_research(self, topic: str, depth: str, fmt: str):
        """Trigger background research"""
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self._run_research(topic, depth, fmt), self._loop)

    async def _run_research(self, topic: str, depth: str, fmt: str):
        """Run deep research in background"""
        try:
            self.activity_logged.emit(f"Derin araştırma başlatıldı: {topic}", "şimdi")
            from tools.research_tools.advanced_research import advanced_research
            
            result = await advanced_research(topic, depth=depth)
            
            if result.get("success"):
                summary = result.get("summary", "Özet oluşturulamadı.")
                report_paths = result.get("report_paths", [])
                
                output = f"### ARAŞTIRMA TAMAMLANDI: {topic}\n\n"
                output += summary + "\n\n"
                if report_paths:
                    output += "**Oluşturulan Raporlar:**\n"
                    for p in report_paths:
                        output += f"- {p}\n"
                
                self.research_finished.emit(result)
                self.activity_logged.emit(f"Araştırma raporu hazır: {topic}", "şimdi")
            else:
                self.research_finished.emit({"success": False, "error": result.get("error")})
                
        except Exception as e:
            logger.error(f"Background research error: {e}")
            self.research_finished.emit({"success": False, "error": str(e)})

    def run(self):
        """Run the bot worker loop"""
        self._running = True
        self.status_changed.emit("Sistem başlatılıyor...", False)

        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        # Run initialization
        init_success = self._loop.run_until_complete(self._initialize_agent())

        if init_success:
            self.status_changed.emit("Bot hazır", True)
            self.activity_logged.emit("Yapay zeka sistemi başarıyla başlatıldı", "şimdi")
            # Try to start telegram in background without blocking
            self._loop.create_task(self._start_telegram())

            # Keep the loop running
            try:
                self._loop.run_forever()
            except Exception as e:
                logger.error(f"Worker loop error: {e}")
            finally:
                # Cleanup
                if self._agent and hasattr(self._agent, 'llm'):
                    self._loop.run_until_complete(self._agent.llm.close())
                self._loop.close()
        else:
            self.error_occurred.emit("Bot başlatılamadı")

    def stop(self):
        self._running = False
        for _, fut in list(self._approval_futures.items()):
            if not fut.done() and self._loop and self._loop.is_running():
                self._loop.call_soon_threadsafe(fut.set_result, False)
        self._approval_futures.clear()
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._telegram_app:
            # We would need another loop call to properly stop telegram
            pass

    def submit_approval_decision(self, request_id: str, approved: bool):
        """Set approval decision from UI thread into worker event loop safely."""
        future = self._approval_futures.get(request_id)
        if not future or future.done():
            return

        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(future.set_result, bool(approved))
        else:
            future.set_result(bool(approved))


class CleanSidebar(QFrame):
    """Clean sidebar navigation with modern components"""

    page_changed = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(232)
        self._setup_ui()

    def _setup_ui(self):
        self.setStyleSheet("""
            QFrame {
                background-color: #FFFFFF;
                border-right: 1px solid #E8ECF2;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addSpacing(12)

        # Navigation
        nav_items = [
            ("Home", 0),
            ("Dashboard", 1),
            ("Tasks", 2),
            ("Insights", 3),
            ("Settings", 5),
        ]

        self._nav_buttons = []

        nav_container = QWidget()
        nav_container.setStyleSheet("background: transparent; border: none;")
        nav_layout = QVBoxLayout(nav_container)
        nav_layout.setContentsMargins(12, 12, 12, 12)
        nav_layout.setSpacing(8)

        for name, index in nav_items:
            btn = SidebarButton("", name)
            btn.clicked.connect(lambda checked, i=index: self._on_nav_click(i))
            nav_layout.addWidget(btn)
            self._nav_buttons.append(btn)

        layout.addWidget(nav_container)
        layout.addStretch()

        # Profile area
        status_frame = QFrame()
        status_frame.setFixedHeight(84)
        status_frame.setStyleSheet("QFrame { background: #FCFCFD; border: 1px solid #E9ECF1; border-radius: 22px; }")
        status_layout = QVBoxLayout(status_frame)
        status_layout.setContentsMargins(12, 10, 12, 10)
        status_layout.setSpacing(5)

        profile_row = QHBoxLayout()
        profile_row.setContentsMargins(0, 0, 0, 0)
        profile_row.setSpacing(8)
        avatar = QFrame()
        avatar.setFixedSize(34, 34)
        avatar.setStyleSheet("QFrame { background: #EAF2FF; border: none; border-radius: 19px; }")
        avatar_layout = QVBoxLayout(avatar)
        avatar_layout.setContentsMargins(0, 0, 0, 0)
        avatar_label = QLabel("RK")
        avatar_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar_label.setStyleSheet("color: #4C82FF; font-weight: 700;")
        avatar_layout.addWidget(avatar_label)
        profile_row.addWidget(avatar)

        profile_text = QVBoxLayout()
        profile_text.setSpacing(0)
        user_name = QLabel("Robin Kim")
        user_name.setFont(QFont(".AppleSystemUIFont", 12, QFont.Weight.DemiBold))
        user_name.setStyleSheet("color: #111318; border: none;")
        user_role = QLabel("Barin-001")
        user_role.setFont(QFont(".AppleSystemUIFont", 10))
        user_role.setStyleSheet("color: #8A93A3; border: none;")
        profile_text.addWidget(user_name)
        profile_text.addWidget(user_role)
        profile_row.addLayout(profile_text, 1)
        status_layout.addLayout(profile_row)

        self._status_text = QLabel("Bot hazır")
        self._status_text.setFont(QFont(".AppleSystemUIFont", 10))
        self._status_text.setStyleSheet("color: #16A34A; border: none;")
        status_layout.addWidget(self._status_text)

        self._status_bar = QProgressBar()
        self._status_bar.setFixedHeight(3)
        self._status_bar.setTextVisible(False)
        self._status_bar.setStyleSheet("""
            QProgressBar {
                background-color: #E9ECF1;
                border: none;
                border-radius: 2px;
            }
            QProgressBar::chunk {
                background-color: #4C82FF;
                border-radius: 2px;
            }
        """)
        status_layout.addWidget(self._status_bar)

        layout.addWidget(status_frame)

        # Set first button as active
        self._nav_buttons[0].set_active(True)

    def _on_nav_click(self, index: int):
        for i, btn in enumerate(self._nav_buttons):
            btn.set_active(i == index)
        self.page_changed.emit(index)

    def set_status(self, online: bool, text: str = None):
        if online:
            self._status_text.setText(text or "Bot hazır")
            self._status_text.setStyleSheet("color: #16A34A; border: none; font-weight: 600; font-size: 10px;")
            self._status_bar.setValue(100)
            self._status_bar.setStyleSheet(self._status_bar.styleSheet().replace("#4C82FF", "#16A34A"))
        else:
            self._status_text.setText(text or "Çevrimdışı")
            self._status_text.setStyleSheet("color: #8A93A3; border: none;")
            self._status_bar.setValue(30)
            self._status_bar.setStyleSheet(self._status_bar.styleSheet().replace("#16A34A", "#EF4444"))


class CleanDashboard(QWidget):
    """Modern Dashboard with Activity Feed and Stats"""
    quick_mode_requested = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 20)
        layout.setSpacing(18)

        shell = QFrame()
        shell.setStyleSheet(
            "QFrame { background: #FFFFFF; border: 1px solid #E9ECF1; border-radius: 30px; }"
        )
        shell_layout = QHBoxLayout(shell)
        shell_layout.setContentsMargins(22, 18, 22, 18)
        shell_layout.setSpacing(18)

        center = QFrame()
        center.setStyleSheet("QFrame { background: transparent; border: none; }")
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(16)

        topbar = QHBoxLayout()
        topbar.setContentsMargins(0, 0, 0, 0)
        topbar.setSpacing(12)
        brand = QHBoxLayout()
        brand.setContentsMargins(0, 0, 0, 0)
        brand.setSpacing(8)
        star = QLabel("✦")
        star.setStyleSheet("color: #9EB1D5; font-size: 22px;")
        brand_title = QLabel("Elyan")
        brand_title.setFont(QFont(".AppleSystemUIFont", 21, QFont.Weight.DemiBold))
        brand_title.setStyleSheet("color: #2B3441; border: none;")
        brand.addWidget(star)
        brand.addWidget(brand_title)
        topbar.addLayout(brand)
        topbar.addStretch()
        topbar.addWidget(self._make_chip("Light", toggle=True))
        topbar.addWidget(self._make_chip("Back"))
        center_layout.addLayout(topbar)

        hero_row = QHBoxLayout()
        hero_row.setContentsMargins(0, 0, 0, 0)
        hero_row.setSpacing(0)
        hero_row.addStretch()
        mascot_column = QVBoxLayout()
        mascot_column.setContentsMargins(0, 0, 0, 0)
        mascot_column.setSpacing(0)
        mascot_column.addStretch()
        mascot_shell = QFrame()
        mascot_shell.setFixedSize(320, 320)
        mascot_shell.setStyleSheet("QFrame { background: transparent; border: none; }")
        mascot_layout = QVBoxLayout(mascot_shell)
        mascot_layout.setContentsMargins(0, 0, 0, 0)
        mascot_layout.setSpacing(0)
        mascot = QLabel()
        pix = load_brand_pixmap(size=260)
        if not pix.isNull():
            mascot.setPixmap(pix)
            mascot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mascot_layout.addWidget(mascot)
        mascot_column.addWidget(mascot_shell, 0, Qt.AlignmentFlag.AlignHCenter)
        mascot_column.addStretch()
        hero_row.addLayout(mascot_column)
        hero_row.addStretch()
        center_layout.addLayout(hero_row)

        card = QFrame()
        card.setStyleSheet(
            "QFrame { background: #FCFCFD; border: 1px solid #E9ECF1; border-radius: 28px; }"
        )
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(20, 20, 20, 18)
        card_layout.setSpacing(16)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(8)
        title = QLabel("✦ Elyan")
        title.setFont(QFont(".AppleSystemUIFont", 23, QFont.Weight.DemiBold))
        title.setStyleSheet("color: #2B3441; border: none;")
        header_row.addWidget(title)
        header_row.addStretch()
        more = QLabel("···")
        more.setStyleSheet("color: #A7B0BE; font-size: 26px; letter-spacing: 2px;")
        header_row.addWidget(more)
        card_layout.addLayout(header_row)

        self._hero_command = QLineEdit()
        self._hero_command.setPlaceholderText("Ask a question or type a command...")
        self._hero_command.setMinimumHeight(58)
        self._hero_command.setFont(QFont(".AppleSystemUIFont", 14))
        self._hero_command.setStyleSheet("""
            QLineEdit {
                background: #FFFFFF;
                border: 1px solid #E9ECF1;
                border-radius: 28px;
                padding: 0 18px;
                color: #111318;
            }
            QLineEdit:focus {
                border: 1px solid #C9D6F5;
                background: #FFFFFF;
            }
            QLineEdit::placeholder { color: #A7B0BE; }
        """)
        self._hero_send = QPushButton("↻")
        self._hero_send.setFixedSize(34, 34)
        self._hero_send.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hero_send.setStyleSheet(
            "QPushButton { background: #F7F8FA; color: #7B8594; border: 1px solid #E9ECF1; border-radius: 17px; font-size: 20px; }"
        )
        self._hero_send.clicked.connect(self._send_hero_command)
        command_box = QHBoxLayout()
        command_box.setContentsMargins(0, 0, 0, 0)
        command_box.addWidget(self._hero_command, 1)
        command_box.addWidget(self._hero_send)
        card_layout.addLayout(command_box)

        quick_row = QHBoxLayout()
        quick_row.setSpacing(12)
        for text in ("Create a report", "Summarize notes", "Search the docs", "Generate image"):
            chip = self._make_quick_chip(text)
            quick_row.addWidget(chip)
        quick_row.addStretch()
        card_layout.addLayout(quick_row)

        footer_row = QHBoxLayout()
        footer_row.setContentsMargins(0, 0, 0, 0)
        footer_row.addWidget(QLabel("Quick Action.."))
        footer_row.addStretch()
        footer_row.addWidget(QLabel("Your commands"))
        footer_row.addWidget(QLabel("›"))
        card_layout.addLayout(footer_row)

        center_layout.addWidget(card)
        shell_layout.addWidget(center, 1)

        right = QFrame()
        right.setFixedWidth(330)
        right.setStyleSheet("QFrame { background: transparent; border: none; }")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 6, 0, 6)
        right_layout.setSpacing(12)

        activity_title = QLabel("Activity")
        activity_title.setFont(QFont(".AppleSystemUIFont", 19, QFont.Weight.DemiBold))
        activity_title.setStyleSheet("color: #2B3441; border: none;")
        right_layout.addWidget(activity_title)

        self._activity_frame = QFrame()
        self._activity_frame.setStyleSheet(
            "QFrame { background: #FCFCFD; border: 1px solid #E9ECF1; border-radius: 26px; }"
        )
        activity_layout = QVBoxLayout(self._activity_frame)
        activity_layout.setContentsMargins(12, 12, 12, 12)
        activity_layout.setSpacing(10)
        self._activity_list = QListWidget()
        self._activity_list.setStyleSheet("""
            QListWidget {
                background: transparent;
                border: none;
                padding: 0;
            }
            QListWidget::item {
                padding: 6px;
                border: none;
                margin-bottom: 8px;
            }
        """)
        activity_layout.addWidget(self._activity_list)
        right_layout.addWidget(self._activity_frame, 1)
        shell_layout.addWidget(right)

        layout.addWidget(shell)

        # Dash stats remain in a compact row under the hero card.
        stats_layout = QHBoxLayout()
        stats_layout.setSpacing(16)
        self._cpu_card = StatCard("", "0%", "CPU Kullanımı", "#0F9AFE")
        self._mem_card = StatCard("", "0 MB", "Bellek", "#5856D6")
        self._disk_card = StatCard("", "0%", "Disk Durumu", "#34C759")
        stats_layout.addWidget(self._cpu_card)
        stats_layout.addWidget(self._mem_card)
        stats_layout.addWidget(self._disk_card)
        layout.addLayout(stats_layout)

        ai_row1 = QHBoxLayout()
        ai_row1.setSpacing(16)
        self._latency_card = StatCard("", "0ms", "AI Hızı", "#0F9AFE")
        self._success_card = StatCard("", "100%", "Başarı Oranı", "#34C759")
        self._ops_card = StatCard("", "0", "Toplam İşlem", "#5856D6")
        self._domain_card = StatCard("", "general", "Odak Domain", "#FF9500")
        ai_row1.addWidget(self._latency_card)
        ai_row1.addWidget(self._success_card)
        ai_row1.addWidget(self._ops_card)
        ai_row1.addWidget(self._domain_card)
        layout.addLayout(ai_row1)

        ai_row2 = QHBoxLayout()
        ai_row2.setSpacing(16)
        self._cost_card = StatCard("", "$0.00", "Tahmini Maliyet", "#FF3B30")
        self._quality_card = StatCard("", "0", "Kalite Skoru", "#AF52DE")
        self._pipeline_card = StatCard("", "A:0 R:0", "Pipeline", "#007AFF")
        ai_row2.addWidget(self._cost_card)
        ai_row2.addWidget(self._quality_card)
        ai_row2.addWidget(self._pipeline_card)
        layout.addLayout(ai_row2)

        layout.addWidget(SectionHeader("Performans Trendi"))
        self._latency_graph = LatencyGraph()
        layout.addWidget(self._latency_graph)

        self._add_activity("Sistem başlatıldı", "şimdi")

        # Setup stats timer
        self._stats_timer = QTimer(self)
        self._stats_timer.timeout.connect(self._update_stats)
        self._stats_timer.start(2000)
        self._update_stats()

    def _send_hero_command(self):
        text = str(getattr(self, "_hero_command", None).text() if hasattr(self, "_hero_command") else "").strip()
        if not text:
            return
        self.quick_mode_requested.emit("custom", text)
        if hasattr(self, "_hero_command"):
            self._hero_command.clear()

    def _update_stats(self):
        """Fetch and update real-time system metrics"""
        try:
            cpu_percent = psutil.cpu_percent()
            self._cpu_card.set_value(f"{cpu_percent}%")
            
            mem = psutil.virtual_memory()
            mem_used_mb = int(mem.used / (1024 * 1024))
            self._mem_card.set_value(f"{mem_used_mb} MB")
            
            disk = psutil.disk_usage('/')
            self._disk_card.set_value(f"{disk.percent}%")

            # AI Metrics (v7.0)
            monitor = get_monitoring()
            health = monitor.get_health_status()
            dashboard = monitor.get_dashboard()
            
            latency_bytes = dashboard.get("metrics_summary", {}).get("llm_latency", {})
            avg_latency = latency_bytes.get("avg", 0)
            self._latency_card.set_value(f"{int(avg_latency)}ms")
            
            self._success_card.set_value(health.get("success_rate", "100%"))
            self._ops_card.set_value(str(health.get("total_operations", 0)))

            cap_summary = get_capability_metrics().summary(window_hours=24)
            top_domain = str(cap_summary.get("top_domain", "general"))
            top_rate = cap_summary.get("domains", {}).get(top_domain, {}).get("success_rate", 0.0)
            self._domain_card.set_value(f"{top_domain[:8]} {top_rate:.0f}%")

            pricing = get_pricing_tracker().summary()
            lifetime_cost = float(pricing.get("lifetime", {}).get("estimated_cost_usd", 0.0))
            self._cost_card.set_value(f"${lifetime_cost:.2f}")

            quality = get_artifact_quality_engine().summary(window_hours=24)
            avg_quality = float(quality.get("avg_quality_score", 0.0))
            publish_rate = float(quality.get("publish_ready_rate", 0.0))
            self._quality_card.set_value(f"{avg_quality:.0f}/{publish_rate:.0f}%")

            pipeline = self._pipeline_summary(window_hours=24)
            active_count = int(pipeline.get("active_count", 0))
            recent_total = int(pipeline.get("recent_total", 0))
            self._pipeline_card.set_value(f"A:{active_count} R:{recent_total}")
            
            # Update Latency Graph (v8.0)
            self._latency_graph.add_value(avg_latency)

            # Proactive Suggestions (v7.0)
            self._update_suggestions()

            # Proactive Dashboard Alerts (v5.0)
            if cpu_percent > 85:
                self._add_activity("UYARI: Yüksek sistem yükü tespit edildi.", "şimdi")
            if mem.percent > 90:
                self._add_activity("UYARI: Bellek kullanımı kritik seviyede.", "şimdi")

        except Exception as e:
            logger.error(f"Error updating stats: {e}")

    def _pipeline_summary(self, window_hours: int = 24) -> Dict[str, Any]:
        """Compatibility summary across old/new pipeline state implementations."""
        state = get_pipeline_state()
        summary_fn = getattr(state, "history_summary", None)
        if callable(summary_fn):
            try:
                data = summary_fn(window_hours=window_hours)
                if isinstance(data, dict):
                    return data
            except Exception as exc:
                logger.debug(f"Pipeline summary helper failed: {exc}")

        pipelines = getattr(state, "_pipelines", {})
        if not isinstance(pipelines, dict):
            return {"active_count": 0, "recent_total": 0}

        cutoff = time.time() - (max(1, int(window_hours)) * 3600)
        active_count = 0
        recent_total = 0
        for pipeline in pipelines.values():
            status = str(pipeline.get("status", "running"))
            if status == "running":
                active_count += 1
                continue
            completed_at = float(pipeline.get("completed_at") or 0.0)
            if completed_at >= cutoff:
                recent_total += 1
        return {"active_count": active_count, "recent_total": recent_total}

    def _add_activity(self, text: str, time_str: str):
        item = QListWidgetItem()
        widget = FileItem(text, time_str)
        item.setSizeHint(widget.sizeHint())
        self._activity_list.addItem(item)
        self._activity_list.setItemWidget(item, widget)

    def _make_chip(self, text: str, toggle: bool = False) -> QWidget:
        chip = QPushButton(text)
        chip.setFixedHeight(32)
        chip.setMinimumWidth(74 if len(text) <= 4 else 88)
        chip.setCursor(Qt.CursorShape.PointingHandCursor)
        chip.setStyleSheet("""
            QPushButton {
                background: #F7F8FA;
                color: #8A93A3;
                border: 1px solid #E9ECF1;
                border-radius: 16px;
                padding: 0 14px;
                font-size: 12px;
            }
            QPushButton:hover {
                background: #FFFFFF;
                color: #5B6472;
            }
        """)
        if toggle:
            chip.setText("Light")
        return chip

    def _make_quick_chip(self, text: str) -> QWidget:
        chip = QPushButton(text)
        chip.setFixedHeight(34)
        chip.setCursor(Qt.CursorShape.PointingHandCursor)
        chip.setStyleSheet("""
            QPushButton {
                background: #FFFFFF;
                color: #5B6472;
                border: 1px solid #E9ECF1;
                border-radius: 10px;
                padding: 0 14px;
                font-size: 12px;
            }
            QPushButton:hover {
                background: #FCFCFD;
                color: #111318;
            }
        """)
        chip.clicked.connect(lambda checked=False, label=text: self.quick_mode_requested.emit("custom", label))
        return chip

    def _update_suggestions(self):
        """Fetch proactive task suggestions from the agent"""
        try:
            # Need to reach the agent via the main app layout
            main_app = self.window()
            if hasattr(main_app, "_bot_worker") and main_app._bot_worker._agent:
                agent = main_app._bot_worker._agent
                # Loop is async, so we'd need a signal or a simpler sync check
                # For now, let's use a simpler heuristic if we can't easily await here
                # Or just keep it as a placeholder that updates occasionally
                pass
        except:
            pass




class CleanFilePanel(QWidget):
    """File panel with real file system integration"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(14)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(8)
        header = QLabel("Files")
        header.setFont(QFont(".AppleSystemUIFont", 24, QFont.Weight.DemiBold))
        header.setStyleSheet("color: #111318; border: none; letter-spacing: -0.4px;")
        subtitle = QLabel("Local file control")
        subtitle.setStyleSheet("color: #8B95A7; border: none; font-size: 11px;")
        header_row.addWidget(header)
        header_row.addWidget(subtitle)
        header_row.addStretch()
        actions = QToolButton()
        actions.setText("Actions ▾")
        actions.setCursor(Qt.CursorShape.PointingHandCursor)
        actions.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        actions.setFixedHeight(28)
        actions.setStyleSheet(
            """
            QToolButton {
                background: #FFFFFF;
                color: #5D6675;
                border: 1px solid #E8ECF2;
                border-radius: 14px;
                padding: 0 12px;
                font-size: 11px;
                font-weight: 600;
            }
            QToolButton:hover { background: #F7F8FA; color: #111318; }
            """
        )
        action_menu = QMenu(actions)
        refresh_action = action_menu.addAction("Refresh")
        refresh_action.triggered.connect(lambda checked=False: self._model.setRootPath(self._model.rootPath()))
        open_action = action_menu.addAction("Open selected")
        open_action.triggered.connect(lambda checked=False: self._open_selected())
        semantic_action = action_menu.addAction("Semantic analysis")
        semantic_action.setCheckable(True)
        semantic_action.setChecked(False)
        semantic_action.toggled.connect(self._on_semantic_toggled)
        actions.setMenu(action_menu)
        header_row.addWidget(actions)
        layout.addLayout(header_row)

        # Actions
        actions_layout = QHBoxLayout()
        actions_layout.setSpacing(10)

        self._refresh_btn = AnimatedButton("Yenile", primary=False)
        self._open_btn = AnimatedButton("Dosyayı Aç", primary=True)

        actions_layout.addWidget(self._refresh_btn)
        actions_layout.addWidget(self._open_btn)
        actions_layout.addStretch()
        layout.addLayout(actions_layout)

        # Browser
        self._file_frame = GlassFrame()
        browser_layout = QVBoxLayout(self._file_frame)
        browser_layout.setContentsMargins(1, 1, 1, 1)

        self._model = QFileSystemModel()
        self._model.setRootPath(str(Path.home()))
        
        self._view = QListView()
        self._view.setModel(self._model)
        self._view.setRootIndex(self._model.index(str(Path.home() / "Desktop")))
        
        self._view.setStyleSheet("""
            QListView {
                background: #FFFFFF;
                border: 1px solid #E5E5EA;
                border-radius: 12px;
                color: #252F33;
                padding: 10px;
                font-size: 13px;
            }
            QListView::item { 
                padding: 12px; 
                border-radius: 8px; 
                margin-bottom: 2px;
                color: #252F33;
            }
            QListView::item:hover { background-color: #F2F2F7; }
            QListView::item:selected { background-color: #7196A2; color: #FFFFFF; }
        """)
        
        browser_layout.addWidget(self._view)
        layout.addWidget(self._file_frame, 1)

        self._open_btn.clicked.connect(self._open_selected)
        self._refresh_btn.clicked.connect(lambda: self._model.setRootPath(self._model.rootPath()))

    def _on_semantic_toggled(self, checked: bool):
        """Handle semantic analysis toggle logic"""
        if checked:
            logger.info("Semantic analysis enabled for File Panel (indexing placeholder)")
            # In a real implementation, this would trigger an indexing worker
        else:
            logger.info("Semantic analysis disabled")

    def _open_selected(self):
        index = self._view.currentIndex()
        if index.isValid():
            path = self._model.filePath(index)
            import subprocess
            if sys.platform == "darwin":
                subprocess.run(["open", path], check=False)
            elif sys.platform.startswith("win"):
                os.startfile(path)  # type: ignore[attr-defined]
            else:
                subprocess.run(["xdg-open", path], check=False)


class CleanResearchPanel(QWidget):
    """Clean research panel"""
    research_requested = pyqtSignal(str, str, str) # topic, depth, format

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(14)

        header = QLabel("Research")
        header.setFont(QFont(".AppleSystemUIFont", 24, QFont.Weight.DemiBold))
        header.setStyleSheet("color: #111318; border: none; letter-spacing: -0.4px;")
        layout.addWidget(header)

        desc = QLabel("Compact deep research workspace")
        desc.setFont(QFont(".AppleSystemUIFont", 11))
        desc.setStyleSheet("color: #8E8E93;")
        layout.addWidget(desc)

        # Input section
        input_group = GlassFrame()
        input_layout = QVBoxLayout(input_group)
        input_layout.setContentsMargins(18, 16, 18, 16)
        input_layout.setSpacing(12)

        topic_label = QLabel("Topic")
        topic_label.setFont(QFont(".AppleSystemUIFont", 12, QFont.Weight.Medium))
        topic_label.setStyleSheet("color: #8E8E93; border: none;")
        input_layout.addWidget(topic_label)

        self._topic_input = QLineEdit()
        self._topic_input.setPlaceholderText("Araştırmak istediğiniz konuyu yazın...")
        self._topic_input.setMinimumHeight(44)
        self._topic_input.setFont(QFont(".AppleSystemUIFont", 13))
        self._topic_input.setStyleSheet("""
            QLineEdit {
                background-color: #FFFFFF;
                border: 1px solid #E8ECF2;
                border-radius: 12px;
                padding: 10px 14px;
                color: #111318;
            }
            QLineEdit:focus { border-color: #C9D6F5; }
            QLineEdit::placeholder { color: #A7B0BE; }
        """)
        input_layout.addWidget(self._topic_input)

        # Options row
        options_layout = QHBoxLayout()
        options_layout.setSpacing(10)

        depth_label = QLabel("Depth")
        depth_label.setFont(QFont(".AppleSystemUIFont", 11))
        depth_label.setStyleSheet("color: #8E8E93;")
        options_layout.addWidget(depth_label)

        self._depth_combo = QComboBox()
        self._depth_combo.addItems(["Hızlı", "Orta", "Derin"])
        self._depth_combo.setFont(QFont(".AppleSystemUIFont", 11))
        self._depth_combo.setStyleSheet("""
            QComboBox {
                background-color: #FFFFFF;
                border: 1px solid #E8ECF2;
                border-radius: 12px;
                padding: 8px 12px;
                color: #111318;
                min-width: 104px;
            }
            QComboBox::drop-down { border: none; }
        """)
        options_layout.addWidget(self._depth_combo)

        options_layout.addStretch()

        format_label = QLabel("Format")
        format_label.setFont(QFont(".AppleSystemUIFont", 11))
        format_label.setStyleSheet("color: #8E8E93;")
        options_layout.addWidget(format_label)

        self._format_combo = QComboBox()
        self._format_combo.addItems(["Markdown", "PDF", "Word"])
        self._format_combo.setFont(QFont(".AppleSystemUIFont", 11))
        self._format_combo.setStyleSheet("""
            QComboBox {
                background-color: #FFFFFF;
                border: 1px solid #E8ECF2;
                border-radius: 12px;
                padding: 8px 12px;
                color: #111318;
                min-width: 104px;
            }
            QComboBox::drop-down { border: none; }
        """)
        options_layout.addWidget(self._format_combo)

        input_layout.addLayout(options_layout)

        layout.addWidget(input_group)

        # Start button
        self._start_btn = AnimatedButton("Araştırmayı Başlat", primary=True)
        self._start_btn.setMinimumHeight(42)
        self._start_btn.clicked.connect(self._on_start_clicked)
        layout.addWidget(self._start_btn)

        # Results & Charts Row
        results_container = QHBoxLayout()
        results_container.setSpacing(12)

        # Text Results
        text_layout = QVBoxLayout()
        text_layout.addWidget(QLabel("Insights"))
        self._results_area = QTextEdit()
        self._results_area.setReadOnly(True)
        self._results_area.setFont(QFont(".AppleSystemUIFont", 12))
        self._results_area.setStyleSheet("""
            QTextEdit {
                background-color: #FFFFFF;
                border: 1px solid #E8ECF2;
                border-radius: 14px;
                padding: 12px;
                color: #111318;
            }
        """)
        text_layout.addWidget(self._results_area)
        results_container.addLayout(text_layout, 1)

        # Visual Charts
        chart_layout = QVBoxLayout()
        chart_layout.addWidget(QLabel("Chart"))
        self._chart_scroll = QScrollArea()
        self._chart_scroll.setWidgetResizable(True)
        self._chart_scroll.setStyleSheet("background: transparent; border: none;")
        
        self._chart_label = QLabel()
        self._chart_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._chart_label.setText("Grafikler burada görünecek")
        self._chart_label.setStyleSheet("color: #8E8E93; background: #FCFCFD; border: 1px solid #E8ECF2; border-radius: 14px; padding: 28px;")
        self._chart_scroll.setWidget(self._chart_label)
        
        chart_layout.addWidget(self._chart_scroll)
        results_container.addLayout(chart_layout, 1)
        layout.addLayout(results_container, 1)

        from ui.components import PulseLabel
        self._status_pulse = PulseLabel("Araştırılıyor...")
        self._status_pulse.setStyleSheet("color: #3b82f6; font-weight: bold;")
        self._status_pulse.hide()
        layout.addWidget(self._status_pulse)

    def _on_start_clicked(self):
        topic = self._topic_input.text().strip()
        if not topic: return
        depth = self._depth_combo.currentText()
        fmt = self._format_combo.currentText()
        self._start_btn.setEnabled(False)
        self._results_area.setText("Derin araştırma motoru çalıştırılıyor...")
        self._status_pulse.show()
        self._status_pulse.start()
        self.research_requested.emit(topic, depth, fmt)

    def display_results(self, data: Any):
        """Display research results and charts"""
        self._start_btn.setEnabled(True)
        self._status_pulse.stop()
        self._status_pulse.hide()
        if isinstance(data, str):
            self._results_area.setMarkdown(data)
        elif isinstance(data, dict):
            summary = data.get("summary", "")
            self._results_area.setMarkdown(summary)
            if data.get("chart"):
                self.set_chart(data.get("chart"))

    def set_chart(self, base64_image: str):
        """Display research chart from base64 string with crash protection"""
        if not base64_image or not isinstance(base64_image, str):
            self._chart_label.setText("Grafik verisi bulunamadı")
            return
            
        try:
            if "base64," in base64_image:
                base64_image = base64_image.split("base64,")[1]
            
            from PyQt6.QtCore import QByteArray
            from PyQt6.QtGui import QPixmap
            
            img_data = QByteArray.fromBase64(base64_image.encode())
            pixmap = QPixmap()
            if not pixmap.loadFromData(img_data):
                raise ValueError("Pixmap load failed")
            
            # Scale to fit while maintaining aspect ratio
            scaled_pixmap = pixmap.scaled(
                self._chart_scroll.width() - 20,
                self._chart_scroll.height() - 20,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self._chart_label.setPixmap(scaled_pixmap)
            self._chart_label.setText("") 
        except Exception as e:
            logger.error(f"Error setting chart: {e}")
            self._chart_label.setText("Grafik işlenirken hata oluştu")


class CleanSettingsPanel(QWidget):
    """Compact settings panel focused on automatic behavior."""

    def __init__(self, parent=None):
        super().__init__(parent)
        from config.settings_manager import SettingsPanel as SettingsManager
        self._settings_manager = SettingsManager()
        self._setup_ui()
        self._load_settings()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(14)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(8)

        title_block = QVBoxLayout()
        title_block.setContentsMargins(0, 0, 0, 0)
        title_block.setSpacing(1)
        title = QLabel("Settings")
        title.setFont(QFont(".AppleSystemUIFont", 24, QFont.Weight.DemiBold))
        title.setStyleSheet("color: #111318; border: none; letter-spacing: -0.4px;")
        subtitle = QLabel("Mostly automatic. Only the essentials remain.")
        subtitle.setStyleSheet("color: #8B95A7; border: none; font-size: 11px;")
        title_block.addWidget(title)
        title_block.addWidget(subtitle)
        header_row.addLayout(title_block)
        header_row.addStretch()

        menu_button = QToolButton()
        menu_button.setText("More ▾")
        menu_button.setCursor(Qt.CursorShape.PointingHandCursor)
        menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu_button.setFixedHeight(28)
        menu_button.setStyleSheet(
            """
            QToolButton {
                background: #FFFFFF;
                color: #5D6675;
                border: 1px solid #E8ECF2;
                border-radius: 14px;
                padding: 0 12px;
                font-size: 11px;
                font-weight: 600;
            }
            QToolButton:hover { background: #F7F8FA; color: #111318; }
            """
        )
        menu = QMenu(menu_button)
        open_ai = menu.addAction("Open AI settings")
        open_ai.triggered.connect(lambda checked=False: self._open_ai_settings())
        clear_learning = menu.addAction("Clear learning data")
        clear_learning.triggered.connect(lambda checked=False: self._on_user_data_delete_requested())
        menu_button.setMenu(menu)
        header_row.addWidget(menu_button)
        layout.addLayout(header_row)

        behavior_card = GlassFrame()
        behavior_layout = QVBoxLayout(behavior_card)
        behavior_layout.setContentsMargins(18, 16, 18, 16)
        behavior_layout.setSpacing(10)

        behavior_header = QLabel("Automation")
        behavior_header.setFont(QFont(".AppleSystemUIFont", 14, QFont.Weight.DemiBold))
        behavior_header.setStyleSheet("color: #111318; border: none;")
        behavior_layout.addWidget(behavior_header)

        self._auto_replan_switch = self._make_setting_row(
            behavior_layout,
            "auto_replan_enabled",
            "Auto replanning",
            "Task engine retries and re-plans automatically.",
        )
        self._consensus_switch = self._make_setting_row(
            behavior_layout,
            "consensus_enabled",
            "Consensus checks",
            "Critical decisions use multi-agent consensus.",
        )
        self._learning_switch = self._make_setting_row(
            behavior_layout,
            "learning_paused",
            "Learning paused",
            "Pause adaptive learning without touching other systems.",
        )
        layout.addWidget(behavior_card)

        note_card = GlassFrame()
        note_layout = QVBoxLayout(note_card)
        note_layout.setContentsMargins(18, 14, 18, 14)
        note_layout.setSpacing(8)
        note_title = QLabel("AI controls")
        note_title.setFont(QFont(".AppleSystemUIFont", 14, QFont.Weight.DemiBold))
        note_title.setStyleSheet("color: #111318; border: none;")
        note_body = QLabel("Provider and model live on the AI page. Settings stays focused on runtime behavior.")
        note_body.setWordWrap(True)
        note_body.setStyleSheet("color: #8B95A7; border: none; font-size: 11px;")
        note_layout.addWidget(note_title)
        note_layout.addWidget(note_body)
        layout.addWidget(note_card)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.addStretch()
        open_ai_btn = AnimatedButton("Open AI settings", primary=False)
        open_ai_btn.clicked.connect(self._open_ai_settings)
        actions.addWidget(open_ai_btn)
        layout.addLayout(actions)

        self._status_label = QLabel("")
        self._status_label.setStyleSheet("color: #A7B0BE; font-size: 11px; border: none;")
        layout.addWidget(self._status_label)
        layout.addStretch()

    def _make_setting_row(self, parent_layout: QVBoxLayout, setting_key: str, title: str, description: str) -> Switch:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)

        text_block = QVBoxLayout()
        text_block.setContentsMargins(0, 0, 0, 0)
        text_block.setSpacing(1)
        label = QLabel(title)
        label.setFont(QFont(".AppleSystemUIFont", 12, QFont.Weight.Medium))
        label.setStyleSheet("color: #111318; border: none;")
        desc = QLabel(description)
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #8B95A7; border: none; font-size: 10px;")
        text_block.addWidget(label)
        text_block.addWidget(desc)
        row.addLayout(text_block, 1)

        switch = Switch()
        switch.toggled.connect(lambda checked, key=setting_key: self._on_setting_toggled(key, checked))
        row.addWidget(switch, 0, Qt.AlignmentFlag.AlignRight)
        parent_layout.addLayout(row)
        return switch

    def _load_settings(self):
        self._auto_replan_switch.set_checked(bool(self._settings_manager.get("auto_replan_enabled", True)))
        self._consensus_switch.set_checked(bool(self._settings_manager.get("consensus_enabled", True)))
        self._learning_switch.set_checked(bool(self._settings_manager.get("learning_paused", False)))

    def _on_setting_toggled(self, key: str, checked: bool):
        updates: dict[str, Any] = {}
        if key == "auto_replan_enabled":
            updates["auto_replan_enabled"] = bool(checked)
        elif key == "consensus_enabled":
            updates["consensus_enabled"] = bool(checked)
        elif key == "learning_paused":
            updates["learning_paused"] = bool(checked)
        if not updates:
            return
        try:
            self._settings_manager.update(updates)
            self._apply_runtime_settings(updates)
            self._status_label.setText("Saved automatically")
        except Exception as exc:
            logger.error(f"Settings update failed: {exc}")
            self._status_label.setText("Save failed")

    def _apply_runtime_settings(self, settings: dict):
        runtime_updates = {k: settings[k] for k in ("auto_replan_enabled", "consensus_enabled", "learning_paused") if k in settings}
        if not runtime_updates:
            return
        try:
            from core.task_engine import get_task_engine

            task_engine = get_task_engine()
            if hasattr(task_engine, "settings") and hasattr(task_engine.settings, "_settings"):
                task_engine.settings._settings.update(runtime_updates)
        except Exception as exc:
            logger.debug(f"Task engine runtime update skipped: {exc}")
        try:
            from core.learning_control import get_learning_control_plane

            plane = get_learning_control_plane()
            uid = "local"
            if "learning_paused" in runtime_updates:
                plane.set_learning_paused(bool(runtime_updates.get("learning_paused")), user_id=uid)
        except Exception as exc:
            logger.debug(f"Learning control runtime update skipped: {exc}")

    def _open_ai_settings(self):
        app = self.window()
        if hasattr(app, "_show_page"):
            app._show_page(4)
        if hasattr(app, "_show_and_activate"):
            app._show_and_activate()

    def _on_user_data_delete_requested(self):
        try:
            from core.learning_control import get_learning_control_plane

            result = get_learning_control_plane().delete_user_data("local")
            QMessageBox.information(self, "Operator Intelligence", "Kullanıcı öğrenme verileri silindi.")
            logger.info(f"Local user learning data deleted: {result}")
            app = self.window()
            if hasattr(app, "_dashboard"):
                app._dashboard._add_activity("Kullanıcı öğrenme verileri silindi", "şimdi")
        except Exception as exc:
            logger.error(f"Delete user learning data failed: {exc}")
            QMessageBox.warning(self, "Operator Intelligence", f"Veri silme başarısız: {exc}")


class CleanAdvancedPanel(QWidget):
    """Advanced system panel for logs and technical info"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(14)

        # Header
        header = QLabel("System Audit")
        header.setFont(QFont(".AppleSystemUIFont", 24, QFont.Weight.DemiBold))
        header.setStyleSheet("color: #111318; border: none; letter-spacing: -0.4px;")
        layout.addWidget(header)

        # Log Section
        layout.addWidget(SectionHeader("Logs"))
        
        self._log_area = QTextEdit()
        self._log_area.setReadOnly(True)
        self._log_area.setFont(QFont(_MONO_FONT_FAMILY, 11))
        self._log_area.setStyleSheet("""
            QTextEdit {
                background-color: #FFFFFF;
                border: 1px solid #E8ECF2;
                border-radius: 14px;
                padding: 12px;
                color: #111318;
                selection-background-color: #EAF2FF;
            }
        """)
        
        # Try to load initial logs
        try:
            log_path = Path("logs/bot.log")
            if log_path.exists():
                with open(log_path, 'r') as f:
                    lines = f.readlines()[-100:] # Last 100 lines
                    self._log_area.setText("".join(lines))
        except Exception:
            self._log_area.setText("Log dosyası okunamadı.")
            
        layout.addWidget(self._log_area, 1)
        
        # Debug Info
        info_frame = GlassFrame()
        info_layout = QVBoxLayout(info_frame)
        
        import platform
        sys_info = f"Sistem: {platform.system()} {platform.release()}\n"
        sys_info += f"Python: {platform.python_version()}\n"
        sys_info += f"İşlemci: {platform.processor()}"
        
        info_label = QLabel(sys_info)
        info_label.setStyleSheet(f"color: #8E8E93; font-family: '{_MONO_FONT_FAMILY}';")
        info_layout.addWidget(info_label)
        
        layout.addWidget(info_frame)


class CleanMainWindow(QMainWindow):
    """Clean main application window"""
    async_ui_message = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._window_shell = None
        self._title_bar = None
        self._chrome_margins = 16
        self._bot_worker = BotWorker()
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        
        self.setWindowTitle("Elyan v24.0 Pro")
        self.setWindowIcon(load_brand_icon(size=128))
        self.setMinimumSize(1180, 760)
        self.resize(1320, 840)

        self._config = self._load_config()
        self._setup_ui()
        self._setup_tray()
        self.async_ui_message.connect(self._on_async_ui_message)

        self._bot_worker.status_changed.connect(self._on_status_changed)
        self._bot_worker.error_occurred.connect(self._on_error)
        self._bot_worker.activity_logged.connect(self._dashboard._add_activity)
        
        # Bridge Connections (Thread-Safety v13.0)
        self._bot_worker.bridge.status_updated.connect(lambda msg: self._sidebar.set_status(True, msg))
        self._bot_worker.bridge.history_added.connect(self._on_history_added)
        self._bot_worker.bridge.activity_logged.connect(self._dashboard._add_activity)
        self._bot_worker.bridge.thought_notified.connect(self._on_thought_notified)
        self._bot_worker.bridge.screenshot_shown.connect(self._on_screenshot_shown)
        self._bot_worker.bridge.approval_requested.connect(self._on_approval_requested)

        QTimer.singleShot(500, self._start_bot)

    def _on_history_added(self, user_input: str, result: str):
        """Thread-safe history update"""
        if hasattr(self, "_chat_widget"):
            self._chat_widget.add_message(user_input, is_user=True)
            self._chat_widget.add_message(result, is_user=False)

    def _on_thought_notified(self, thought: str):
        """Display live reasoning thoughts"""
        if hasattr(self, "_chat_widget"):
            self._chat_widget.add_message(f"[Reasoning] {thought}", is_user=False)
        self._dashboard._add_activity(f"Düşünce: {thought[:40]}...", "şimdi")

    def _on_screenshot_shown(self, path: str, message: str):
        """Handle visual verification display"""
        self._dashboard._add_activity(f"Görsel Doğrulama: {message}", "şimdi")
        if hasattr(self, "_chat_widget"):
            self._chat_widget.add_message(f"[Screenshot] {message}\nDosya: {path}", is_user=False)

    def _on_approval_requested(self, request_id: str, message: str):
        """Display explicit approval dialog and return user's decision to worker."""
        answer = QMessageBox.question(
            self,
            "Onay Gerekli",
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        approved = answer == QMessageBox.StandardButton.Yes
        self._bot_worker.submit_approval_decision(request_id, approved)

    def _load_config(self) -> dict:
        config_file = Path.home() / ".elyan" / "config.json"
        if config_file.exists():
            try:
                with open(config_file, 'r') as f:
                    return json.load(f)
            except:
                pass
        return {}

    def _setup_ui(self):
        central = QWidget()
        central.setObjectName("central_widget")
        central.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setCentralWidget(central)

        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(self._chrome_margins, self._chrome_margins, self._chrome_margins, self._chrome_margins)
        root_layout.setSpacing(0)

        self._window_shell = QFrame()
        self._window_shell.setObjectName("window_shell")
        self._window_shell.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        shell_layout = QVBoxLayout(self._window_shell)
        shell_layout.setContentsMargins(1, 1, 1, 1)
        shell_layout.setSpacing(0)

        self._title_bar = _WindowTitleBar(self)
        self._title_bar.minimize_requested.connect(self.showMinimized)
        self._title_bar.maximize_restore_requested.connect(self._toggle_maximize_restore)
        self._title_bar.close_requested.connect(self.close)
        shell_layout.addWidget(self._title_bar)

        body = QWidget()
        body.setObjectName("window_body")
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        # Sidebar
        self._sidebar = CleanSidebar()
        self._sidebar.page_changed.connect(self._on_page_changed)
        body_layout.addWidget(self._sidebar)

        # Main container for content with background
        self._main_container = QWidget()
        self._main_container_layout = QVBoxLayout(self._main_container)
        self._main_container_layout.setContentsMargins(0, 0, 0, 0)
        
        # Content stack
        self._content_stack = QStackedWidget()
        self._content_stack.setStyleSheet("background-color: transparent;")
        self._main_container_layout.addWidget(self._content_stack)
        
        body_layout.addWidget(self._main_container, 1)
        shell_layout.addWidget(body, 1)
        root_layout.addWidget(self._window_shell, 1)

        # Import and add pages
        from ui.clean_chat_widget import CleanChatWidget

        self._dashboard = PremiumHomeView()
        self._dashboard.quick_mode_requested.connect(self._on_quick_mode_requested)
        self._dashboard.settings_requested.connect(lambda: self._show_page(5))
        self._content_stack.addWidget(self._dashboard)

        self._chat_widget = CleanChatWidget(process_callback=self._process_message)
        self._content_stack.addWidget(self._chat_widget)

        self._research_panel = CleanResearchPanel()
        self._research_panel.research_requested.connect(self._bot_worker.trigger_research)
        self._bot_worker.research_finished.connect(self._research_panel.display_results)
        self._content_stack.addWidget(self._research_panel)

        self._file_panel = CleanFilePanel()
        self._content_stack.addWidget(self._file_panel)

        self._ai_panel = CleanAIPanel()
        self._content_stack.addWidget(self._ai_panel)

        self._settings_panel = CleanSettingsPanel()
        self._content_stack.addWidget(self._settings_panel)

        self._advanced_panel = CleanAdvancedPanel()
        self._content_stack.addWidget(self._advanced_panel)

        self._apply_theme()
        self._refresh_window_frame()
        # Home-first desktop experience.
        self._sidebar._on_nav_click(0)
        self._content_stack.setCurrentIndex(0)

    def _apply_theme(self):
        self.setStyleSheet("""
            QWidget#central_widget {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #F3F7FF,
                    stop:0.48 #F8FBFF,
                    stop:1 #EEF8F4);
            }
            QMainWindow {
                background: #F3F7FF;
            }
            QFrame#window_shell {
                background: rgba(255, 255, 255, 0.72);
                border: 1px solid rgba(255, 255, 255, 0.56);
                border-radius: 20px;
            }
            QWidget#window_body {
                background: transparent;
                border-radius: 18px;
            }
            QStackedWidget {
                background: transparent;
            }
            QScrollArea {
                border: none;
                background: transparent;
            }
            QLineEdit, QComboBox, QSpinBox, QTextEdit {
                background: rgba(255, 255, 255, 0.86);
                border: 1px solid rgba(255, 255, 255, 0.64);
                border-radius: 10px;
                padding: 8px 10px;
                color: #1E293B;
                font-family: ".AppleSystemUIFont";
                font-size: 13px;
            }
            QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QTextEdit:focus {
                border: 1px solid #C9D6F5;
            }
        """)

    def _refresh_window_frame(self):
        if not self._window_shell or not self._title_bar:
            return
        maximized = self.isMaximized() or self.isFullScreen()
        margins = 0 if maximized else 12
        self._chrome_margins = margins
        if self.centralWidget() and isinstance(self.centralWidget().layout(), QVBoxLayout):
            self.centralWidget().layout().setContentsMargins(margins, margins, margins, margins)
        self._title_bar.set_maximized(maximized)
        if maximized:
            self._window_shell.setStyleSheet("""
                QFrame#window_shell {
                    background: rgba(255, 255, 255, 0.84);
                    border: 1px solid rgba(255, 255, 255, 0.58);
                    border-radius: 0px;
                }
                QWidget#window_body {
                    background: transparent;
                }
            """)
        else:
            self._apply_theme()

    def _toggle_maximize_restore(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()
        self._refresh_window_frame()

    def _setup_tray(self):
        self._tray = QSystemTrayIcon(self)
        tray_icon = load_brand_icon(size=64)
        if not tray_icon.isNull():
            self._tray.setIcon(tray_icon)

        tray_menu = QMenu()

        # Header
        header_action = QAction("Elyan v24.0", self)
        header_action.setEnabled(False)
        tray_menu.addAction(header_action)

        self._tray_status = QAction("Durum: Başlatılıyor...", self)
        self._tray_status.setEnabled(False)
        tray_menu.addAction(self._tray_status)

        tray_menu.addSeparator()

        # Main actions
        show_action = QAction("Uygulamayı Aç", self)
        show_action.triggered.connect(self._show_and_activate)
        tray_menu.addAction(show_action)

        chat_action = QAction("Sohbet", self)
        chat_action.triggered.connect(lambda: self._show_page(1))
        tray_menu.addAction(chat_action)

        tray_menu.addSeparator()

        # Quick modes
        quick_menu = tray_menu.addMenu("Hızlı Modlar")
        for mode, label in [("build", "Build"), ("research", "Research"), ("document", "Document"), ("ship", "Ship")]:
            act = QAction(label, self)
            act.triggered.connect(lambda _, m=mode: self._tray_quick_mode(m))
            quick_menu.addAction(act)

        tray_menu.addSeparator()

        from config.settings_manager import SettingsPanel
        paused_default = bool(SettingsPanel().get("learning_paused", False))
        self._pause_learning_action = QAction("Pause Learning", self)
        self._pause_learning_action.setCheckable(True)
        self._pause_learning_action.setChecked(paused_default)
        self._pause_learning_action.toggled.connect(self._tray_toggle_learning_pause)
        tray_menu.addAction(self._pause_learning_action)

        force_focused_action = QAction("Force Focused", self)
        force_focused_action.triggered.connect(self._tray_force_focused)
        tray_menu.addAction(force_focused_action)

        sleep_consolidation_action = QAction("Run Sleep Consolidation", self)
        sleep_consolidation_action.triggered.connect(self._tray_run_sleep_consolidation)
        tray_menu.addAction(sleep_consolidation_action)

        tray_menu.addSeparator()

        # Settings
        settings_action = QAction("Ayarlar", self)
        settings_action.triggered.connect(lambda: self._show_page(5))
        tray_menu.addAction(settings_action)

        ai_action = QAction("AI Ayarları", self)
        ai_action.triggered.connect(lambda: self._show_page(4))
        tray_menu.addAction(ai_action)

        tray_menu.addSeparator()

        # System
        restart_action = QAction("Botu Yeniden Başlat", self)
        restart_action.triggered.connect(self._restart_bot)
        tray_menu.addAction(restart_action)

        quit_action = QAction("Çıkış", self)
        quit_action.triggered.connect(self._quit_app)
        tray_menu.addAction(quit_action)

        self._tray.setContextMenu(tray_menu)
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

    def _show_and_activate(self):
        if self.isMinimized() or self.isMaximized():
            self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()
        _activate_macos_app()

    def _show_page(self, index: int):
        self._show_and_activate()
        self._sidebar._on_nav_click(index)
        self._content_stack.setCurrentIndex(index)

    def _tray_quick_mode(self, mode: str):
        prompts = {
            "build": "Build modu: profesyonel bir proje planla, kodu üret, test et ve teslim paketini hazırla.",
            "research": "Research modu: çok kaynaklı derin araştırma yap, riskleri çıkar ve karar özeti oluştur.",
            "document": "Document modu: yönetici özeti, ana rapor ve aksiyon maddeleri içeren profesyonel doküman paketi üret.",
            "ship": "Ship modu: mevcut çalışmayı doğrula, kalite raporu çıkar ve publish-ready teslim çıktısı üret.",
        }
        self._show_page(1)
        if hasattr(self, "_chat_widget"):
            self._chat_widget.set_draft(prompts.get(mode, ""), auto_send=True)

    def _restart_bot(self):
        self._bot_worker.stop()
        QTimer.singleShot(1000, self._start_bot)

    def _tray_toggle_learning_pause(self, paused: bool):
        try:
            from core.learning_control import get_learning_control_plane
            from config.settings_manager import SettingsPanel

            get_learning_control_plane().set_learning_paused(bool(paused), user_id="local")
            SettingsPanel().set("learning_paused", bool(paused))
            state = "durduruldu" if paused else "devam ediyor"
            self._dashboard._add_activity(f"Learning {state}", "şimdi")
        except Exception as exc:
            logger.error(f"Pause learning toggle failed: {exc}")

    def _tray_force_focused(self):
        try:
            from core.cognitive_layer_integrator import get_cognitive_integrator

            result = get_cognitive_integrator().force_mode("focused")
            if result.get("success"):
                self._dashboard._add_activity("Execution mode FOCUSED olarak ayarlandı", "şimdi")
            else:
                self._dashboard._add_activity("Force Focused başarısız", "şimdi")
        except Exception as exc:
            logger.error(f"Force focused failed: {exc}")

    def _tray_run_sleep_consolidation(self):
        try:
            from core.cognitive_layer_integrator import get_cognitive_integrator

            self._dashboard._add_activity("Sleep consolidation başlatıldı", "şimdi")
            if self._bot_worker and self._bot_worker._loop and self._bot_worker._loop.is_running():
                future = asyncio.run_coroutine_threadsafe(
                    get_cognitive_integrator().consolidate_daily_learning(force=True),
                    self._bot_worker._loop,
                )

                def _wait_future():
                    try:
                        report = future.result(timeout=120)
                        if report is None:
                            self.async_ui_message.emit("Sleep consolidation tamamlandı (konsolide edilecek veri yok).")
                        else:
                            self.async_ui_message.emit("Sleep consolidation tamamlandı.")
                    except Exception as exc:
                        self.async_ui_message.emit(f"Sleep consolidation hatası: {exc}")

                threading.Thread(target=_wait_future, daemon=True).start()
                return

            report = asyncio.run(get_cognitive_integrator().consolidate_daily_learning(force=True))
            if report is None:
                self._dashboard._add_activity("Sleep consolidation: veri yok", "şimdi")
            else:
                self._dashboard._add_activity("Sleep consolidation tamamlandı", "şimdi")
        except Exception as exc:
            logger.error(f"Sleep consolidation failed: {exc}")
            self._dashboard._add_activity(f"Sleep consolidation hatası: {exc}", "şimdi")

    def _on_page_changed(self, index: int):
        # Graphics effects can trigger QPainter re-entry warnings on some Qt builds.
        self._content_stack.setCurrentIndex(index)
        self._content_stack.currentWidget().update()
        self.setFocus()

    def _on_quick_mode_requested(self, mode: str, prompt: str):
        """Route one-click operator modes to chat workflow."""
        self._dashboard._add_activity(f"One-click mode: {mode.upper()}", "şimdi")
        # Chat page index is 1
        self._sidebar._on_nav_click(1)
        self._content_stack.setCurrentIndex(1)
        if hasattr(self, "_chat_widget"):
            self._chat_widget.set_draft(prompt, auto_send=True)

    def _on_status_changed(self, message: str, online: bool):
        self._sidebar.set_status(online, message)
        self._chat_widget.set_status(online, message)
        if hasattr(self, '_tray_status'):
            self._tray_status.setText(f"Durum: {message}")
        self._tray.setToolTip(f"Elyan - {message}")

    def _on_error(self, error: str):
        QMessageBox.warning(self, "Hata", f"Bot hatası: {error}")

    def _on_async_ui_message(self, message: str):
        self._dashboard._add_activity(message, "şimdi")

    def _start_bot(self):
        self._bot_worker.start()

    async def _process_message(self, message: str, notify: Optional[Callable] = None, **kwargs) -> str:
        """Process incoming messages from UI with explicit bridge support"""
        if self._bot_worker and self._bot_worker._agent:
            return await self._bot_worker.process_message(message)
        return "Bot henüz hazır değil. Lütfen bekleyin..."

    def _on_tray_activated(self, reason):
        if reason in {
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        }:
            self._show_and_activate()

    def _quit_app(self):
        self._bot_worker.stop()
        QApplication.quit()

    def changeEvent(self, event):
        if event.type() == QEvent.Type.WindowStateChange:
            QTimer.singleShot(0, self._refresh_window_frame)
        super().changeEvent(event)

    def resizeEvent(self, event):
        self._refresh_window_frame()
        super().resizeEvent(event)

    def closeEvent(self, event):
        if self._config.get("general", {}).get("minimize_to_tray", True):
            event.ignore()
            self.hide()
        else:
            self._quit_app()


def main():
    """Main entry point"""
    app = QApplication(sys.argv)
    _configure_font_fallbacks(app)
    _configure_macos_menu_bar_only()
    app.setApplicationName("Elyan")
    app.setApplicationVersion("24.0.0")
    app.setWindowIcon(load_brand_icon(size=128))
    app.setQuitOnLastWindowClosed(False)

    if not _is_llm_configured():
        logger.warning("LLM not configured; opening desktop in offline mode. Run `elyan setup` for onboarding.")

    window = CleanMainWindow()
    app._elyan_main_window = window  # type: ignore[attr-defined]
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
