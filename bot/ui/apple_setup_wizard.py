"""
Elyan Setup Wizard - Apple-inspired Design
Clean, minimal, emoji-free, never freezes
"""

import os
import sys
import subprocess
import platform
from pathlib import Path
from typing import Optional, Dict, Any

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QStackedWidget,
    QLineEdit, QPushButton, QFrame, QProgressBar, QApplication,
    QDialog, QComboBox, QMessageBox, QRadioButton, QButtonGroup
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread, QTimer
from PyQt6.QtGui import QFont

from utils.logger import get_logger
from config.settings_manager import SettingsPanel
from ui.branding import load_brand_icon, load_brand_pixmap

logger = get_logger("apple_setup_wizard")

# Apple-style color palette
COLORS = {
    "primary": "#0E86F8",
    "secondary": "#1565D8",
    "success": "#22C55E",
    "warning": "#F59E0B",
    "danger": "#EF4444",
    "text": "#0B1B2B",
    "text_secondary": "#4B6075",
    "bg": "#F2F6FC",
    "bg_secondary": "#FFFFFF",
    "border": "#D7E1EC",
}

# Provider definitions (emoji-free)
PROVIDERS = {
    "groq": {
        "name": "Groq",
        "desc": "Ultra-fast cloud API",
        "badge": "Free",
        "speed": "Fastest",
        "quality": "High",
        "cost": "Free (Limited)",
        "privacy": "Cloud-based",
        "models": ["llama-3.3-70b-versatile", "mixtral-8x7b-32768", "llama-3.1-8b-instant"],
        "env_key": "GROQ_API_KEY",
        "llm_type": "groq",
        "signup_url": "https://console.groq.com/keys",
    },
    "gemini": {
        "name": "Google Gemini",
        "desc": "Powerful and versatile AI",
        "badge": "Free Tier",
        "speed": "Fast",
        "quality": "Excellent",
        "cost": "Free (Limited)",
        "privacy": "Google Cloud",
        "models": ["gemini-2.0-flash", "gemini-1.5-pro", "gemini-1.5-flash"],
        "env_key": "GOOGLE_API_KEY",
        "llm_type": "api",
        "signup_url": "https://makersuite.google.com/app/apikey",
    },
    "openai": {
        "name": "OpenAI",
        "desc": "Most powerful GPT models",
        "badge": "Paid",
        "speed": "Fast",
        "quality": "Excellent",
        "cost": "Paid ($$$)",
        "privacy": "OpenAI Cloud",
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"],
        "env_key": "OPENAI_API_KEY",
        "llm_type": "openai",
        "signup_url": "https://platform.openai.com/api-keys",
    },
    "ollama": {
        "name": "Ollama",
        "desc": "Runs locally on your Mac",
        "badge": "Private",
        "speed": "Medium",
        "quality": "Good",
        "cost": "Free",
        "privacy": "100% Local",
        "models": [],  # Populated dynamically
        "env_key": None,
        "llm_type": "ollama",
        "signup_url": None,
    },
}


def _get_ollama_models() -> list[str]:
    """Get installed Ollama models"""
    try:
        result = subprocess.run(
            ["ollama", "list"],
            capture_output=True,
            text=True,
            timeout=3
        )
        models = []
        for line in result.stdout.strip().splitlines()[1:]:
            parts = line.split()
            if parts:
                models.append(parts[0])
        return models
    except Exception as e:
        logger.debug(f"Ollama not available: {e}")
        return []


class OllamaInstallThread(QThread):
    """Background thread for Ollama installation - never blocks UI"""
    progress = pyqtSignal(int, str)
    finished_signal = pyqtSignal(bool, str)

    def __init__(self, model_name="llama3.2:3b"):
        super().__init__()
        self.model_name = model_name
        self._is_cancelled = False

    def run(self):
        try:
            # Check if Ollama is installed
            self.progress.emit(10, "Checking Ollama installation...")
            try:
                result = subprocess.run(
                    ["ollama", "--version"],
                    capture_output=True,
                    timeout=3
                )
                if result.returncode == 0:
                    self.progress.emit(30, "Ollama is already installed")
                else:
                    raise FileNotFoundError
            except (FileNotFoundError, subprocess.TimeoutExpired):
                # Ollama not installed - install it
                self.progress.emit(30, "Installing Ollama...")

                system = platform.system()
                if system == "Darwin":  # macOS
                    install_cmd = "curl -fsSL https://ollama.com/install.sh | sh"
                    subprocess.run(
                        install_cmd,
                        shell=True,
                        check=True,
                        timeout=300
                    )
                    self.progress.emit(60, "Ollama installed successfully")
                else:
                    self.finished_signal.emit(False, "Only macOS is supported")
                    return

            if self._is_cancelled:
                return

            # Pull model
            self.progress.emit(70, f"Downloading {self.model_name}...")
            pull_process = subprocess.Popen(
                ["ollama", "pull", self.model_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )

            for line in pull_process.stdout:
                if self._is_cancelled:
                    pull_process.terminate()
                    return

                if "pulling" in line.lower():
                    self.progress.emit(85, f"Downloading model...")
                elif "success" in line.lower():
                    self.progress.emit(95, "Model downloaded")

            pull_process.wait()

            if pull_process.returncode == 0:
                self.progress.emit(100, "Setup complete")
                self.finished_signal.emit(True, f"Successfully installed {self.model_name}")
            else:
                self.finished_signal.emit(False, "Model download failed")

        except subprocess.TimeoutExpired:
            self.finished_signal.emit(False, "Installation timeout")
        except Exception as e:
            logger.error(f"Ollama installation error: {e}")
            self.finished_signal.emit(False, f"Error: {str(e)}")

    def cancel(self):
        self._is_cancelled = True


class ConnectionTestThread(QThread):
    """Background thread for testing API connections - never blocks UI"""
    finished_signal = pyqtSignal(bool, str)

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
                self.finished_signal.emit(False, "Unknown provider")
        except Exception as e:
            logger.error(f"Connection test error: {e}")
            self.finished_signal.emit(False, f"Connection failed: {str(e)}")

    def _test_groq(self):
        try:
            import httpx
            url = "https://api.groq.com/openai/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            data = {
                "model": "llama-3.3-70b-versatile",
                "messages": [{"role": "user", "content": "test"}],
                "max_tokens": 5
            }
            with httpx.Client(timeout=10.0) as client:
                response = client.post(url, json=data, headers=headers)
                if response.status_code == 200:
                    self.finished_signal.emit(True, "Connection successful")
                elif response.status_code == 401:
                    self.finished_signal.emit(False, "Invalid API key")
                else:
                    self.finished_signal.emit(False, f"Error: {response.status_code}")
        except Exception as e:
            self.finished_signal.emit(False, f"Connection failed: {str(e)}")

    def _test_gemini(self):
        try:
            import httpx
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={self.api_key}"
            data = {"contents": [{"parts": [{"text": "test"}]}]}
            with httpx.Client(timeout=10.0) as client:
                response = client.post(url, json=data)
                if response.status_code == 200:
                    self.finished_signal.emit(True, "Connection successful")
                elif response.status_code == 400:
                    self.finished_signal.emit(False, "Invalid API key")
                else:
                    self.finished_signal.emit(False, f"Error: {response.status_code}")
        except Exception as e:
            self.finished_signal.emit(False, f"Connection failed: {str(e)}")

    def _test_openai(self):
        try:
            import httpx
            url = "https://api.openai.com/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            data = {
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": "test"}],
                "max_tokens": 5
            }
            with httpx.Client(timeout=10.0) as client:
                response = client.post(url, json=data, headers=headers)
                if response.status_code == 200:
                    self.finished_signal.emit(True, "Connection successful")
                elif response.status_code == 401:
                    self.finished_signal.emit(False, "Invalid API key")
                else:
                    self.finished_signal.emit(False, f"Error: {response.status_code}")
        except Exception as e:
            self.finished_signal.emit(False, f"Connection failed: {str(e)}")

    def _test_ollama(self):
        try:
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
                    self.finished_signal.emit(True, "Connection successful")
                else:
                    self.finished_signal.emit(False, f"Ollama error: {response.status_code}")
        except Exception as e:
            self.finished_signal.emit(False, f"Connection failed: {str(e)}")


