"""
Elyan Enhanced Setup Wizard v24.0 - Professional AI Configuration
With Ollama Installation Support, Provider Comparison, and Connection Testing
"""

import os
import sys
import subprocess
import urllib.request
import platform
from pathlib import Path
from typing import Optional, Dict, Any

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QStackedWidget,
    QLineEdit, QPushButton, QFrame, QProgressBar, QApplication,
    QDialog, QComboBox, QMessageBox, QTextEdit, QCheckBox,
    QRadioButton, QButtonGroup, QScrollArea
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread, QTimer
from PyQt6.QtGui import QFont, QColor

from ui.components import GlassFrame, AnimatedButton, SectionHeader, PulseLabel
from utils.logger import get_logger

logger = get_logger("enhanced_setup_wizard")

# ── Provider definitions with detailed comparison ──────────────
PROVIDERS = {
    "groq": {
        "name": "Groq",
        "desc": "Ultra-hızlı bulut API",
        "badge": "🎁 Ücretsiz",
        "badge_color": "#34C759",
        "needs_key": True,
        "speed": "⚡⚡⚡",
        "quality": "⭐⭐⭐⭐",
        "cost": "Ücretsiz (Sınırlı)",
        "privacy": "Orta (Bulut)",
        "models": ["llama-3.3-70b-versatile", "mixtral-8x7b-32768", "llama-3.1-8b-instant"],
        "env_key": "GROQ_API_KEY",
        "llm_type": "groq",
        "signup_url": "https://console.groq.com/keys",
    },
    "gemini": {
        "name": "Google Gemini",
        "desc": "Güçlü ve çok yönlü AI",
        "badge": "🎁 Ücretsiz",
        "badge_color": "#34C759",
        "needs_key": True,
        "speed": "⚡⚡",
        "quality": "⭐⭐⭐⭐⭐",
        "cost": "Ücretsiz (Sınırlı)",
        "privacy": "Orta (Google)",
        "models": ["gemini-2.0-flash", "gemini-1.5-pro", "gemini-1.5-flash"],
        "env_key": "GOOGLE_API_KEY",
        "llm_type": "api",
        "signup_url": "https://makersuite.google.com/app/apikey",
    },
    "openai": {
        "name": "OpenAI",
        "desc": "En güçlü GPT modelleri",
        "badge": "💳 Ücretli",
        "badge_color": "#FF9500",
        "needs_key": True,
        "speed": "⚡⚡",
        "quality": "⭐⭐⭐⭐⭐",
        "cost": "Ücretli ($$$)",
        "privacy": "Orta (OpenAI)",
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"],
        "env_key": "OPENAI_API_KEY",
        "llm_type": "openai",
        "signup_url": "https://platform.openai.com/api-keys",
    },
    "ollama": {
        "name": "Ollama (Yerel)",
        "desc": "Bilgisayarınızda çalışır",
        "badge": "🔒 Gizli",
        "badge_color": "#7196A2",
        "needs_key": False,
        "speed": "⚡",
        "quality": "⭐⭐⭐",
        "cost": "Tamamen Ücretsiz",
        "privacy": "Yüksek (Yerel)",
        "models": [],  # Dynamically populated
        "env_key": None,
        "llm_type": "ollama",
        "signup_url": None,
    },
}


