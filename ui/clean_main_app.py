"""
Clean Main Application - Professional desktop app without emojis
Minimal, clean and modern design
"""

import sys
import os
import asyncio
import json
import concurrent.futures
from pathlib import Path
from typing import Optional, List, Dict, Any, Callable
import psutil
from core.monitoring import get_monitoring
from core.capability_metrics import get_capability_metrics
from core.pricing_tracker import get_pricing_tracker
from core.artifact_quality_engine import get_artifact_quality_engine
from core.pipeline_state import get_pipeline_state

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QThread, QSize, QObject
from PyQt6.QtGui import QIcon, QPixmap, QAction, QFont, QFontDatabase, QColor, QPalette, QFileSystemModel
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QLabel, QPushButton, QFrame, QStackedWidget, QScrollArea, 
    QSystemTrayIcon, QMenu, QMessageBox, QLineEdit, QComboBox, 
    QFileDialog, QListView,
    QProgressBar, QListWidget, QListWidgetItem, QTextEdit
)
from ui.components import (
    SidebarButton, GlassFrame, StatCard, FileItem, Switch, 
    SectionHeader, Divider, LatencyGraph, AnimatedButton, PulseLabel
)
from ui.branding import load_brand_icon, load_brand_pixmap
from ui.ai_settings_panel import CleanAIPanel

from utils.logger import get_logger

logger = get_logger("clean_main_app")