class ProviderCard(QFrame):
    """Apple-style provider card - minimal, clean"""
    clicked = pyqtSignal(str)

    def __init__(self, provider_id: str, info: dict, parent=None):
        super().__init__(parent)
        self.provider_id = provider_id
        self._selected = False
        self.setFixedHeight(112)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._setup(info)

    def _setup(self, info):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(8)

        # Header: Name + Badge
        header = QHBoxLayout()
        header.setSpacing(8)

        name_label = QLabel(info["name"])
        name_label.setFont(QFont(".AppleSystemUIFont", 16, QFont.Weight.Medium))
        name_label.setStyleSheet(f"color: {COLORS['text']};")
        header.addWidget(name_label)

        # Badge
        badge_color = COLORS["success"] if "free" in info["badge"].lower() else COLORS["secondary"]
        badge = QLabel(info["badge"])
        badge.setStyleSheet(f"""
            background: {badge_color};
            color: white;
            padding: 3px 8px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: 600;
        """)
        badge.setFixedHeight(20)
        header.addWidget(badge)
        header.addStretch()
        layout.addLayout(header)

        # Description
        desc = QLabel(info["desc"])
        desc.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 13px;")
        layout.addWidget(desc)

        # Metrics
        metrics = QLabel(f"{info['speed']} • {info['quality']} • {info['privacy']}")
        metrics.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px;")
        layout.addWidget(metrics)

        self._update_style()

    def _update_style(self):
        if self._selected:
            self.setStyleSheet(f"""
                QFrame {{
                    background: {COLORS['bg']};
                    border: 2px solid {COLORS['primary']};
                    border-radius: 10px;
                }}
            """)
        else:
            self.setStyleSheet(f"""
                QFrame {{
                    background: {COLORS['bg_secondary']};
                    border: 1px solid {COLORS['border']};
                    border-radius: 10px;
                }}
                QFrame:hover {{
                    border: 1px solid {COLORS['primary']};
                }}
            """)

    def set_selected(self, selected: bool):
        self._selected = selected
        self._update_style()

    def mousePressEvent(self, event):
        self.clicked.emit(self.provider_id)


class CleanButton(QPushButton):
    """Apple-style button - clean, minimal"""
    def __init__(self, text: str, primary: bool = False, parent=None):
        super().__init__(text, parent)
        self.primary = primary
        self.setFixedHeight(44)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._update_style()

    def _update_style(self):
        if self.primary:
            self.setStyleSheet(f"""
                QPushButton {{
                    background: {COLORS['primary']};
                    color: white;
                    border: none;
                    border-radius: 10px;
                    font-size: 15px;
                    font-weight: 600;
                    padding: 0 20px;
                }}
                QPushButton:hover {{
                    background: #0051D5;
                }}
                QPushButton:pressed {{
                    background: #004BB8;
                }}
                QPushButton:disabled {{
                    background: {COLORS['bg_secondary']};
                    color: {COLORS['text_secondary']};
                }}
            """)
        else:
            self.setStyleSheet(f"""
                QPushButton {{
                    background: {COLORS['bg_secondary']};
                    color: {COLORS['text']};
                    border: none;
                    border-radius: 10px;
                    font-size: 15px;
                    font-weight: 500;
                    padding: 0 20px;
                }}
                QPushButton:hover {{
                    background: #E5E5EA;
                }}
                QPushButton:pressed {{
                    background: #D1D1D6;
                }}
            """)