class OllamaInstallThread(QThread):
    """Background thread for Ollama installation"""
    progress = pyqtSignal(int, str)  # (percent, message)
    finished_signal = pyqtSignal(bool, str)  # (success, message)

    def __init__(self, model_name="llama3.2:3b"):
        super().__init__()
        self.model_name = model_name

    def run(self):
        try:
            # Check if Ollama is already installed
            self.progress.emit(10, "Ollama kontrolü yapılıyor...")
            try:
                result = subprocess.run(["ollama", "--version"], capture_output=True, timeout=5)
                if result.returncode == 0:
                    self.progress.emit(30, "Ollama zaten kurulu!")
                else:
                    raise FileNotFoundError
            except (FileNotFoundError, subprocess.TimeoutExpired):
                # Ollama not installed
                self.progress.emit(30, "Ollama kurulu değil. Kurulum başlatılıyor...")

                # Download and install Ollama
                system = platform.system()
                if system == "Darwin":  # macOS
                    self.progress.emit(40, "Ollama indiriliyor...")
                    install_cmd = "curl -fsSL https://ollama.com/install.sh | sh"
                    subprocess.run(install_cmd, shell=True, check=True, timeout=300)
                    self.progress.emit(60, "Ollama kuruldu!")
                else:
                    self.finished_signal.emit(False, "Sadece macOS desteklenmektedir.")
                    return

            # Pull the specified model
            self.progress.emit(70, f"{self.model_name} modeli indiriliyor...")
            pull_process = subprocess.Popen(
                ["ollama", "pull", self.model_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )

            for line in pull_process.stdout:
                if "pulling" in line.lower():
                    self.progress.emit(80, f"Model indiriliyor: {line.strip()}")
                elif "success" in line.lower():
                    self.progress.emit(90, "Model başarıyla indirildi!")

            pull_process.wait()

            if pull_process.returncode == 0:
                self.progress.emit(100, "Kurulum tamamlandı!")
                self.finished_signal.emit(True, f"{self.model_name} başarıyla kuruldu!")
            else:
                self.finished_signal.emit(False, "Model indirme hatası.")

        except Exception as e:
            logger.error(f"Ollama installation error: {e}")
            self.finished_signal.emit(False, f"Hata: {str(e)}")


class ConnectionTestThread(QThread):
    """Background thread for testing API/Ollama connection"""
    finished_signal = pyqtSignal(bool, str)  # (success, message)

    def __init__(self, provider: str, api_key: str = "", model: str = ""):
        super().__init__()
        self.provider = provider
        self.api_key = api_key
        self.model = model

    def run(self):
        try:
            if self.provider == "groq":
                self._test_groq()
            elif self.provider == "gemini":
                self._test_gemini()
            elif self.provider == "openai":
                self._test_openai()
            elif self.provider == "ollama":
                self._test_ollama()
            else:
                self.finished_signal.emit(False, "Bilinmeyen provider")
        except Exception as e:
            self.finished_signal.emit(False, f"Bağlantı hatası: {str(e)}")

    def _test_groq(self):
        import httpx
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        data = {
            "model": "llama-3.3-70b-versatile",
            "messages": [{"role": "user", "content": "test"}],
            "max_tokens": 10
        }
        with httpx.Client(timeout=10.0) as client:
            response = client.post(url, json=data, headers=headers)
            if response.status_code == 200:
                self.finished_signal.emit(True, "✅ Groq bağlantısı başarılı!")
            else:
                self.finished_signal.emit(False, f"Groq hatası: {response.status_code}")

    def _test_gemini(self):
        import httpx
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={self.api_key}"
        data = {"contents": [{"parts": [{"text": "test"}]}]}
        with httpx.Client(timeout=10.0) as client:
            response = client.post(url, json=data)
            if response.status_code == 200:
                self.finished_signal.emit(True, "✅ Gemini bağlantısı başarılı!")
            else:
                self.finished_signal.emit(False, f"Gemini hatası: {response.status_code}")

    def _test_openai(self):
        import httpx
        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        data = {
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "test"}],
            "max_tokens": 10
        }
        with httpx.Client(timeout=10.0) as client:
            response = client.post(url, json=data, headers=headers)
            if response.status_code == 200:
                self.finished_signal.emit(True, "✅ OpenAI bağlantısı başarılı!")
            else:
                self.finished_signal.emit(False, f"OpenAI hatası: {response.status_code}")

    def _test_ollama(self):
        import httpx
        url = "http://localhost:11434/api/generate"
        data = {
            "model": self.model,
            "prompt": "test",
            "stream": False
        }
        with httpx.Client(timeout=15.0) as client:
            response = client.post(url, json=data)
            if response.status_code == 200:
                self.finished_signal.emit(True, "✅ Ollama bağlantısı başarılı!")
            else:
                self.finished_signal.emit(False, f"Ollama hatası: {response.status_code}")


