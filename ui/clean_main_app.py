"""
Clean Main Application - Professional desktop app without emojis
Minimal, clean and modern design
"""

import sys
import os
import asyncio
import json
from pathlib import Path
from typing import Optional, List, Dict, Any, Callable
import psutil
from core.monitoring import get_monitoring

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QThread, QPropertyAnimation, QEasingCurve, QSize, QObject
from PyQt6.QtGui import QIcon, QPixmap, QAction, QFont, QColor, QPalette, QFileSystemModel
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QLabel, QPushButton, QFrame, QStackedWidget, QScrollArea, 
    QSystemTrayIcon, QMenu, QMessageBox, QLineEdit, QComboBox, 
    QSlider, QSpinBox, QFileDialog, QGraphicsOpacityEffect, QListView,
    QProgressBar, QListWidget, QListWidgetItem, QTextEdit
)
from ui.components import (
    SidebarButton, GlassFrame, StatCard, FileItem, Switch, 
    SectionHeader, Divider, LatencyGraph, AnimatedButton, PulseLabel
)
from ui.branding import load_brand_icon

from utils.logger import get_logger

logger = get_logger("clean_main_app")


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
    research_finished = pyqtSignal(str) # result text

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
        TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
        if not TELEGRAM_TOKEN or TELEGRAM_TOKEN == "YOUR_TOKEN_HERE":
            logger.warning("Telegram token bulunamadı, bot başlatılamıyor")
            return

        try:
            # Silent token validation
            import httpx
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getMe")
                if resp.status_code != 200:
                    logger.error(f"Geçersiz Telegram Token: {resp.status_code}")
                    return
            
            from telegram.ext import ApplicationBuilder
            from handlers.telegram_handler import setup_handlers

            self._telegram_app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
            setup_handlers(self._telegram_app, self._agent)

            await self._telegram_app.initialize()
            await self._telegram_app.start()
            await self._telegram_app.updater.start_polling(drop_pending_updates=True)
            self.activity_logged.emit("Telegram botu aktif edildi ve dinlemeye başladı", "şimdi")
            logger.info("Telegram botu başarıyla başlatıldı ve polling yapıyor")
        except Exception as e:
            logger.error(f"Telegram bot başlatma hatası: {e}")

    async def process_message(self, message: str) -> str:
        """Process a message through the agent"""
        if self._agent is None:
            return "Bot henüz başlatılmadı. Lütfen bekleyin."

        try:
            self.activity_logged.emit(f"Kullanıcı mesajı işleniyor: {message[:30]}...", "şimdi")
            response = await self._agent.process(message)
            self.activity_logged.emit("İşlem başarıyla tamamlandı", "şimdi")
            return response
        except Exception as e:
            logger.error(f"Message processing error: {e}")
            return f"Hata oluştu: {str(e)}"

    def trigger_research(self, topic: str, depth: str, fmt: str):
        """Trigger background research"""
        if self._loop:
            self._loop.create_task(self._run_research(topic, depth, fmt))

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
        logo_frame.setFixedHeight(120)
        logo_frame.setStyleSheet("background: transparent; border: none;")
        logo_layout = QVBoxLayout(logo_frame)
        logo_layout.setContentsMargins(32, 48, 24, 24)

        logo_text = QLabel("Wiqo")
        logo_text.setFont(QFont("SF Pro Display", 32, QFont.Weight.Bold))
        logo_text.setStyleSheet("color: #252F33; border: none; letter-spacing: -1px;")
        logo_layout.addWidget(logo_text)
        
        logo_sub = QLabel("Strategic Digital Companion")
        logo_sub.setFont(QFont("SF Pro Text", 11, QFont.Weight.Medium))
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
        self._status_text.setFont(QFont("SF Pro Text", 11))
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

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 40, 32, 32)
        layout.setSpacing(24)

        # Header
        header = QLabel("Sistem Özeti")
        header.setFont(QFont("SF Pro Display", 32, QFont.Weight.Bold))
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
        
        ai_stats_layout.addWidget(self._latency_card)
        ai_stats_layout.addWidget(self._success_card)
        ai_stats_layout.addWidget(self._ops_card)
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
        
        self._suggestion_btn1 = AnimatedButton("Doküman Özetle", primary=False)
        self._suggestion_btn2 = AnimatedButton("Güvenlik Taraması", primary=False)
        self._suggestion_btn3 = AnimatedButton("Verimlilik Analizi", primary=False)
        
        suggestions_layout.addWidget(self._suggestion_btn1)
        suggestions_layout.addWidget(self._suggestion_btn2)
        suggestions_layout.addWidget(self._suggestion_btn3)
        suggestions_layout.addStretch()
        layout.addWidget(self._suggestions_frame)

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
        header.setFont(QFont("SF Pro Display", 32, QFont.Weight.Bold))
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
        header.setFont(QFont("SF Pro Display", 32, QFont.Weight.Bold))
        header.setStyleSheet("color: #252F33; border: none; letter-spacing: -0.5px;")
        layout.addWidget(header)

        desc = QLabel("Derinlemesine stratejik analizler yapın ve kurumsal raporlar oluşturun")
        desc.setFont(QFont("SF Pro Text", 14))
        desc.setStyleSheet("color: #8E8E93;")
        layout.addWidget(desc)

        # Input section
        input_group = GlassFrame()
        input_layout = QVBoxLayout(input_group)
        input_layout.setContentsMargins(24, 24, 24, 24)
        input_layout.setSpacing(16)

        topic_label = QLabel("Araştırma Konusu")
        topic_label.setFont(QFont("SF Pro Text", 13, QFont.Weight.Medium))
        topic_label.setStyleSheet("color: #94a3b8; border: none;")
        input_layout.addWidget(topic_label)

        self._topic_input = QLineEdit()
        self._topic_input.setPlaceholderText("Araştırmak istediğiniz konuyu yazın...")
        self._topic_input.setMinimumHeight(48)
        self._topic_input.setFont(QFont("SF Pro Text", 14))
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
        depth_label.setFont(QFont("SF Pro Text", 13))
        depth_label.setStyleSheet("color: #94a3b8;")
        options_layout.addWidget(depth_label)

        self._depth_combo = QComboBox()
        self._depth_combo.addItems(["Hızlı", "Orta", "Derin"])
        self._depth_combo.setFont(QFont("SF Pro Text", 13))
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
        format_label.setFont(QFont("SF Pro Text", 13))
        format_label.setStyleSheet("color: #94a3b8;")
        options_layout.addWidget(format_label)

        self._format_combo = QComboBox()
        self._format_combo.addItems(["Markdown", "PDF", "Word"])
        self._format_combo.setFont(QFont("SF Pro Text", 13))
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
        self._results_area.setFont(QFont("SF Pro Text", 13))
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
            btn.setFont(QFont("SF Pro Text", 13))
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
        actions_title.setFont(QFont("SF Pro Text", 14, QFont.Weight.Medium))
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
            btn_name.setFont(QFont("SF Pro Text", 13, QFont.Weight.Medium))
            btn_name.setStyleSheet("color: #0f172a;")
            btn_layout.addWidget(btn_name)

            btn_desc = QLabel(desc_text)
            btn_desc.setFont(QFont("SF Pro Text", 11))
            btn_desc.setStyleSheet("color: #64748b;")
            btn_layout.addWidget(btn_desc)

            actions_layout.addWidget(action_btn)

        layout.addWidget(actions_frame)
        layout.addStretch()