class AppleSetupWizard(QDialog):
    """
    Apple-inspired setup wizard
    - No emojis
    - Clean, minimal design
    - Never freezes (all I/O in background threads)
    - Robust error handling
    """

    finished = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Elyan Setup")
        self.setMinimumSize(760, 680)
        self.resize(820, 700)
        self.setSizeGripEnabled(True)
        self.setModal(True)
        brand_icon = load_brand_icon(size=128)
        if not brand_icon.isNull():
            self.setWindowIcon(brand_icon)

        self.config: Dict[str, Any] = {
            "provider": "groq",
            "llm_type": "groq",
            "api_key": "",
            "ollama_host": "http://localhost:11434",
            "model": "llama-3.3-70b-versatile",
            "telegram_token": "",
            "user_id": "",
            "ollama_installed": False,
            "autonomy_level": "Balanced",
            "communication_tone": "professional_friendly",
            "response_length": "short",
            "task_planning_depth": "adaptive",
            "assistant_expertise": "advanced",
            "full_disk_access": True,
        }

        self.setup_completed = False
        self._provider_cards: dict[str, ProviderCard] = {}
        self._selected_model_by_provider: dict[str, str] = {}
        self._ollama_install_thread = None
        self._connection_test_thread = None
        self._connection_verified = False

        self._setup_ui()

    def _setup_ui(self):
        self.setStyleSheet(f"""
            QDialog {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                            stop:0 #F7FAFF, stop:0.5 #F1F6FD, stop:1 #EAF1FA);
            }}
            QLabel {{
                color: {COLORS['text']};
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)

        shell = QFrame()
        shell.setStyleSheet(f"""
            QFrame {{
                background: {COLORS['bg_secondary']};
                border: 1px solid {COLORS['border']};
                border-radius: 18px;
            }}
        """)
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._wrap_step(self._create_welcome_page(), 1, "Hoş geldiniz"))        # 0
        self.stack.addWidget(self._wrap_step(self._create_provider_page(), 2, "Sağlayıcı seç"))       # 1
        self.stack.addWidget(self._wrap_step(self._create_ollama_setup_page(), 3, "Ollama kurulum"))   # 2
        self.stack.addWidget(self._wrap_step(self._create_api_key_page(), 3, "API anahtarı"))        # 3
        self.stack.addWidget(self._wrap_step(self._create_model_page(), 4, "Model seç"))          # 4
        self.stack.addWidget(self._wrap_step(self._create_connection_test(), 5, "Bağlantı testi"))     # 5
        self.stack.addWidget(self._wrap_step(self._create_telegram_page(), 6, "Telegram"))       # 6
        self.stack.addWidget(self._wrap_step(self._create_personalization_page(), 7, "Kişiselleştirme"))# 7
        self.stack.addWidget(self._wrap_step(self._create_completion_page(), 8, "Tamam"))     # 8

        # Connect stack changed signal to handle page-specific logic
        self.stack.currentChanged.connect(self._on_page_changed)
        shell_layout.addWidget(self.stack)
        layout.addWidget(shell)

    def _wrap_step(self, widget: QWidget, step_no: int, title: str) -> QWidget:
        """Wrap each page with a consistent header showing step info."""
        wrapper = QWidget()
        v = QVBoxLayout(wrapper)
        v.setContentsMargins(36, 24, 36, 24)
        v.setSpacing(16)

        header_row = QHBoxLayout()
        step_badge = QLabel(f"Adım {step_no}/8")
        step_badge.setStyleSheet(f"""
            QLabel {{
                background: {COLORS['primary']};
                color: white;
                padding: 6px 12px;
                border-radius: 10px;
                font-weight: 600;
                font-size: 12px;
            }}
        """)
        header_row.addWidget(step_badge, alignment=Qt.AlignmentFlag.AlignLeft)

        title_label = QLabel(title)
        title_label.setFont(QFont(".AppleSystemUIFont", 18, QFont.Weight.Bold))
        title_label.setStyleSheet(f"color: {COLORS['text']};")
        header_row.addWidget(title_label, alignment=Qt.AlignmentFlag.AlignLeft)
        header_row.addStretch()

        companion = QLabel()
        companion_pixmap = load_brand_pixmap(size=34)
        if not companion_pixmap.isNull():
            companion.setPixmap(companion_pixmap)
            companion.setFixedSize(34, 34)
            companion.setStyleSheet(f"""
                QLabel {{
                    background: {COLORS['bg_secondary']};
                    border: 1px solid {COLORS['border']};
                    border-radius: 17px;
                    padding: 2px;
                }}
            """)
            header_row.addWidget(companion, alignment=Qt.AlignmentFlag.AlignRight)

        v.addLayout(header_row)

        v.addWidget(widget)
        return wrapper

    def _on_page_changed(self, index: int):
        """Handle page-specific logic when stack index changes"""
        try:
            if index == 4:  # Model page
                self._populate_model_combo()
            elif index == 3:  # API key page
                self._update_api_key_page_for_provider()
            elif index == 5:  # Connection test page
                self._connection_verified = False
                self._test_next_btn.setEnabled(False)
                self._test_next_btn.setText("Continue")
                QTimer.singleShot(300, self._run_connection_test)
        except Exception as e:
            logger.error(f"Page changed error: {e}")

    # ── Page 0: Welcome ──────────────────────────────────────
    def _create_welcome_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(60, 80, 60, 60)
        layout.setSpacing(18)

        mascot = QLabel()
        mascot_pixmap = load_brand_pixmap(size=180)
        if not mascot_pixmap.isNull():
            mascot.setPixmap(mascot_pixmap)
            mascot.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(mascot)

        logo = QLabel("ELYAN")
        logo.setFont(QFont(".AppleSystemUIFont", 52, QFont.Weight.Bold))
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setStyleSheet(f"color: {COLORS['primary']}; letter-spacing: -1px;")
        layout.addWidget(logo)

        # Subtitle
        subtitle = QLabel("Intelligent Digital Assistant")
        subtitle.setFont(QFont(".AppleSystemUIFont", 20, QFont.Weight.Medium))
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet(f"color: {COLORS['text_secondary']};")
        layout.addWidget(subtitle)

        # Description
        desc = QLabel(
            "Elyan, ilk günden itibaren yanında olan güvenilir bir dijital asistandır.\n"
            "Kurulum 2 dakika sürer ve seçtiğin model ayarlarına sadık kalır.\n\n"
            "Hız, gizlilik ve kontrol tamamen sende."
        )
        desc.setWordWrap(True)
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 15px;")
        layout.addWidget(desc)

        layout.addStretch()

        # Continue button
        btn = CleanButton("Continue", primary=True)
        btn.clicked.connect(lambda: self.stack.setCurrentIndex(1))
        layout.addWidget(btn)

        return page

    # ── Page 1: Provider Selection ──────────────────────────
    def _create_provider_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(44, 34, 44, 34)
        layout.setSpacing(20)

        # Header
        header = QLabel("Choose AI Provider")
        header.setFont(QFont(".AppleSystemUIFont", 24, QFont.Weight.Bold))
        layout.addWidget(header)

        desc = QLabel("Select the AI engine that powers Elyan")
        desc.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 14px;")
        layout.addWidget(desc)

        # Provider cards
        for pid, info in PROVIDERS.items():
            card = ProviderCard(pid, info)
            card.clicked.connect(self._on_provider_selected)
            self._provider_cards[pid] = card
            layout.addWidget(card)

        layout.addStretch()

        # Navigation
        nav = QHBoxLayout()
        nav.setSpacing(12)

        back = CleanButton("Back", primary=False)
        back.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        nav.addWidget(back)

        fwd = CleanButton("Continue", primary=True)
        fwd.clicked.connect(self._provider_next)
        nav.addWidget(fwd)
        layout.addLayout(nav)

        # Set default
        self._on_provider_selected("groq")

        return page

    def _on_provider_selected(self, provider_id: str):
        self.config["provider"] = provider_id
        self.config["llm_type"] = PROVIDERS[provider_id]["llm_type"]
        remembered = self._selected_model_by_provider.get(provider_id)
        if remembered:
            self.config["model"] = remembered

        for pid, card in self._provider_cards.items():
            card.set_selected(pid == provider_id)

    def _provider_next(self):
        provider = self.config["provider"]

        if provider == "ollama":
            self.stack.setCurrentIndex(2)  # Ollama setup
        else:
            self.stack.setCurrentIndex(3)  # API key

    # ── Page 2: Ollama Setup ────────────────────────────────
    def _create_ollama_setup_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(40, 30, 40, 30)
        layout.setSpacing(20)

        # Header
        header = QLabel("Ollama Setup")
        header.setFont(QFont(".AppleSystemUIFont", 24, QFont.Weight.Bold))
        layout.addWidget(header)

        desc = QLabel(
            "Ollama runs AI models locally on your Mac.\n"
            "Your data never leaves your computer.\n\n"
            "First-time setup requires downloading 2-5 GB."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 14px;")
        layout.addWidget(desc)

        # Radio options
        self._ollama_radio_group = QButtonGroup()

        install_radio = QRadioButton("Install Ollama (Recommended)")
        install_radio.setFont(QFont(".AppleSystemUIFont", 14, QFont.Weight.Medium))
        install_radio.setChecked(True)
        self._ollama_radio_group.addButton(install_radio, 1)
        layout.addWidget(install_radio)

        skip_radio = QRadioButton("Already installed, skip")
        skip_radio.setFont(QFont(".AppleSystemUIFont", 14))
        self._ollama_radio_group.addButton(skip_radio, 2)
        layout.addWidget(skip_radio)

        api_radio = QRadioButton("Use cloud API instead")
        api_radio.setFont(QFont(".AppleSystemUIFont", 14))
        self._ollama_radio_group.addButton(api_radio, 3)
        layout.addWidget(api_radio)

        # Progress area (hidden initially)
        self._ollama_progress_frame = QFrame()
        self._ollama_progress_frame.setVisible(False)
        progress_layout = QVBoxLayout(self._ollama_progress_frame)

        self._ollama_progress_label = QLabel("")
        self._ollama_progress_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 13px;")
        progress_layout.addWidget(self._ollama_progress_label)

        self._ollama_progress_bar = QProgressBar()
        self._ollama_progress_bar.setStyleSheet(f"""
            QProgressBar {{
                border: 1px solid {COLORS['border']};
                border-radius: 6px;
                background: {COLORS['bg_secondary']};
                text-align: center;
                height: 8px;
            }}
            QProgressBar::chunk {{
                background: {COLORS['primary']};
                border-radius: 5px;
            }}
        """)
        progress_layout.addWidget(self._ollama_progress_bar)

        layout.addWidget(self._ollama_progress_frame)

        layout.addStretch()

        # Navigation
        nav = QHBoxLayout()
        nav.setSpacing(12)

        back = CleanButton("Back", primary=False)
        back.clicked.connect(lambda: self.stack.setCurrentIndex(1))
        nav.addWidget(back)

        self._ollama_next_btn = CleanButton("Continue", primary=True)
        self._ollama_next_btn.clicked.connect(self._ollama_setup_next)
        nav.addWidget(self._ollama_next_btn)
        layout.addLayout(nav)

        return page

    def _ollama_setup_next(self):
        choice = self._ollama_radio_group.checkedId()

        if choice == 1:  # Install
            self._start_ollama_installation()
        elif choice == 2:  # Already installed
            if self._is_ollama_available():
                self.config["ollama_installed"] = True
                self.stack.setCurrentIndex(4)  # Model page
            else:
                QMessageBox.warning(
                    self,
                    "Ollama Not Found",
                    "Ollama is not installed or not reachable in PATH.\n"
                    "Please choose 'Install Ollama' or switch to cloud API."
                )
        elif choice == 3:  # Use API
            self.config["provider"] = "groq"
            self.config["llm_type"] = PROVIDERS["groq"]["llm_type"]
            for pid, card in self._provider_cards.items():
                card.set_selected(pid == "groq")
            self.stack.setCurrentIndex(3)  # API key

    def _is_ollama_available(self) -> bool:
        try:
            result = subprocess.run(
                ["ollama", "--version"],
                capture_output=True,
                text=True,
                timeout=3
            )
            return result.returncode == 0
        except Exception:
            return False

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
            QMessageBox.information(self, "Success", message)
            self.config["ollama_installed"] = True
            self.config["model"] = "llama3.2:3b"
            self._selected_model_by_provider["ollama"] = "llama3.2:3b"
            self.stack.setCurrentIndex(4)  # Model page
        else:
            QMessageBox.critical(self, "Error", message)
            self._ollama_progress_frame.setVisible(False)

    # ── Page 3: API Key ─────────────────────────────────────
    def _create_api_key_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(40, 30, 40, 30)
        layout.setSpacing(20)

        # Header
        header = QLabel("API Key")
        header.setFont(QFont(".AppleSystemUIFont", 24, QFont.Weight.Bold))
        layout.addWidget(header)

        self._api_desc = QLabel("")
        self._api_desc.setWordWrap(True)
        self._api_desc.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 14px;")
        layout.addWidget(self._api_desc)

        # API Key input
        key_label = QLabel("Enter your API key:")
        key_label.setFont(QFont(".AppleSystemUIFont", 13, QFont.Weight.Medium))
        layout.addWidget(key_label)

        self._api_input = QLineEdit()
        self._api_input.setPlaceholderText("Paste your API key here...")
        self._api_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_input.setFixedHeight(44)
        self._api_input.setStyleSheet(f"""
            QLineEdit {{
                background: {COLORS['bg_secondary']};
                border: 1px solid {COLORS['border']};
                border-radius: 8px;
                padding: 0 12px;
                font-size: 14px;
            }}
            QLineEdit:focus {{
                border: 2px solid {COLORS['primary']};
                background: {COLORS['bg']};
            }}
        """)
        layout.addWidget(self._api_input)

        # Get key button
        self._get_key_btn = CleanButton("Get API Key", primary=False)
        self._get_key_btn.clicked.connect(self._open_api_key_url)
        layout.addWidget(self._get_key_btn)

        layout.addStretch()

        # Navigation
        nav = QHBoxLayout()
        nav.setSpacing(12)

        back = CleanButton("Back", primary=False)
        back.clicked.connect(lambda: self.stack.setCurrentIndex(1))
        nav.addWidget(back)

        fwd = CleanButton("Continue", primary=True)
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

    def _update_api_key_page_for_provider(self):
        provider = self.config["provider"]
        provider_info = PROVIDERS.get(provider, PROVIDERS["groq"])
        self._api_desc.setText(
            f"{provider_info['name']} kullanmak için API anahtarı gerekiyor.\n"
            "Anahtarınızı güvenli şekilde yalnızca bu cihazda saklarız."
        )
        self._api_input.setPlaceholderText(f"{provider_info['name']} API key")

    def _api_key_next(self):
        api_key = self._api_input.text().strip()
        provider = self.config["provider"]

        if not api_key:
            QMessageBox.warning(self, "Warning", "Please enter your API key")
            return

        # Lightweight format checks to catch common paste mistakes early.
        format_ok = True
        if provider == "openai":
            format_ok = api_key.startswith("sk-")
        elif provider == "groq":
            format_ok = len(api_key) >= 20
        elif provider == "gemini":
            format_ok = len(api_key) >= 20

        if not format_ok:
            answer = QMessageBox.question(
                self,
                "API Key Format",
                "API key format looks unusual for selected provider.\n"
                "Do you want to continue anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        self.config["api_key"] = api_key
        self.stack.setCurrentIndex(4)  # Model page

    # ── Page 4: Model Selection ─────────────────────────────
    def _create_model_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(44, 34, 44, 34)
        layout.setSpacing(22)

        # Header
        header = QLabel("Select Model")
        header.setFont(QFont(".AppleSystemUIFont", 24, QFont.Weight.Bold))
        layout.addWidget(header)

        desc = QLabel("Choose the AI model to use")
        desc.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 14px;")
        layout.addWidget(desc)

        # Model combo
        self._model_combo = QComboBox()
        self._model_combo.setFixedHeight(44)
        self._model_combo.currentTextChanged.connect(self._on_model_changed)
        self._model_combo.setStyleSheet(f"""
            QComboBox {{
                background: {COLORS['bg_secondary']};
                border: 1px solid {COLORS['border']};
                border-radius: 8px;
                padding: 0 12px;
                font-size: 14px;
            }}
            QComboBox:focus {{
                border: 2px solid {COLORS['primary']};
            }}
            QComboBox::drop-down {{
                border: none;
                width: 30px;
            }}
            QComboBox QAbstractItemView {{
                background: {COLORS['bg']};
                border: 1px solid {COLORS['border']};
                selection-background-color: {COLORS['primary']};
            }}
        """)
        layout.addWidget(self._model_combo)

        layout.addStretch()

        # Navigation
        nav = QHBoxLayout()
        nav.setSpacing(12)

        back = CleanButton("Back", primary=False)
        back.clicked.connect(self._model_back)
        nav.addWidget(back)

        fwd = CleanButton("Continue", primary=True)
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
            self._selected_model_by_provider[self.config.get("provider", "groq")] = model
            self.stack.setCurrentIndex(5)  # Connection test

    def _populate_model_combo(self):
        """Populate model combo based on provider - CRITICAL FIX"""
        try:
            provider = self.config["provider"]
            logger.info(f"Populating models for provider: {provider}")

            self._model_combo.clear()

            if provider == "ollama":
                # Get installed Ollama models
                models = _get_ollama_models()
                logger.info(f"Found Ollama models: {models}")

                if models:
                    self._model_combo.addItems(models)
                else:
                    # No models found, add default
                    self._model_combo.addItem("llama3.2:3b")
                    logger.warning("No Ollama models found, added default")
            else:
                # Cloud provider models
                models = PROVIDERS[provider]["models"]
                logger.info(f"Cloud provider models: {models}")
                self._model_combo.addItems(models)

            preferred_model = (
                self._selected_model_by_provider.get(provider)
                or self.config.get("model", "")
            )
            if self._model_combo.count() > 0:
                selected_idx = self._model_combo.findText(preferred_model)
                if selected_idx >= 0:
                    self._model_combo.setCurrentIndex(selected_idx)
                else:
                    self._model_combo.setCurrentIndex(0)
                self.config["model"] = self._model_combo.currentText()
                self._selected_model_by_provider[provider] = self._model_combo.currentText()
                logger.info(f"Selected model: {self._model_combo.currentText()}")

        except Exception as e:
            logger.error(f"Failed to populate models: {e}", exc_info=True)
            # Fallback: add at least one model
            self._model_combo.addItem("llama-3.3-70b-versatile")
            self.config["model"] = "llama-3.3-70b-versatile"

    def _on_model_changed(self, model: str):
        model = (model or "").strip()
        if not model:
            return
        provider = self.config.get("provider", "groq")
        self.config["model"] = model
        self._selected_model_by_provider[provider] = model

    # ── Page 5: Connection Test ─────────────────────────────
    def _create_connection_test(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(44, 64, 44, 64)
        layout.setSpacing(26)

        # Header
        header = QLabel("Testing Connection")
        header.setFont(QFont(".AppleSystemUIFont", 24, QFont.Weight.Bold))
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(header)

        desc = QLabel("Verifying your AI provider connection...")
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 14px;")
        layout.addWidget(desc)

        # Status
        self._test_status = QLabel("Testing...")
        self._test_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._test_status.setFont(QFont(".AppleSystemUIFont", 16, QFont.Weight.Medium))
        self._test_status.setStyleSheet(f"color: {COLORS['text_secondary']};")
        layout.addWidget(self._test_status)

        # Progress
        self._test_progress = QProgressBar()
        self._test_progress.setRange(0, 0)  # Indeterminate
        self._test_progress.setFixedHeight(4)
        self._test_progress.setTextVisible(False)
        self._test_progress.setStyleSheet(f"""
            QProgressBar {{
                border: none;
                background: {COLORS['bg_secondary']};
                border-radius: 2px;
            }}
            QProgressBar::chunk {{
                background: {COLORS['primary']};
                border-radius: 2px;
            }}
        """)
        layout.addWidget(self._test_progress)

        layout.addStretch()

        # Navigation
        nav = QHBoxLayout()
        nav.setSpacing(12)

        back = CleanButton("Back", primary=False)
        back.clicked.connect(lambda: self.stack.setCurrentIndex(4))
        nav.addWidget(back)

        self._test_next_btn = CleanButton("Continue", primary=True)
        self._test_next_btn.setEnabled(False)
        self._test_next_btn.clicked.connect(self._on_test_next_clicked)
        nav.addWidget(self._test_next_btn)
        layout.addLayout(nav)

        return page

    def _run_connection_test(self):
        """Run connection test - called when page is shown"""
        try:
            provider = self.config["provider"]
            api_key = self.config.get("api_key", "")
            model = self.config.get("model", "")

            logger.info(f"Starting connection test for {provider}")
            self._test_status.setText("Testing...")
            self._test_status.setStyleSheet(f"color: {COLORS['text_secondary']};")
            self._test_progress.setRange(0, 0)
            self._connection_verified = False
            self._test_next_btn.setEnabled(False)
            self._test_next_btn.setText("Continue")

            self._connection_test_thread = ConnectionTestThread(provider, api_key, model)
            self._connection_test_thread.finished_signal.connect(self._on_test_finished)
            self._connection_test_thread.start()
        except Exception as e:
            logger.error(f"Failed to start connection test: {e}")
            self._on_test_finished(False, f"Test failed: {str(e)}")

    def _on_test_finished(self, success: bool, message: str):
        self._test_progress.setRange(0, 100)
        self._test_progress.setValue(100 if success else 0)
        self._test_status.setText(message)

        if success:
            self._test_status.setStyleSheet(f"color: {COLORS['success']};")
            self._connection_verified = True
            self._test_next_btn.setEnabled(True)
            self._test_next_btn.setText("Continue")
        else:
            self._test_status.setStyleSheet(f"color: {COLORS['danger']};")
            self._connection_verified = False
            self._test_next_btn.setEnabled(True)
            self._test_next_btn.setText("Retry")
            return

    def _on_test_next_clicked(self):
        if self._connection_verified:
            self.stack.setCurrentIndex(6)
        else:
            self._run_connection_test()

    # ── Page 6: Telegram (Optional) ─────────────────────────
    def _create_telegram_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(40, 30, 40, 30)
        layout.setSpacing(20)

        # Header
        header = QLabel("Telegram Bot (Optional)")
        header.setFont(QFont(".AppleSystemUIFont", 24, QFont.Weight.Bold))
        layout.addWidget(header)

        desc = QLabel(
            "Connect Elyan to Telegram for mobile access.\n"
            "You can skip this and add it later in settings."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 14px;")
        layout.addWidget(desc)

        # Bot Token
        token_label = QLabel("Bot Token:")
        token_label.setFont(QFont(".AppleSystemUIFont", 13, QFont.Weight.Medium))
        layout.addWidget(token_label)

        self._telegram_token = QLineEdit()
        self._telegram_token.setPlaceholderText("123456:ABC-DEF...")
        self._telegram_token.setFixedHeight(44)
        self._telegram_token.setStyleSheet(f"""
            QLineEdit {{
                background: {COLORS['bg_secondary']};
                border: 1px solid {COLORS['border']};
                border-radius: 8px;
                padding: 0 12px;
                font-size: 14px;
            }}
            QLineEdit:focus {{
                border: 2px solid {COLORS['primary']};
                background: {COLORS['bg']};
            }}
        """)
        layout.addWidget(self._telegram_token)

        # User ID
        uid_label = QLabel("User ID:")
        uid_label.setFont(QFont(".AppleSystemUIFont", 13, QFont.Weight.Medium))
        layout.addWidget(uid_label)

        self._telegram_uid = QLineEdit()
        self._telegram_uid.setPlaceholderText("123456789")
        self._telegram_uid.setFixedHeight(44)
        self._telegram_uid.setStyleSheet(f"""
            QLineEdit {{
                background: {COLORS['bg_secondary']};
                border: 1px solid {COLORS['border']};
                border-radius: 8px;
                padding: 0 12px;
                font-size: 14px;
            }}
            QLineEdit:focus {{
                border: 2px solid {COLORS['primary']};
                background: {COLORS['bg']};
            }}
        """)
        layout.addWidget(self._telegram_uid)

        layout.addStretch()

        # Navigation
        nav = QHBoxLayout()
        nav.setSpacing(12)

        skip = CleanButton("Skip", primary=False)
        skip.clicked.connect(lambda: self.stack.setCurrentIndex(7))
        nav.addWidget(skip)

        fwd = CleanButton("Continue", primary=True)
        fwd.clicked.connect(self._telegram_next)
        nav.addWidget(fwd)
        layout.addLayout(nav)

        return page

    def _telegram_next(self):
        token = self._telegram_token.text().strip()
        user_id = self._telegram_uid.text().strip()

        if user_id and not user_id.isdigit():
            QMessageBox.warning(self, "Warning", "User ID sadece rakamlardan oluşmalıdır.")
            return

        self.config["telegram_token"] = token
        self.config["user_id"] = user_id
        self.stack.setCurrentIndex(7)

    # ── Page 7: Personalization ─────────────────────────────
    def _create_personalization_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(40, 30, 40, 30)
        layout.setSpacing(18)

        header = QLabel("Personalization")
        header.setFont(QFont(".AppleSystemUIFont", 24, QFont.Weight.Bold))
        layout.addWidget(header)

        desc = QLabel(
            "Customize how Elyan communicates and plans complex tasks.\n"
            "You can change these later in settings."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 14px;")
        layout.addWidget(desc)

        tone_label = QLabel("Communication Tone")
        tone_label.setFont(QFont(".AppleSystemUIFont", 13, QFont.Weight.Medium))
        layout.addWidget(tone_label)
        self._tone_combo = QComboBox()
        self._tone_combo.addItem("Professional + Friendly", "professional_friendly")
        self._tone_combo.addItem("Mentor / Coaching", "mentor")
        self._tone_combo.addItem("Formal", "formal")
        self._tone_combo.setCurrentIndex(0)
        layout.addWidget(self._tone_combo)

        length_label = QLabel("Response Length")
        length_label.setFont(QFont(".AppleSystemUIFont", 13, QFont.Weight.Medium))
        layout.addWidget(length_label)
        self._length_combo = QComboBox()
        self._length_combo.addItem("Short (2-4 sentences)", "short")
        self._length_combo.addItem("Medium (4-6 sentences)", "medium")
        self._length_combo.addItem("Detailed", "detailed")
        self._length_combo.setCurrentIndex(0)
        layout.addWidget(self._length_combo)

        autonomy_label = QLabel("Autonomy Level")
        autonomy_label.setFont(QFont(".AppleSystemUIFont", 13, QFont.Weight.Medium))
        layout.addWidget(autonomy_label)
        self._autonomy_combo = QComboBox()
        self._autonomy_combo.addItem("Strict (safe, fewer actions)", "Strict")
        self._autonomy_combo.addItem("Balanced (recommended)", "Balanced")
        self._autonomy_combo.addItem("Flexible (deeper plans)", "Flexible")
        self._autonomy_combo.setCurrentIndex(1)
        layout.addWidget(self._autonomy_combo)

        depth_label = QLabel("Task Planning Depth")
        depth_label.setFont(QFont(".AppleSystemUIFont", 13, QFont.Weight.Medium))
        layout.addWidget(depth_label)
        self._planning_depth_combo = QComboBox()
        self._planning_depth_combo.addItem("Adaptive", "adaptive")
        self._planning_depth_combo.addItem("Compact", "compact")
        self._planning_depth_combo.addItem("Deep", "deep")
        self._planning_depth_combo.setCurrentIndex(0)
        layout.addWidget(self._planning_depth_combo)

        expertise_label = QLabel("Assistant Expertise")
        expertise_label.setFont(QFont(".AppleSystemUIFont", 13, QFont.Weight.Medium))
        layout.addWidget(expertise_label)
        self._expertise_combo = QComboBox()
        self._expertise_combo.addItem("Basic", "basic")
        self._expertise_combo.addItem("Advanced (recommended)", "advanced")
        self._expertise_combo.addItem("Expert", "expert")
        self._expertise_combo.setCurrentIndex(1)
        layout.addWidget(self._expertise_combo)

        access_label = QLabel("Erişim Kapsamı")
        access_label.setFont(QFont(".AppleSystemUIFont", 13, QFont.Weight.Medium))
        layout.addWidget(access_label)
        self._access_combo = QComboBox()
        self._access_combo.addItem("Geniş (ev dizini + tüm kullanıcı dizinleri)", "full")
        self._access_combo.addItem("Sadece kullanıcı klasörleri", "home_only")
        self._access_combo.setCurrentIndex(0)
        layout.addWidget(self._access_combo)

        layout.addStretch()

        nav = QHBoxLayout()
        nav.setSpacing(12)

        back = CleanButton("Back", primary=False)
        back.clicked.connect(lambda: self.stack.setCurrentIndex(6))
        nav.addWidget(back)

        complete = CleanButton("Complete Setup", primary=True)
        complete.clicked.connect(self._personalization_next)
        nav.addWidget(complete)
        layout.addLayout(nav)

        return page

    def _personalization_next(self):
        self.config["communication_tone"] = self._tone_combo.currentData()
        self.config["response_length"] = self._length_combo.currentData()
        self.config["autonomy_level"] = self._autonomy_combo.currentData()
        self.config["task_planning_depth"] = self._planning_depth_combo.currentData()
        self.config["assistant_expertise"] = self._expertise_combo.currentData()
        self.config["full_disk_access"] = self._access_combo.currentData() == "full"
        self._finish_setup()

    # ── Page 8: Completion ──────────────────────────────────
    def _create_completion_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(60, 80, 60, 60)
        layout.setSpacing(24)

        # Success icon (text-based, no emoji)
        mascot = QLabel()
        mascot_pixmap = load_brand_pixmap(size=128)
        if not mascot_pixmap.isNull():
            mascot.setPixmap(mascot_pixmap)
            mascot.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(mascot)

        icon = QLabel("✓")
        icon.setFont(QFont(".AppleSystemUIFont", 62, QFont.Weight.Thin))
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet(f"color: {COLORS['success']};")
        layout.addWidget(icon)

        # Title
        title = QLabel("Setup Complete")
        title.setFont(QFont(".AppleSystemUIFont", 28, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        # Description
        desc = QLabel(
            "Elyan hazır.\n\n"
            "Asistanın artık seçtiğin sağlayıcı ve modele sadık şekilde çalışacak."
        )
        desc.setWordWrap(True)
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 15px;")
        layout.addWidget(desc)

        layout.addStretch()

        # Finish button
        finish = CleanButton("Launch Elyan", primary=True)
        finish.clicked.connect(self._complete_wizard)
        layout.addWidget(finish)

        return page

    def _finish_setup(self):
        """Save config and show completion"""
        self._save_config()
        self.stack.setCurrentIndex(8)

    def _save_config(self):
        """Save configuration to .env with proper validation"""
        try:
            env_path = Path(__file__).parent.parent / ".env"

            # Read existing .env
            lines = []
            if env_path.exists():
                with open(env_path, 'r') as f:
                    lines = f.readlines()

            # Helper to update or add line
            def update_or_add(key: str, value: str):
                nonlocal lines
                updated = False
                for i, line in enumerate(lines):
                    if line.strip().startswith(f"{key}="):
                        lines[i] = f"{key}={value}\n"
                        updated = True
                        break
                if not updated:
                    # Find the right section to add
                    if key in ["GROQ_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY"]:
                        # Add after API Keys section
                        for i, line in enumerate(lines):
                            if "API Keys" in line:
                                # Find next empty line
                                for j in range(i, len(lines)):
                                    if lines[j].strip() == "":
                                        lines.insert(j, f"{key}={value}\n")
                                        return
                    lines.append(f"{key}={value}\n")

            # Update LLM_TYPE
            provider = self.config.get("provider", "groq")
            llm_type_map = {
                "groq": "groq",
                "gemini": "api",
                "openai": "openai",
                "ollama": "ollama"
            }
            update_or_add("LLM_TYPE", llm_type_map.get(provider, "groq"))
            update_or_add("FULL_DISK_ACCESS", "true" if self.config.get("full_disk_access", True) else "false")

            # Update API keys (only the relevant one)
            api_key = self.config.get("api_key", "")
            if provider == "groq" and api_key:
                update_or_add("GROQ_API_KEY", api_key)
            elif provider == "gemini" and api_key:
                update_or_add("GOOGLE_API_KEY", api_key)
            elif provider == "openai" and api_key:
                update_or_add("OPENAI_API_KEY", api_key)

            # Update Telegram config
            telegram_token = self.config.get("telegram_token", "")
            if telegram_token:
                update_or_add("TELEGRAM_BOT_TOKEN", telegram_token)

            user_id = self.config.get("user_id", "")
            if user_id:
                update_or_add("ALLOWED_USER_IDS", user_id)

            # Write back to .env
            with open(env_path, 'w') as f:
                f.writelines(lines)

            logger.info(f"Configuration saved: LLM={provider}, Model={self.config.get('model')}")

            # Also save to settings.json via SettingsPanel
            try:
                settings = SettingsPanel()
                update_data = {
                    "llm_provider": provider,
                    "llm_model": self.config.get("model", "llama-3.3-70b-versatile"),
                    "api_key": api_key,
                    "llm_sticky_selection": True,
                    "llm_fallback_mode": "conservative",
                    "llm_fallback_order": [provider, "groq", "gemini", "openai", "ollama"],
                    "full_disk_access": bool(self.config.get("full_disk_access", True)),
                    "autonomy_level": self.config.get("autonomy_level", "Balanced"),
                    "communication_tone": self.config.get("communication_tone", "professional_friendly"),
                    "response_length": self.config.get("response_length", "short"),
                    "task_planning_depth": self.config.get("task_planning_depth", "adaptive"),
                    "assistant_expertise": self.config.get("assistant_expertise", "advanced"),
                    "show_first_run_tips": True,
                    "onboarding_completed": True,
                }
                if telegram_token:
                    update_data["telegram_token"] = telegram_token
                if user_id:
                    update_data["allowed_user_ids"] = [user_id]
                if provider == "ollama":
                    update_data["ollama_host"] = self.config.get("ollama_host", "http://localhost:11434")
                settings.update(update_data)
                logger.info("Settings.json updated")
            except Exception as e:
                logger.warning(f"Settings.json update failed: {e}")

        except Exception as e:
            logger.error(f"Failed to save config: {e}", exc_info=True)
            QMessageBox.critical(
                self,
                "Configuration Error",
                f"Failed to save configuration:\n{str(e)}\n\nPlease check file permissions."
            )

    def _complete_wizard(self):
        self.setup_completed = True
        self.finished.emit(self.config)
        self.accept()

    def closeEvent(self, event):
        """Handle wizard close - cleanup threads"""
        try:
            if self._ollama_install_thread and self._ollama_install_thread.isRunning():
                self._ollama_install_thread.cancel()
                self._ollama_install_thread.wait(3000)

            if self._connection_test_thread and self._connection_test_thread.isRunning():
                self._connection_test_thread.wait(3000)
        except Exception as e:
            logger.error(f"Cleanup error: {e}")

        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    wizard = AppleSetupWizard()
    wizard.show()
    sys.exit(app.exec())