class ProviderComparisonCard(QFrame):
    """Detailed provider comparison card"""
    clicked = pyqtSignal(str)

    def __init__(self, provider_id: str, info: dict, parent=None):
        super().__init__(parent)
        self.provider_id = provider_id
        self._selected = False
        self.setFixedHeight(140)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._setup(info)

    def _setup(self, info):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        # Header: Name + Badge
        header = QHBoxLayout()
        name_label = QLabel(info["name"])
        name_label.setFont(QFont("SF Pro Display", 15, QFont.Weight.Bold))
        header.addWidget(name_label)

        badge = QLabel(info["badge"])
        badge.setStyleSheet(f"""
            background: {info['badge_color']};
            color: white;
            padding: 4px 8px;
            border-radius: 6px;
            font-size: 11px;
            font-weight: bold;
        """)
        header.addWidget(badge)
        header.addStretch()
        layout.addLayout(header)

        # Description
        desc = QLabel(info["desc"])
        desc.setStyleSheet("color: #8E8E93; font-size: 12px;")
        layout.addWidget(desc)

        # Comparison metrics
        metrics = QHBoxLayout()
        metrics.setSpacing(12)

        speed_label = QLabel(f"Hız: {info['speed']}")
        speed_label.setStyleSheet("font-size: 11px; color: #636366;")
        metrics.addWidget(speed_label)

        quality_label = QLabel(f"Kalite: {info['quality']}")
        quality_label.setStyleSheet("font-size: 11px; color: #636366;")
        metrics.addWidget(quality_label)

        metrics.addStretch()
        layout.addLayout(metrics)

        # Cost + Privacy
        details = QHBoxLayout()
        cost_label = QLabel(f"💰 {info['cost']}")
        cost_label.setStyleSheet("font-size: 11px; color: #636366;")
        details.addWidget(cost_label)

        privacy_label = QLabel(f"🔒 {info['privacy']}")
        privacy_label.setStyleSheet("font-size: 11px; color: #636366;")
        details.addWidget(privacy_label)
        details.addStretch()
        layout.addLayout(details)

        self._update_style()

    def _update_style(self):
        if self._selected:
            self.setStyleSheet("""
                QFrame {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                                stop:0 #E3F2FD, stop:1 #BBDEFB);
                    border: 2px solid #2196F3;
                    border-radius: 12px;
                }
            """)
        else:
            self.setStyleSheet("""
                QFrame {
                    background: #F2F2F7;
                    border: 1px solid #D1D1D6;
                    border-radius: 12px;
                }
                QFrame:hover {
                    background: #E5E5EA;
                    border-color: #7196A2;
                }
            """)

    def set_selected(self, selected: bool):
        self._selected = selected
        self._update_style()

    def mousePressEvent(self, event):
        self.clicked.emit(self.provider_id)