def _configure_font_fallbacks(app: QApplication) -> None:
    """Set robust fallback mappings to avoid missing SF font warnings on macOS/Qt."""
    try:
        families = set(QFontDatabase.families())
        default_family = app.font().family()

        ui_font = ".AppleSystemUIFont" if ".AppleSystemUIFont" in families else default_family
        display_font = ui_font
        mono_font = "SF Mono" if "SF Mono" in families else ("Menlo" if "Menlo" in families else default_family)

        QFont.insertSubstitution("SF Pro Display", display_font)
        QFont.insertSubstitution("SF Pro Text", ui_font)
        QFont.insertSubstitution("SF Mono", mono_font)
        app.setFont(QFont(ui_font, 13))
    except Exception as exc:
        logger.debug(f"Font fallback configuration skipped: {exc}")

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
            
            # Connect the bridge (Thread-Safety v13.0)
            self._agent.connect_ui(self.bridge)

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
            return await self._agent.process(message)

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
        self.setFixedWidth(240)
        self._setup_ui()

    def _setup_ui(self):
        self.setStyleSheet("""
            QFrame {
                background-color: #F8FAFC;
                border-right: 1px solid #E2E8F0;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Logo area
        logo_frame = QFrame()
        logo_frame.setFixedHeight(148)
        logo_frame.setStyleSheet("background: transparent; border: none;")
        logo_layout = QVBoxLayout(logo_frame)
        logo_layout.setContentsMargins(24, 28, 24, 16)
        logo_layout.setSpacing(6)

        brand_label = QLabel()
        brand_pixmap = load_brand_pixmap(size=42)
        if not brand_pixmap.isNull():
            brand_label.setPixmap(brand_pixmap)
            brand_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            logo_layout.addWidget(brand_label)

        logo_text = QLabel("Elyan")
        logo_text.setFont(QFont(".AppleSystemUIFont", 32, QFont.Weight.Bold))
        logo_text.setStyleSheet("color: #252F33; border: none; letter-spacing: -1px;")
        logo_layout.addWidget(logo_text)
        
        logo_sub = QLabel("Strategic Digital Companion")
        logo_sub.setFont(QFont(".AppleSystemUIFont", 11, QFont.Weight.Medium))
        logo_sub.setStyleSheet("color: #8E8E93; border: none; text-transform: uppercase; letter-spacing: 0.5px;")
        logo_layout.addWidget(logo_sub)

        layout.addWidget(logo_frame)

        # Navigation
        nav_items = [
            ("Panel", 0),
            ("Sohbet", 1),
            ("Araştırma", 2),
            ("Dosyalar", 3),
            ("Zeka", 4),
            ("Ayarlar", 5),
            ("Sistem", 6),
        ]

        self._nav_buttons = []

        nav_container = QWidget()
        nav_container.setStyleSheet("background: transparent; border: none;")
        nav_layout = QVBoxLayout(nav_container)
        nav_layout.setContentsMargins(12, 20, 12, 20)
        nav_layout.setSpacing(8)

        for name, index in nav_items:
            btn = SidebarButton("", name)
            btn.clicked.connect(lambda checked, i=index: self._on_nav_click(i))
            nav_layout.addWidget(btn)
            self._nav_buttons.append(btn)

        layout.addWidget(nav_container)
        layout.addStretch()

        # Status area
        status_frame = QFrame()
        status_frame.setFixedHeight(80)
        status_layout = QVBoxLayout(status_frame)
        status_layout.setContentsMargins(24, 10, 24, 20)

        self._status_text = QLabel("Bağlantı bekleniyor")
        self._status_text.setFont(QFont(".AppleSystemUIFont", 11))
        self._status_text.setStyleSheet("color: #64748b; border: none;")
        status_layout.addWidget(self._status_text)

        self._status_bar = QProgressBar()
        self._status_bar.setFixedHeight(4)
        self._status_bar.setTextVisible(False)
        self._status_bar.setStyleSheet("""
            QProgressBar {
                background-color: #E5E5EA;
                border: none;
                border-radius: 2px;
            }
            QProgressBar::chunk {
                background-color: #7196A2;
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
            self._status_text.setText(text or "SİSTEM AKTİF")
            self._status_text.setStyleSheet("color: #34C759; border: none; font-weight: 700; font-size: 10px;")
            self._status_bar.setValue(100)
            self._status_bar.setStyleSheet(self._status_bar.styleSheet().replace("#7196A2", "#34C759"))
        else:
            self._status_text.setText(text or "Çevrimdışı")
            self._status_text.setStyleSheet("color: #64748b; border: none;")
            self._status_bar.setValue(30)
            self._status_bar.setStyleSheet(self._status_bar.styleSheet().replace("#22c55e", "#ef4444"))


class CleanDashboard(QWidget):
    """Modern Dashboard with Activity Feed and Stats"""
    quick_mode_requested = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 40, 32, 32)
        layout.setSpacing(24)

        # Header
        header = QLabel("Sistem Özeti")
        header.setFont(QFont(".AppleSystemUIFont", 32, QFont.Weight.Bold))
        header.setStyleSheet("color: #252F33; border: none; letter-spacing: -0.5px;")
        layout.addWidget(header)

        # Stats Row
        stats_layout = QHBoxLayout()
        stats_layout.setSpacing(20)
        
        self._cpu_card = StatCard("", "0%", "CPU Kullanımı", "#7196A2")
        self._mem_card = StatCard("", "0 MB", "Bellek", "#7196A2")
        self._disk_card = StatCard("", "0%", "Disk Durumu", "#7196A2")
        
        stats_layout.addWidget(self._cpu_card)
        stats_layout.addWidget(self._mem_card)
        stats_layout.addWidget(self._disk_card)
        layout.addLayout(stats_layout)

        # AI Metrics Row (v7.0)
        ai_stats_layout = QHBoxLayout()
        ai_stats_layout.setSpacing(20)
        
        self._latency_card = StatCard("", "0ms", "Yapay Zeka Hızı", "#7196A2")
        self._success_card = StatCard("", "100%", "Başarı Oranı", "#7196A2")
        self._ops_card = StatCard("", "0", "Toplam İşlem", "#7196A2")
        self._domain_card = StatCard("", "general", "Odak Domain", "#7196A2")
        self._cost_card = StatCard("", "$0.00", "Tahmini Maliyet", "#7196A2")
        self._quality_card = StatCard("", "0", "Kalite Skoru", "#7196A2")
        self._pipeline_card = StatCard("", "A:0 H:0", "Pipeline", "#7196A2")
        
        ai_stats_layout.addWidget(self._latency_card)
        ai_stats_layout.addWidget(self._success_card)
        ai_stats_layout.addWidget(self._ops_card)
        ai_stats_layout.addWidget(self._domain_card)
        ai_stats_layout.addWidget(self._cost_card)
        ai_stats_layout.addWidget(self._quality_card)
        ai_stats_layout.addWidget(self._pipeline_card)
        layout.addLayout(ai_stats_layout)

        # Performance Graph (v8.0)
        layout.addWidget(SectionHeader("Performans Trendi"))
        self._latency_graph = LatencyGraph()
        layout.addWidget(self._latency_graph)

        # Suggestions Section (v7.0)
        layout.addWidget(SectionHeader("Senin İçin Önerilenler"))
        
        self._suggestions_frame = QFrame()
        self._suggestions_frame.setStyleSheet("background: #F5F5F7; border-radius: 12px; border: 1px solid #E5E5EA;")
        suggestions_layout = QHBoxLayout(self._suggestions_frame)
        suggestions_layout.setContentsMargins(15, 15, 15, 15)
        suggestions_layout.setSpacing(10)
        
        self._suggestion_btn1 = AnimatedButton("Build", primary=False)
        self._suggestion_btn2 = AnimatedButton("Research", primary=False)
        self._suggestion_btn3 = AnimatedButton("Document", primary=False)
        self._suggestion_btn4 = AnimatedButton("Ship", primary=False)

        suggestions_layout.addWidget(self._suggestion_btn1)
        suggestions_layout.addWidget(self._suggestion_btn2)
        suggestions_layout.addWidget(self._suggestion_btn3)
        suggestions_layout.addWidget(self._suggestion_btn4)
        suggestions_layout.addStretch()
        layout.addWidget(self._suggestions_frame)

        self._suggestion_btn1.clicked.connect(
            lambda: self.quick_mode_requested.emit(
                "build",
                "Build modu: profesyonel bir proje planla, kodu üret, test et ve teslim paketini hazırla.",
            )
        )
        self._suggestion_btn2.clicked.connect(
            lambda: self.quick_mode_requested.emit(
                "research",
                "Research modu: çok kaynaklı derin araştırma yap, riskleri çıkar ve karar özeti oluştur.",
            )
        )
        self._suggestion_btn3.clicked.connect(
            lambda: self.quick_mode_requested.emit(
                "document",
                "Document modu: yönetici özeti, ana rapor ve aksiyon maddeleri içeren profesyonel doküman paketi üret.",
            )
        )
        self._suggestion_btn4.clicked.connect(
            lambda: self.quick_mode_requested.emit(
                "ship",
                "Ship modu: mevcut çalışmayı doğrula, kalite raporu çıkar ve publish-ready teslim çıktısı üret.",
            )
        )

        # Activity Feed Section
        layout.addWidget(SectionHeader("Son Aktiviteler"))
        
        self._activity_frame = QFrame()
        self._activity_frame.setStyleSheet("background: #FFFFFF; border-radius: 12px; border: 1px solid #E5E5EA;")
        activity_layout = QVBoxLayout(self._activity_frame)
        activity_layout.setContentsMargins(2, 2, 2, 2)
        
        self._activity_list = QListWidget()
        self._activity_list.setStyleSheet("""
            QListWidget {
                background: transparent;
                border: none;
                padding: 10px;
            }
            QListWidget::item {
                padding: 4px;
                border-bottom: 1px solid #F5F5F7;
            }
        """)
        activity_layout.addWidget(self._activity_list)
        layout.addWidget(self._activity_frame, 1)
        
        # Add initial activity
        self._add_activity("Sistem başlatıldı", "şimdi")

        # Setup stats timer
        self._stats_timer = QTimer(self)
        self._stats_timer.timeout.connect(self._update_stats)
        self._stats_timer.start(2000)
        self._update_stats()

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

            pipeline = get_pipeline_state().history_summary(window_hours=24)
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

    def _add_activity(self, text: str, time_str: str):
        item = QListWidgetItem()
        widget = FileItem(text, time_str)
        item.setSizeHint(widget.sizeHint())
        self._activity_list.addItem(item)
        self._activity_list.setItemWidget(item, widget)

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
        layout.setContentsMargins(32, 40, 32, 32)
        layout.setSpacing(24)

        # Header
        header = QLabel("Dosya Gezgini")
        header.setFont(QFont(".AppleSystemUIFont", 32, QFont.Weight.Bold))
        header.setStyleSheet("color: #252F33; border: none; letter-spacing: -0.5px;")
        layout.addWidget(header)

        # Actions
        actions_layout = QHBoxLayout()
        actions_layout.setSpacing(12)
        
        self._refresh_btn = AnimatedButton("Yenile", primary=False)
        self._open_btn = AnimatedButton("Dosyayı Aç", primary=True)
        
        # Semantic Toggle (v8.0)
        self._semantic_label = QLabel("SEMANTİK ANALİZ:")
        self._semantic_label.setStyleSheet("color: #8E8E93; font-size: 11px; font-weight: 700; border: none; letter-spacing: 0.5px;")
        self._semantic_toggle = Switch()
        
        actions_layout.addWidget(self._refresh_btn)
        actions_layout.addWidget(self._open_btn)
        actions_layout.addStretch()
        actions_layout.addWidget(self._semantic_label)
        actions_layout.addWidget(self._semantic_toggle)
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
        self._semantic_toggle.toggled.connect(self._on_semantic_toggled)

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
            subprocess.run(["open", path])


class CleanResearchPanel(QWidget):
    """Clean research panel"""
    research_requested = pyqtSignal(str, str, str) # topic, depth, format

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setSpacing(24)

        # Header
        header = QLabel("Araştırma Merkezi")
        header.setFont(QFont(".AppleSystemUIFont", 32, QFont.Weight.Bold))
        header.setStyleSheet("color: #252F33; border: none; letter-spacing: -0.5px;")
        layout.addWidget(header)

        desc = QLabel("Derinlemesine stratejik analizler yapın ve kurumsal raporlar oluşturun")
        desc.setFont(QFont(".AppleSystemUIFont", 14))
        desc.setStyleSheet("color: #8E8E93;")
        layout.addWidget(desc)

        # Input section
        input_group = GlassFrame()
        input_layout = QVBoxLayout(input_group)
        input_layout.setContentsMargins(24, 24, 24, 24)
        input_layout.setSpacing(16)

        topic_label = QLabel("Araştırma Konusu")
        topic_label.setFont(QFont(".AppleSystemUIFont", 13, QFont.Weight.Medium))
        topic_label.setStyleSheet("color: #94a3b8; border: none;")
        input_layout.addWidget(topic_label)

        self._topic_input = QLineEdit()
        self._topic_input.setPlaceholderText("Araştırmak istediğiniz konuyu yazın...")
        self._topic_input.setMinimumHeight(48)
        self._topic_input.setFont(QFont(".AppleSystemUIFont", 14))
        self._topic_input.setStyleSheet("""
            QLineEdit {
                background-color: #F2F2F7;
                border: 1px solid #D1D1D6;
                border-radius: 8px;
                padding: 12px 16px;
                color: #252F33;
            }
            QLineEdit:focus { border-color: #7196A2; background-color: #FFFFFF; }
            QLineEdit::placeholder { color: #8E8E93; }
        """)
        input_layout.addWidget(self._topic_input)

        # Options row
        options_layout = QHBoxLayout()

        depth_label = QLabel("Derinlik:")
        depth_label.setFont(QFont(".AppleSystemUIFont", 13))
        depth_label.setStyleSheet("color: #94a3b8;")
        options_layout.addWidget(depth_label)

        self._depth_combo = QComboBox()
        self._depth_combo.addItems(["Hızlı", "Orta", "Derin"])
        self._depth_combo.setFont(QFont(".AppleSystemUIFont", 13))
        self._depth_combo.setStyleSheet("""
            QComboBox {
                background-color: #F2F2F7;
                border: 1px solid #D1D1D6;
                border-radius: 8px;
                padding: 8px 16px;
                color: #252F33;
                min-width: 120px;
            }
            QComboBox::drop-down { border: none; }
        """)
        options_layout.addWidget(self._depth_combo)

        options_layout.addStretch()

        format_label = QLabel("Format:")
        format_label.setFont(QFont(".AppleSystemUIFont", 13))
        format_label.setStyleSheet("color: #94a3b8;")
        options_layout.addWidget(format_label)

        self._format_combo = QComboBox()
        self._format_combo.addItems(["Markdown", "PDF", "Word"])
        self._format_combo.setFont(QFont(".AppleSystemUIFont", 13))
        self._format_combo.setStyleSheet("""
            QComboBox {
                background-color: #F2F2F7;
                border: 1px solid #D1D1D6;
                border-radius: 8px;
                padding: 8px 16px;
                color: #252F33;
                min-width: 120px;
            }
            QComboBox::drop-down { border: none; }
        """)
        options_layout.addWidget(self._format_combo)

        input_layout.addLayout(options_layout)

        layout.addWidget(input_group)

        # Start button
        self._start_btn = AnimatedButton("Araştırmayı Başlat", primary=True)
        self._start_btn.setMinimumHeight(50)
        self._start_btn.clicked.connect(self._on_start_clicked)
        layout.addWidget(self._start_btn)

        # Results & Charts Row
        results_container = QHBoxLayout()
        results_container.setSpacing(16)

        # Text Results
        text_layout = QVBoxLayout()
        text_layout.addWidget(QLabel("Bulgular"))
        self._results_area = QTextEdit()
        self._results_area.setReadOnly(True)
        self._results_area.setFont(QFont(".AppleSystemUIFont", 13))
        self._results_area.setStyleSheet("""
            QTextEdit {
                background-color: #FFFFFF;
                border: 1px solid #E5E5EA;
                border-radius: 12px;
                padding: 16px;
                color: #252F33;
            }
        """)
        text_layout.addWidget(self._results_area)
        results_container.addLayout(text_layout, 1)

        # Visual Charts
        chart_layout = QVBoxLayout()
        chart_layout.addWidget(QLabel("Görsel Analiz"))
        self._chart_scroll = QScrollArea()
        self._chart_scroll.setWidgetResizable(True)
        self._chart_scroll.setStyleSheet("background: transparent; border: none;")
        
        self._chart_label = QLabel()
        self._chart_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._chart_label.setText("Grafikler burada görünecek")
        self._chart_label.setStyleSheet("color: #71717a; background: rgba(0,0,0,0.2); border-radius: 12px;")
        self._chart_scroll.setWidget(self._chart_label)
        
        chart_layout.addWidget(self._chart_scroll)
        results_container.addLayout(chart_layout, 1)

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


        locations_layout.setContentsMargins(16, 16, 16, 16)
        locations_layout.setSpacing(12)

        locations = [
            ("Masaüstü", "~/Desktop"),
            ("Belgeler", "~/Documents"),
            ("İndirilenler", "~/Downloads"),
            ("Resimler", "~/Pictures"),
        ]

        for name, path in locations:
            btn = QPushButton(name)
            btn.setFont(QFont(".AppleSystemUIFont", 13))
            btn.setMinimumHeight(40)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #0f172a;
                    color: #e2e8f0;
                    border: 1px solid #334155;
                    border-radius: 8px;
                    padding: 0 20px;
                }
                QPushButton:hover {
                    background-color: rgba(0, 0, 0, 0.05);
                    border-color: #3b82f6;
                }
            """)
            locations_layout.addWidget(btn)

        layout.addWidget(locations_frame)

        # Actions
        actions_frame = GlassFrame()
        actions_layout = QVBoxLayout(actions_frame)
        actions_layout.setContentsMargins(20, 20, 20, 20)
        actions_layout.setSpacing(12)

        actions_title = QLabel("Hızlı İşlemler")
        actions_title.setFont(QFont(".AppleSystemUIFont", 14, QFont.Weight.Medium))
        actions_title.setStyleSheet("color: #0f172a;")
        actions_layout.addWidget(actions_title)

        actions = [
            ("Dosya Ara", "Bilgisayarınızda dosya arayın"),
            ("Dosyaları Düzenle", "Klasördeki dosyaları türe göre düzenleyin"),
            ("Yedekle", "Seçili dosyaları yedekleyin"),
            ("Sıkıştır", "Dosyaları ZIP olarak sıkıştırın"),
        ]

        for name, desc_text in actions:
            action_btn = QPushButton()
            action_btn.setMinimumHeight(60)
            action_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            action_btn.setStyleSheet("""
                QPushButton {
                    background-color: #0f172a;
                    border: 1px solid #334155;
                    border-radius: 8px;
                    text-align: left;
                    padding: 12px 16px;
                }
                QPushButton:hover {
                    border-color: #3b82f6;
                }
            """)

            btn_layout = QVBoxLayout(action_btn)
            btn_layout.setContentsMargins(0, 0, 0, 0)
            btn_layout.setSpacing(4)

            btn_name = QLabel(name)
            btn_name.setFont(QFont(".AppleSystemUIFont", 13, QFont.Weight.Medium))
            btn_name.setStyleSheet("color: #0f172a;")
            btn_layout.addWidget(btn_name)

            btn_desc = QLabel(desc_text)
            btn_desc.setFont(QFont(".AppleSystemUIFont", 11))
            btn_desc.setStyleSheet("color: #64748b;")
            btn_layout.addWidget(btn_desc)

            actions_layout.addWidget(action_btn)

        layout.addWidget(actions_frame)
        layout.addStretch()


class CleanSettingsPanel(QWidget):
    """Settings panel wrapper that uses full professional Settings UI."""

    def __init__(self, parent=None):
        super().__init__(parent)
        from config.settings_manager import SettingsPanel as SettingsManager
        from ui.settings_panel_ui import SettingsPanelUI
        self._settings_manager = SettingsManager()
        self._full_settings_ui = SettingsPanelUI(config=self._settings_manager._settings)
        self._full_settings_ui.settings_changed.connect(self._on_settings_changed)
        self._setup_ui()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(self._full_settings_ui)

    def _on_settings_changed(self, settings: dict):
        try:
            if isinstance(settings, dict) and settings:
                self._settings_manager.update(settings)
        except Exception as exc:
            logger.error(f"Settings update failed: {exc}")


class CleanAdvancedPanel(QWidget):
    """Advanced system panel for logs and technical info"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 40, 32, 32)
        layout.setSpacing(24)

        # Header
        header = QLabel("Sistem Denetimi")
        header.setFont(QFont(".AppleSystemUIFont", 32, QFont.Weight.Bold))
        header.setStyleSheet("color: #252F33; border: none; letter-spacing: -0.5px;")
        layout.addWidget(header)

        # Log Section
        layout.addWidget(SectionHeader("Uygulama Logları"))
        
        self._log_area = QTextEdit()
        self._log_area.setReadOnly(True)
        self._log_area.setFont(QFont("SF Mono", 11))
        self._log_area.setStyleSheet("""
            QTextEdit {
                background-color: #F8FAFC;
                border: 1px solid #E2E8F0;
                border-radius: 12px;
                padding: 12px;
                color: #334155;
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
        info_label.setStyleSheet("color: #94a3b8; font-family: 'SF Mono';")
        info_layout.addWidget(info_label)
        
        layout.addWidget(info_frame)


class CleanMainWindow(QMainWindow):
    """Clean main application window"""

    def __init__(self):
        super().__init__()
        self._bot_worker = BotWorker()
        
        self.setWindowTitle("Elyan v24.0 Pro")
        self.setWindowIcon(load_brand_icon(size=128))
        self.setMinimumSize(1180, 760)
        self.resize(1320, 840)

        self._config = self._load_config()
        self._setup_ui()
        self._setup_tray()

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
            self._chat_widget.add_message("User", user_input)
            self._chat_widget.add_message("Elyan", result)

    def _on_thought_notified(self, thought: str):
        """Display live reasoning thoughts"""
        if hasattr(self, "_chat_widget"):
            # Use a special reasoning style/prefix
            self._chat_widget.add_message("Elyan Reasoning", thought)
        self._dashboard._add_activity(f"Düşünce: {thought[:40]}...", "şimdi")

    def _on_screenshot_shown(self, path: str, message: str):
        """Handle visual verification display"""
        self._dashboard._add_activity(f"Görsel Doğrulama: {message}", "şimdi")
        # In the future, we could pop up the screenshot or show it in chat
        if hasattr(self, "_chat_widget"):
             self._chat_widget.add_message("System", f"📷 {message}\nDosya: {path}")

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
        self.setCentralWidget(central)

        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Sidebar
        self._sidebar = CleanSidebar()
        self._sidebar.page_changed.connect(self._on_page_changed)
        main_layout.addWidget(self._sidebar)

        # Main container for content with background
        self._main_container = QWidget()
        self._main_container_layout = QVBoxLayout(self._main_container)
        self._main_container_layout.setContentsMargins(0, 0, 0, 0)
        
        # Content stack
        self._content_stack = QStackedWidget()
        self._content_stack.setStyleSheet("background-color: transparent;")
        self._main_container_layout.addWidget(self._content_stack)
        
        main_layout.addWidget(self._main_container, 1)

        # Import and add pages
        from ui.clean_chat_widget import CleanChatWidget

        self._dashboard = CleanDashboard()
        self._dashboard.quick_mode_requested.connect(self._on_quick_mode_requested)
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

    def _apply_theme(self):
        # Stronger, cleaner visual identity for desktop UI.
        self.setStyleSheet("""
            QWidget#central_widget {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                            stop:0 #F8FBFF, stop:0.45 #F4F7FB, stop:1 #EEF3FA);
            }
            QMainWindow {
                background: transparent;
            }
            QStackedWidget {
                background: transparent;
            }
            QScrollArea {
                border: none;
                background: transparent;
            }
            QLineEdit, QComboBox, QSpinBox, QTextEdit, QListView, QListWidget {
                background: #FFFFFF;
                border: 1px solid #D9E2EC;
                border-radius: 12px;
                padding: 8px 10px;
                color: #1E293B;
                font-family: ".AppleSystemUIFont";
                font-size: 13px;
            }
            QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QTextEdit:focus {
                border: 1px solid #0F9AFE;
            }
            QPushButton {
                background: #0F9AFE;
                color: #FFFFFF;
                border: none;
                border-radius: 11px;
                padding: 9px 14px;
                font-family: ".AppleSystemUIFont";
                font-size: 13px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: #0B84D9;
            }
            QPushButton:pressed {
                background: #096DB4;
            }
            QLabel {
                color: #0F172A;
            }
        """)

    def _setup_tray(self):
        self._tray = QSystemTrayIcon(self)
        tray_icon = load_brand_icon(size=64)
        if not tray_icon.isNull():
            self._tray.setIcon(tray_icon)

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

    def _on_error(self, error: str):
        QMessageBox.warning(self, "Hata", f"Bot hatası: {error}")

    def _start_bot(self):
        self._bot_worker.start()

    async def _process_message(self, message: str, notify: Optional[Callable] = None, **kwargs) -> str:
        """Process incoming messages from UI with explicit bridge support"""
        if self._bot_worker and self._bot_worker._agent:
            return await self._bot_worker.process_message(message)
        return "Bot henüz hazır değil. Lütfen bekleyin..."

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show()
            self.activateWindow()

    def _quit_app(self):
        self._bot_worker.stop()
        QApplication.quit()

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
    app.setApplicationName("Elyan")
    app.setApplicationVersion("24.0.0")

    # Setup detection (provider-aware, not just .env presence)
    if not _is_llm_configured():
        from ui.wizard_entry import SetupWizard
        logger.info(f"Setup wizard selected: {SetupWizard.__module__}.{SetupWizard.__name__}")
        wizard = SetupWizard()
        
        def start_main_app(config):
            # Save config to .env (handled inside wizard or here)
            window = CleanMainWindow()
            window.show()
            
        wizard.finished.connect(start_main_app)
        wizard.show()
        return app.exec()

    # Normal startup
    window = CleanMainWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