class CleanAIPanel(QWidget):
    """Clean AI/Ollama settings panel"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: transparent;
            }
        """)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setSpacing(24)

        # Header
        header = QLabel("Yapay Zeka")
        header.setFont(QFont("SF Pro Display", 32, QFont.Weight.Bold))
        header.setStyleSheet("color: #252F33; border: none; letter-spacing: -0.5px;")
        layout.addWidget(header)

        desc = QLabel("Ollama ve model ayarlarını yapılandırın")
        desc.setFont(QFont("SF Pro Text", 14))
        desc.setStyleSheet("color: #64748b;")
        layout.addWidget(desc)

        # Status card
        status_card = GlassFrame()
        status_layout = QHBoxLayout(status_card)
        status_layout.setContentsMargins(24, 20, 24, 20)

        self._ollama_status = QLabel("Ollama durumu kontrol ediliyor...")
        self._ollama_status.setFont(QFont("SF Pro Text", 14))
        self._ollama_status.setStyleSheet("color: #94a3b8; border: none;")
        status_layout.addWidget(self._ollama_status)

        status_layout.addStretch()

        start_btn = QPushButton("Başlat")
        start_btn.setFont(QFont("SF Pro Text", 13))
        start_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        start_btn.setStyleSheet("""
            QPushButton {
                background-color: #22c55e;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 8px 20px;
            }
            QPushButton:hover { background-color: #16a34a; }
        """)
        status_layout.addWidget(start_btn)

        layout.addWidget(status_card)

        # Model settings
        model_frame = GlassFrame()
        model_layout = QVBoxLayout(model_frame)
        model_layout.setContentsMargins(24, 24, 24, 24)
        model_layout.setSpacing(16)

        model_title = QLabel("Model Ayarları")
        model_title.setFont(QFont("SF Pro Text", 15, QFont.Weight.Medium))
        model_title.setStyleSheet("color: #0F172A; border: none;")
        model_layout.addWidget(model_title)

        # Model selection
        model_row = QHBoxLayout()
        model_label = QLabel("Model:")
        model_label.setFont(QFont("SF Pro Text", 13))
        model_label.setStyleSheet("color: #94a3b8;")
        model_label.setFixedWidth(120)
        model_row.addWidget(model_label)

        self._model_combo = QComboBox()
        self._model_combo.addItems(["llama3.2:3b", "llama3.2:1b", "llama3.1:8b", "mistral", "codellama"])
        self._model_combo.setFont(QFont("SF Pro Text", 13))
        self._model_combo.setStyleSheet("""
            QComboBox {
                background-color: #F8FAFC;
                border: 1px solid #E2E8F0;
                border-radius: 8px;
                padding: 10px 16px;
                color: #0F172A;
            }
            QComboBox::drop-down { border: none; }
        """)
        model_row.addWidget(self._model_combo, 1)
        model_layout.addLayout(model_row)

        # Temperature
        temp_row = QHBoxLayout()
        temp_label = QLabel("Sıcaklık:")
        temp_label.setFont(QFont("SF Pro Text", 13))
        temp_label.setStyleSheet("color: #94a3b8;")
        temp_label.setFixedWidth(120)
        temp_row.addWidget(temp_label)

        self._temp_slider = QSlider(Qt.Orientation.Horizontal)
        self._temp_slider.setRange(0, 100)
        self._temp_slider.setValue(70)
        self._temp_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                background: #27272a;
                height: 4px;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #fafafa;
                width: 16px;
                height: 16px;
                margin: -6px 0;
                border-radius: 8px;
            }
            QSlider::sub-page:horizontal {
                background: #fafafa;
                border-radius: 2px;
            }
        """)
        temp_row.addWidget(self._temp_slider, 1)

        self._temp_value = QLabel("0.7")
        self._temp_value.setFont(QFont("SF Pro Text", 13))
        self._temp_value.setStyleSheet("color: #94a3b8;")
        self._temp_value.setFixedWidth(40)
        temp_row.addWidget(self._temp_value)

        self._temp_slider.valueChanged.connect(
            lambda v: self._temp_value.setText(f"{v/100:.1f}")
        )
        model_layout.addLayout(temp_row)

        # Max tokens
        tokens_row = QHBoxLayout()
        tokens_label = QLabel("Max Token:")
        tokens_label.setFont(QFont("SF Pro Text", 13))
        tokens_label.setStyleSheet("color: #94a3b8;")
        tokens_label.setFixedWidth(120)
        tokens_row.addWidget(tokens_label)

        self._tokens_spin = QSpinBox()
        self._tokens_spin.setRange(256, 8192)
        self._tokens_spin.setValue(2048)
        self._tokens_spin.setFont(QFont("SF Pro Text", 13))
        self._tokens_spin.setStyleSheet("""
            QSpinBox {
                background-color: #F8FAFC;
                border: 1px solid #E2E8F0;
                border-radius: 8px;
                padding: 10px 16px;
                color: #0F172A;
            }
        """)
        tokens_row.addWidget(self._tokens_spin, 1)
        model_layout.addLayout(tokens_row)

        layout.addWidget(model_frame)

        # Install new model
        install_frame = GlassFrame()
        install_layout = QVBoxLayout(install_frame)
        install_layout.setContentsMargins(24, 24, 24, 24)
        install_layout.setSpacing(16)

        install_title = QLabel("Yeni Model Yükle")
        install_title.setFont(QFont("SF Pro Text", 15, QFont.Weight.Medium))
        install_title.setStyleSheet("color: #0F172A; border: none;")
        install_layout.addWidget(install_title)

        install_row = QHBoxLayout()

        self._install_input = QLineEdit()
        self._install_input.setPlaceholderText("Model adı (örn: phi3)")
        self._install_input.setFont(QFont("SF Pro Text", 13))
        self._install_input.setMinimumHeight(44)
        self._install_input.setStyleSheet("""
            QLineEdit {
                background-color: #F8FAFC;
                border: 1px solid #E2E8F0;
                border-radius: 8px;
                padding: 10px 16px;
                color: #0F172A;
            }
            QLineEdit:focus { border-color: #3b82f6; }
            QLineEdit::placeholder { color: #94a3b8; }
        """)
        install_row.addWidget(self._install_input, 1)

        install_btn = QPushButton("Yükle")
        install_btn.setFont(QFont("SF Pro Text", 13, QFont.Weight.Medium))
        install_btn.setMinimumHeight(44)
        install_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        install_btn.setStyleSheet("""
            QPushButton {
                background-color: #0F172A;
                color: #ffffff;
                border: none;
                border-radius: 8px;
                padding: 0 24px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #1E293B; }
        """)
        install_row.addWidget(install_btn)

        install_layout.addLayout(install_row)
        layout.addWidget(install_frame)

        # About Wiqo Section (v9.0)
        about_frame = GlassFrame()
        about_layout = QVBoxLayout(about_frame)
        about_layout.setContentsMargins(24, 24, 24, 24)
        about_layout.setSpacing(12)

        about_title = QLabel("Wiqo Hakkında")
        about_title.setFont(QFont("SF Pro Display", 18, QFont.Weight.Bold))
        about_title.setStyleSheet("color: #0F172A; border: none;")
        about_layout.addWidget(about_title)

        about_text = QLabel(
            "Wiqo v8.0 - Otonom Stratejik Eşlikçi\n\n"
            "Wiqo, yapay zeka ve sistem entegrasyonunu birleştiren, "
            "kullanıcısının ihtiyaçlarını anlayan ve otonom çözümler üreten "
            "yeni nesil bir dijital asistan ekosistemidir.\n\n"
            "• Adaptif Persona Zekası\n"
            "• Multimodal Analiz & Raporlama\n"
            "• Derin Araştırma Motoru\n"
            "• Gerçek Zamanlı Sistem Monitoring"
        )
        about_text.setFont(QFont("SF Pro Text", 12))
        about_text.setStyleSheet("color: #94a3b8; line-height: 1.5;")
        about_text.setWordWrap(True)
        about_layout.addWidget(about_text)

        layout.addWidget(about_frame)

        layout.addStretch()

        scroll.setWidget(content)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(scroll)


class CleanSettingsPanel(QWidget):
    """Clean settings panel with real logic integration"""

    def __init__(self, parent=None):
        super().__init__(parent)
        from ui.settings_panel import SettingsPanel
        self._settings = SettingsPanel()
        self._setup_ui()

    def _setup_ui(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background-color: transparent; }")

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setSpacing(24)

        # Header
        header = QLabel("Tercihler")
        header.setFont(QFont("SF Pro Display", 32, QFont.Weight.Bold))
        header.setStyleSheet("color: #252F33; border: none; letter-spacing: -0.5px;")
        layout.addWidget(header)

        # General Section
        general_section = GlassFrame()
        general_layout = QVBoxLayout(general_section)
        general_layout.setContentsMargins(24, 24, 24, 24)
        general_layout.setSpacing(16)

        general_layout.addWidget(SectionHeader("Genel Yapılandırma"))

        # Theme
        theme_combo = self._create_combo(["Sistem", "Koyu", "Açık"])
        theme_combo.setCurrentText(self._settings.get("ui_theme", "Sistem"))
        theme_combo.currentTextChanged.connect(lambda v: self._settings.set("ui_theme", v))
        general_layout.addWidget(self._create_setting_row("Tema", "Uygulama görünümü", theme_combo))

        general_layout.addWidget(Divider())

        # Notifications
        notif_switch = Switch(self._settings.get("notifications_enabled", True))
        notif_switch.toggled.connect(lambda v: self._settings.set("notifications_enabled", v))
        general_layout.addWidget(self._create_setting_row("Bildirimler", "Masaüstü bildirimlerini etkinleştir", notif_switch))

        layout.addWidget(general_section)

        # Privacy Section
        privacy_section = GlassFrame()
        privacy_layout = QVBoxLayout(privacy_section)
        privacy_layout.setContentsMargins(24, 24, 24, 24)
        privacy_layout.setSpacing(16)

        privacy_layout.addWidget(SectionHeader("Güvenlik ve Gizlilik"))

        # Public Access
        public_switch = Switch(self._settings.get("public_access", False))
        public_switch.toggled.connect(lambda v: self._settings.set("public_access", v))
        privacy_layout.addWidget(self._create_setting_row("Genel Erişim", "Herkesin botu kullanmasına izin ver", public_switch))

        layout.addWidget(privacy_section)

        # Advanced Section
        adv_section = GlassFrame()
        adv_layout = QVBoxLayout(adv_section)
        adv_layout.setContentsMargins(24, 24, 24, 24)
        adv_layout.setSpacing(16)
        
        adv_layout.addWidget(SectionHeader("Gelişmiş"))
        
        # Cache
        cache_switch = Switch(self._settings.get("cache_enabled", True))
        cache_switch.toggled.connect(lambda v: self._settings.set("cache_enabled", v))
        adv_layout.addWidget(self._create_setting_row("Önbellek", "Daha hızlı yanıt için önbelleği aktif et", cache_switch))

        layout.addWidget(adv_section)
        layout.addStretch()

        scroll.setWidget(content)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(scroll)

    def _create_setting_row(self, title: str, desc: str, control: QWidget) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 4, 0, 4)

        text_layout = QVBoxLayout()
        t_label = QLabel(title)
        t_label.setFont(QFont("SF Pro Text", 13, QFont.Weight.Medium))
        t_label.setStyleSheet("color: #0F172A; border: none;")
        text_layout.addWidget(t_label)

        d_label = QLabel(desc)
        d_label.setFont(QFont("SF Pro Text", 11))
        d_label.setStyleSheet("color: #64748b; border: none;")
        text_layout.addWidget(d_label)

        layout.addLayout(text_layout, 1)
        layout.addWidget(control)
        return row

    def _create_combo(self, items: list) -> QComboBox:
        combo = QComboBox()
        combo.addItems(items)
        combo.setStyleSheet("""
            QComboBox {
                background-color: #F8FAFC;
                border: 1px solid #E2E8F0;
                border-radius: 8px;
                padding: 6px 12px;
                color: #0F172A;
                min-width: 120px;
            }
        """)
        return combo


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
        header.setFont(QFont("SF Pro Display", 32, QFont.Weight.Bold))
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
        
        self.setWindowTitle("Wiqo")
        self.setMinimumSize(900, 600)

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
            self._chat_widget.add_message("Wiqo", result)

    def _on_thought_notified(self, thought: str):
        """Display live reasoning thoughts"""
        if hasattr(self, "_chat_widget"):
            # Use a special reasoning style/prefix
            self._chat_widget.add_message("Wiqo Reasoning", thought)
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
        config_file = Path.home() / ".wiqo" / "config.json"
        if config_file.exists():
            try:
                with open(config_file, 'r') as f:
                    return json.load(f)
            except:
                pass
        return {}

    def _setup_ui(self):
        central = QWidget()
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

        main_layout.addWidget(self._content_stack, 1)

        self._apply_theme()

    def _apply_theme(self):
        from ui.themes import get_theme, generate_stylesheet
        theme = get_theme("WIQO_WHITE")
        stylesheet = generate_stylesheet(theme)
        self.setStyleSheet(stylesheet)
        
        # Professional Light Mode Background
        self.centralWidget().setStyleSheet("""
            QWidget#central_widget {
                background-color: #ffffff;
            }
        """)
        self.centralWidget().setObjectName("central_widget")

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
        # Add a simple fade animation
        current_widget = self._content_stack.widget(index)
        opacity_effect = QGraphicsOpacityEffect(current_widget)
        current_widget.setGraphicsEffect(opacity_effect)
        
        self._anim = QPropertyAnimation(opacity_effect, b"opacity")
        self._anim.setDuration(400)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        
        self._content_stack.setCurrentIndex(index)
        self._anim.start()
        
        # Ensure focus is cleared to avoid input box issues
        self.setFocus()

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
    app.setApplicationName("Wiqo")
    app.setApplicationVersion("8.0.0")

    # First-run detection (v10.0)
    env_path = Path(__file__).parent.parent / ".env"
    
    if not env_path.exists():
        from ui.wizard_entry import SetupWizard
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