class EnhancedSetupWizard(QDialog):
    """
    Enhanced setup wizard with:
    - Ollama installation support
    - Provider comparison
    - Connection testing
    - Progress indicators
    """

    finished = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Elyan Gelişmiş Kurulum Sihirbazı")
        self.setFixedSize(680, 640)
        self.setModal(True)

        self.config: Dict[str, Any] = {
            "provider": "groq",
            "llm_type": "groq",
            "api_key": "",
            "ollama_host": "http://localhost:11434",
            "model": "llama-3.3-70b-versatile",
            "telegram_token": "",
            "user_id": "",
            "ollama_installed": False,
        }

        self.setup_completed = False
        self._provider_cards: dict[str, ProviderComparisonCard] = {}
        self._ollama_install_thread = None
        self._connection_test_thread = None

        self._setup_ui()

    def _setup_ui(self):
        self.setStyleSheet("""
            QDialog {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                            stop:0 #F8F9FA, stop:1 #E9ECEF);
            }
            QLabel { color: #252F33; }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._create_welcome_page())           # 0
        self.stack.addWidget(self._create_provider_comparison())    # 1
        self.stack.addWidget(self._create_ollama_setup_page())      # 2
        self.stack.addWidget(self._create_api_key_page())           # 3
        self.stack.addWidget(self._create_model_page())             # 4
        self.stack.addWidget(self._create_connection_test_page())   # 5
        self.stack.addWidget(self._create_telegram_page())          # 6
        self.stack.addWidget(self._create_completion_page())        # 7

        layout.addWidget(self.stack)

    # ── Page 0: Welcome ──────────────────────────────────────────
    def _create_welcome_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(40, 60, 40, 40)
        layout.setSpacing(20)

        # Logo
        logo = QLabel("🤖 ELYAN")
        logo.setFont(QFont("SF Pro Display", 52, QFont.Weight.Bold))
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setStyleSheet("color: #2196F3; letter-spacing: -2px;")
        layout.addWidget(logo)

        # Title
        title = QLabel("Akıllı Dijital Asistan")
        title.setFont(QFont("SF Pro Display", 22, QFont.Weight.DemiBold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("color: #455A64;")
        layout.addWidget(title)

        # Description
        desc = QLabel(
            "Elyan, bilgisayarınızı doğal dille kontrol etmenizi sağlar.\n\n"
            "✨ 94+ farklı araç\n"
            "⚡ Ultra-hızlı yanıt süresi\n"
            "🔒 Gizlilik odaklı (yerel model desteği)\n\n"
            "Kurulum sadece 3 dakika sürer."
        )
        desc.setWordWrap(True)
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setStyleSheet("color: #78909C; font-size: 14px; line-height: 1.6;")
        layout.addWidget(desc)

        layout.addStretch()

        # Start button
        btn = AnimatedButton("🚀 Başlayalım", primary=True)
        btn.setFixedHeight(50)
        btn.clicked.connect(lambda: self.stack.setCurrentIndex(1))
        layout.addWidget(btn)

        return page

    # ── Page 1: Provider Comparison ──────────────────────────────
    def _create_provider_comparison(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 20, 30, 20)
        layout.setSpacing(12)

        # Header
        header = SectionHeader("Adım 1: Yapay Zeka Motoru Seçimi")
        layout.addWidget(header)

        desc = QLabel(
            "Elyan'ın zeka kaynağını seçin. Her seçeneğin avantajları farklıdır:"
        )
        desc.setStyleSheet("color: #78909C; font-size: 13px; margin-bottom: 8px;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # Scrollable provider cards
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background: transparent;")

        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setSpacing(10)

        for pid, info in PROVIDERS.items():
            card = ProviderComparisonCard(pid, info)
            card.clicked.connect(self._on_provider_selected)
            self._provider_cards[pid] = card
            scroll_layout.addWidget(card)

        scroll_layout.addStretch()
        scroll.setWidget(scroll_widget)
        layout.addWidget(scroll)

        # Navigation
        nav = QHBoxLayout()
        back = AnimatedButton("← Geri", primary=False)
        back.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        nav.addWidget(back)

        fwd = AnimatedButton("Devam →", primary=True)
        fwd.clicked.connect(self._provider_next)
        nav.addWidget(fwd)
        layout.addLayout(nav)

        # Set default selection
        self._on_provider_selected("groq")

        return page

    def _on_provider_selected(self, provider_id: str):
        self.config["provider"] = provider_id
        self.config["llm_type"] = PROVIDERS[provider_id]["llm_type"]

        for pid, card in self._provider_cards.items():
            card.set_selected(pid == provider_id)

    def _provider_next(self):
        provider = self.config["provider"]

        if provider == "ollama":
            # Go to Ollama setup page
            self.stack.setCurrentIndex(2)
        else:
            # Go to API key page
            self.stack.setCurrentIndex(3)

    # ── Page 2: Ollama Setup ─────────────────────────────────────
    def _create_ollama_setup_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(40, 30, 40, 30)
        layout.setSpacing(16)

        header = SectionHeader("Ollama Kurulumu")
        layout.addWidget(header)

        desc = QLabel(
            "Ollama, bilgisayarınızda AI modellerini yerel olarak çalıştırmanızı sağlar.\n"
            "Bu sayede verileriniz hiçbir zaman internete gönderilmez (tam gizlilik).\n\n"
            "İlk kurulum yaklaşık 2-5 GB indirme gerektirir."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #78909C; font-size: 13px;")
        layout.addWidget(desc)

        # Option buttons
        self._ollama_radio_group = QButtonGroup()

        install_radio = QRadioButton("Ollama'yı indir ve kur (Önerilen)")
        install_radio.setStyleSheet("font-size: 14px; font-weight: bold;")
        install_radio.setChecked(True)
        self._ollama_radio_group.addButton(install_radio, 1)
        layout.addWidget(install_radio)

        skip_radio = QRadioButton("Zaten kurulu, atla")
        skip_radio.setStyleSheet("font-size: 14px;")
        self._ollama_radio_group.addButton(skip_radio, 2)
        layout.addWidget(skip_radio)

        use_api_radio = QRadioButton("Ollama yerine bulut API kullanacağım")
        use_api_radio.setStyleSheet("font-size: 14px;")
        self._ollama_radio_group.addButton(use_api_radio, 3)
        layout.addWidget(use_api_radio)

        # Progress area (hidden initially)
        self._ollama_progress_frame = QFrame()
        progress_layout = QVBoxLayout(self._ollama_progress_frame)

        self._ollama_progress_label = QLabel("")
        self._ollama_progress_label.setStyleSheet("color: #2196F3; font-size: 12px;")
        progress_layout.addWidget(self._ollama_progress_label)

        self._ollama_progress_bar = QProgressBar()
        self._ollama_progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #D1D1D6;
                border-radius: 6px;
                background: #F2F2F7;
                text-align: center;
                color: #252F33;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                            stop:0 #2196F3, stop:1 #64B5F6);
                border-radius: 6px;
            }
        """)
        progress_layout.addWidget(self._ollama_progress_bar)

        self._ollama_progress_frame.setVisible(False)
        layout.addWidget(self._ollama_progress_frame)

        layout.addStretch()

        # Navigation
        nav = QHBoxLayout()
        back = AnimatedButton("← Geri", primary=False)
        back.clicked.connect(lambda: self.stack.setCurrentIndex(1))
        nav.addWidget(back)

        self._ollama_next_btn = AnimatedButton("Devam →", primary=True)
        self._ollama_next_btn.clicked.connect(self._ollama_setup_next)
        nav.addWidget(self._ollama_next_btn)
        layout.addLayout(nav)

        return page

    def _ollama_setup_next(self):
        choice = self._ollama_radio_group.checkedId()

        if choice == 1:  # Install Ollama
            self._start_ollama_installation()
        elif choice == 2:  # Already installed
            self.config["ollama_installed"] = True
            self.stack.setCurrentIndex(4)  # Go to model page
        elif choice == 3:  # Use API instead
            self.stack.setCurrentIndex(1)  # Go back to provider selection

    def _start_ollama_installation(self):
        """Start Ollama installation in background thread"""
        self._ollama_progress_frame.setVisible(True)
        self._ollama_next_btn.setEnabled(False)

        self._ollama_install_thread = OllamaInstallThread(model_name="llama3.2:3b")
        self._ollama_install_thread.progress.connect(self._on_ollama_progress)
        self._ollama_install_thread.finished_signal.connect(self._on_ollama_finished)
        self._ollama_install_thread.start()

    def _on_ollama_progress(self, percent: int, message: str):
        self._ollama_progress_bar.setValue(percent)
        self._ollama_progress_label.setText(message)

    def _on_ollama_finished(self, success: bool, message: str):
        self._ollama_next_btn.setEnabled(True)

        if success:
            QMessageBox.information(self, "Başarılı", message)
            self.config["ollama_installed"] = True
            self.config["model"] = "llama3.2:3b"
            self.stack.setCurrentIndex(4)  # Go to model page
        else:
            QMessageBox.critical(self, "Hata", message)
            self._ollama_progress_frame.setVisible(False)

    # ── Page 3: API Key Input ────────────────────────────────────
    def _create_api_key_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(40, 30, 40, 30)
        layout.setSpacing(16)

        header = SectionHeader("API Anahtarı")
        layout.addWidget(header)

        self._api_info_label = QLabel("")
        self._api_info_label.setWordWrap(True)
        self._api_info_label.setStyleSheet("color: #78909C; font-size: 13px;")
        layout.addWidget(self._api_info_label)

        # API Key input
        key_label = QLabel("API Anahtarınızı Girin:")
        key_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(key_label)

        self._api_input = QLineEdit()
        self._api_input.setPlaceholderText("API anahtarınızı buraya yapıştırın...")
        self._api_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_input.setFixedHeight(44)
        self._api_input.setStyleSheet("""
            QLineEdit {
                background: white;
                border: 2px solid #D1D1D6;
                border-radius: 8px;
                padding: 0 12px;
                font-size: 14px;
                color: #252F33;
            }
            QLineEdit:focus {
                border-color: #2196F3;
            }
        """)
        layout.addWidget(self._api_input)

        # "Get API Key" button
        self._get_key_btn = AnimatedButton("🔑 API Anahtarı Al", primary=False)
        self._get_key_btn.clicked.connect(self._open_api_key_url)
        layout.addWidget(self._get_key_btn)

        layout.addStretch()

        # Navigation
        nav = QHBoxLayout()
        back = AnimatedButton("← Geri", primary=False)
        back.clicked.connect(lambda: self.stack.setCurrentIndex(1))
        nav.addWidget(back)

        fwd = AnimatedButton("Devam →", primary=True)
        fwd.clicked.connect(self._api_key_next)
        nav.addWidget(fwd)
        layout.addLayout(nav)

        return page

    def _open_api_key_url(self):
        provider = self.config["provider"]
        url = PROVIDERS[provider].get("signup_url")
        if url:
            import webbrowser
            webbrowser.open(url)

    def _api_key_next(self):
        api_key = self._api_input.text().strip()

        if not api_key:
            QMessageBox.warning(self, "Uyarı", "Lütfen API anahtarınızı girin.")
            return

        self.config["api_key"] = api_key
        self.stack.setCurrentIndex(4)  # Go to model page

    # ── Page 4: Model Selection ──────────────────────────────────
    def _create_model_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(40, 30, 40, 30)
        layout.setSpacing(16)

        header = SectionHeader("Model Seçimi")
        layout.addWidget(header)

        desc = QLabel("Kullanmak istediğiniz AI modelini seçin:")
        desc.setStyleSheet("color: #78909C; font-size: 13px;")
        layout.addWidget(desc)

        self._model_combo = QComboBox()
        self._model_combo.setFixedHeight(44)
        self._model_combo.setStyleSheet("""
            QComboBox {
                background: white;
                border: 2px solid #D1D1D6;
                border-radius: 8px;
                padding: 0 12px;
                font-size: 14px;
            }
            QComboBox:focus {
                border-color: #2196F3;
            }
        """)
        layout.addWidget(self._model_combo)

        layout.addStretch()

        # Navigation
        nav = QHBoxLayout()
        back = AnimatedButton("← Geri", primary=False)
        back.clicked.connect(self._model_back)
        nav.addWidget(back)

        fwd = AnimatedButton("Devam →", primary=True)
        fwd.clicked.connect(self._model_next)
        nav.addWidget(fwd)
        layout.addLayout(nav)

        return page

    def _model_back(self):
        provider = self.config["provider"]
        if provider == "ollama":
            self.stack.setCurrentIndex(2)
        else:
            self.stack.setCurrentIndex(3)

    def _model_next(self):
        model = self._model_combo.currentText()
        if model:
            self.config["model"] = model
            self.stack.setCurrentIndex(5)  # Go to connection test

    # ── Page 5: Connection Test ──────────────────────────────────
    def _create_connection_test_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(20)

        header = SectionHeader("Bağlantı Testi")
        layout.addWidget(header)

        desc = QLabel(
            "Seçtiğiniz AI motoruna bağlantıyı test ediyoruz..."
        )
        desc.setWordWrap(True)
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setStyleSheet("color: #78909C; font-size: 14px;")
        layout.addWidget(desc)

        # Test status
        self._test_status_label = QLabel("⏳ Test başlatılıyor...")
        self._test_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._test_status_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #2196F3;")
        layout.addWidget(self._test_status_label)

        # Progress
        self._test_progress = QProgressBar()
        self._test_progress.setRange(0, 0)  # Indeterminate
        self._test_progress.setStyleSheet("""
            QProgressBar {
                border: 1px solid #D1D1D6;
                border-radius: 6px;
                background: #F2F2F7;
                text-align: center;
            }
            QProgressBar::chunk {
                background: #2196F3;
            }
        """)
        layout.addWidget(self._test_progress)

        layout.addStretch()

        # Navigation
        nav = QHBoxLayout()
        back = AnimatedButton("← Geri", primary=False)
        back.clicked.connect(lambda: self.stack.setCurrentIndex(4))
        nav.addWidget(back)

        self._test_next_btn = AnimatedButton("Devam →", primary=True)
        self._test_next_btn.setEnabled(False)
        self._test_next_btn.clicked.connect(lambda: self.stack.setCurrentIndex(6))
        nav.addWidget(self._test_next_btn)
        layout.addLayout(nav)

        return page

    def _run_connection_test(self):
        """Run connection test when page is shown"""
        provider = self.config["provider"]
        api_key = self.config.get("api_key", "")
        model = self.config.get("model", "")

        self._connection_test_thread = ConnectionTestThread(provider, api_key, model)
        self._connection_test_thread.finished_signal.connect(self._on_test_finished)
        self._connection_test_thread.start()

    def _on_test_finished(self, success: bool, message: str):
        self._test_progress.setRange(0, 100)
        self._test_progress.setValue(100 if success else 0)
        self._test_status_label.setText(message)

        if success:
            self._test_status_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #34C759;")
        else:
            self._test_status_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #FF3B30;")

        self._test_next_btn.setEnabled(True)

    # ── Page 6: Telegram Config ──────────────────────────────────
    def _create_telegram_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(40, 30, 40, 30)
        layout.setSpacing(16)

        header = SectionHeader("Telegram Botu (İsteğe Bağlı)")
        layout.addWidget(header)

        desc = QLabel(
            "Elyan'ı Telegram üzerinden de kullanabilirsiniz.\n"
            "Şimdilik atlamak isterseniz, daha sonra ayarlardan ekleyebilirsiniz."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #78909C; font-size: 13px;")
        layout.addWidget(desc)

        # Bot Token
        token_label = QLabel("Bot Token:")
        token_label.setStyleSheet("font-weight: bold; font-size: 13px;")
        layout.addWidget(token_label)

        self._telegram_token_input = QLineEdit()
        self._telegram_token_input.setPlaceholderText("123456:ABC-DEF...")
        self._telegram_token_input.setFixedHeight(40)
        self._telegram_token_input.setStyleSheet("""
            QLineEdit {
                background: white;
                border: 2px solid #D1D1D6;
                border-radius: 8px;
                padding: 0 12px;
                font-size: 13px;
            }
        """)
        layout.addWidget(self._telegram_token_input)

        # User ID
        uid_label = QLabel("Kullanıcı ID:")
        uid_label.setStyleSheet("font-weight: bold; font-size: 13px;")
        layout.addWidget(uid_label)

        self._telegram_uid_input = QLineEdit()
        self._telegram_uid_input.setPlaceholderText("123456789")
        self._telegram_uid_input.setFixedHeight(40)
        self._telegram_uid_input.setStyleSheet("""
            QLineEdit {
                background: white;
                border: 2px solid #D1D1D6;
                border-radius: 8px;
                padding: 0 12px;
                font-size: 13px;
            }
        """)
        layout.addWidget(self._telegram_uid_input)

        layout.addStretch()

        # Navigation
        nav = QHBoxLayout()
        skip = AnimatedButton("Atla", primary=False)
        skip.clicked.connect(lambda: self._finish_setup())
        nav.addWidget(skip)

        fwd = AnimatedButton("Tamamla", primary=True)
        fwd.clicked.connect(self._telegram_next)
        nav.addWidget(fwd)
        layout.addLayout(nav)

        return page

    def _telegram_next(self):
        self.config["telegram_token"] = self._telegram_token_input.text().strip()
        self.config["user_id"] = self._telegram_uid_input.text().strip()
        self._finish_setup()

    # ── Page 7: Completion ───────────────────────────────────────
    def _create_completion_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(40, 60, 40, 40)
        layout.setSpacing(20)

        # Success icon
        icon = QLabel("✅")
        icon.setFont(QFont("SF Pro Display", 72))
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon)

        # Title
        title = QLabel("Kurulum Tamamlandı!")
        title.setFont(QFont("SF Pro Display", 24, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("color: #34C759;")
        layout.addWidget(title)

        # Description
        desc = QLabel(
            "Elyan başarıyla kuruldu ve kullanıma hazır.\n\n"
            "Artık doğal dille komutlar verebilir,\n"
            "dosyalarınızı yönetebilir ve daha fazlasını yapabilirsiniz!"
        )
        desc.setWordWrap(True)
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setStyleSheet("color: #78909C; font-size: 14px;")
        layout.addWidget(desc)

        layout.addStretch()

        # Finish button
        finish_btn = AnimatedButton("🚀 Elyan'ı Başlat", primary=True)
        finish_btn.setFixedHeight(50)
        finish_btn.clicked.connect(self._complete_wizard)
        layout.addWidget(finish_btn)

        return page

    def _finish_setup(self):
        """Save config and show completion page"""
        self._save_config()
        self.stack.setCurrentIndex(7)

    def _save_config(self):
        """Save configuration to .env and settings.json"""
        try:
            # Update .env
            env_path = Path.home().parent.parent / "Users" / "emrekoca" / "Desktop" / "bot" / ".env"

            lines = []
            if env_path.exists():
                lines = env_path.read_text().splitlines()

            # Update or add lines
            updated = {}
            for i, line in enumerate(lines):
                if "=" in line:
                    key = line.split("=")[0]
                    if key == "LLM_TYPE":
                        lines[i] = f"LLM_TYPE={self.config['llm_type']}"
                        updated["LLM_TYPE"] = True
                    elif key == "GROQ_API_KEY" and self.config.get("provider") == "groq":
                        lines[i] = f"GROQ_API_KEY={self.config['api_key']}"
                        updated["GROQ_API_KEY"] = True
                    elif key == "GOOGLE_API_KEY" and self.config.get("provider") == "gemini":
                        lines[i] = f"GOOGLE_API_KEY={self.config['api_key']}"
                        updated["GOOGLE_API_KEY"] = True
                    elif key == "OPENAI_API_KEY" and self.config.get("provider") == "openai":
                        lines[i] = f"OPENAI_API_KEY={self.config['api_key']}"
                        updated["OPENAI_API_KEY"] = True
                    elif key == "TELEGRAM_BOT_TOKEN":
                        if self.config.get("telegram_token"):
                            lines[i] = f"TELEGRAM_BOT_TOKEN={self.config['telegram_token']}"
                        updated["TELEGRAM_BOT_TOKEN"] = True
                    elif key == "ALLOWED_USER_IDS":
                        if self.config.get("user_id"):
                            lines[i] = f"ALLOWED_USER_IDS={self.config['user_id']}"
                        updated["ALLOWED_USER_IDS"] = True

            # Add missing keys
            if "LLM_TYPE" not in updated:
                lines.append(f"LLM_TYPE={self.config['llm_type']}")

            if self.config.get("provider") == "groq" and "GROQ_API_KEY" not in updated:
                lines.append(f"GROQ_API_KEY={self.config['api_key']}")
            elif self.config.get("provider") == "gemini" and "GOOGLE_API_KEY" not in updated:
                lines.append(f"GOOGLE_API_KEY={self.config['api_key']}")
            elif self.config.get("provider") == "openai" and "OPENAI_API_KEY" not in updated:
                lines.append(f"OPENAI_API_KEY={self.config['api_key']}")

            env_path.write_text("\n".join(lines))
            logger.info("Configuration saved to .env")

        except Exception as e:
            logger.error(f"Failed to save config: {e}")

    def _complete_wizard(self):
        self.setup_completed = True
        self.finished.emit(self.config)
        self.accept()

    def showEvent(self, event):
        """Override to run connection test when test page is shown"""
        super().showEvent(event)
        if self.stack.currentIndex() == 5:  # Connection test page
            QTimer.singleShot(500, self._run_connection_test)
        elif self.stack.currentIndex() == 4:  # Model page
            self._populate_model_combo()

    def _populate_model_combo(self):
        """Populate model combo based on provider"""
        provider = self.config["provider"]
        models = PROVIDERS[provider]["models"]

        self._model_combo.clear()
        if provider == "ollama":
            # Get installed Ollama models
            installed = _get_ollama_models()
            if installed:
                self._model_combo.addItems(installed)
            else:
                self._model_combo.addItem("llama3.2:3b")
        else:
            self._model_combo.addItems(models)


def _get_ollama_models() -> list[str]:
    """Get installed Ollama models"""
    try:
        result = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=5)
        models = []
        for line in result.stdout.strip().splitlines()[1:]:
            if line.split():
                models.append(line.split()[0])
        return models
    except Exception:
        return []


if __name__ == "__main__":
    app = QApplication(sys.argv)
    wizard = EnhancedSetupWizard()
    wizard.show()
    sys.exit(app.exec())
