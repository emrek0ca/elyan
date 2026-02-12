"""
Wiqo Setup Wizard v19.1 - Professional onboarding with unified AI configuration
"""

import os
import sys
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QStackedWidget,
    QLineEdit, QPushButton, QFrame, QProgressBar, QApplication,
    QDialog, QComboBox, QMessageBox
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QColor

from ui.components import GlassFrame, AnimatedButton, SectionHeader, PulseLabel
from utils.logger import get_logger

logger = get_logger("setup_wizard")

# ── Provider definitions ──────────────────────────────────
PROVIDERS = {
    "groq": {
        "name": "Groq",
        "desc": "Bulut API - En hızlı yanıt süresi",
        "badge": "Ücretsiz",
        "badge_color": "#34C759",
        "needs_key": True,
        "models": ["llama-3.3-70b-versatile", "mixtral-8x7b-32768", "llama-3.1-8b-instant"],
        "env_key": "GROQ_API_KEY",
        "llm_type": "groq",
    },
    "gemini": {
        "name": "Google Gemini",
        "desc": "Bulut API - Güçlü ve çok yönlü",
        "badge": "Ücretsiz Katman",
        "badge_color": "#34C759",
        "needs_key": True,
        "models": ["gemini-2.0-flash", "gemini-1.5-pro", "gemini-1.5-flash"],
        "env_key": "GOOGLE_API_KEY",
        "llm_type": "api",
    },
    "openai": {
        "name": "OpenAI",
        "desc": "Bulut API - En güçlü modeller",
        "badge": "Ücretli",
        "badge_color": "#FF9500",
        "needs_key": True,
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo"],
        "env_key": "OPENAI_API_KEY",
        "llm_type": "openai",
    },
    "ollama": {
        "name": "Ollama (Yerel)",
        "desc": "Bilgisayarınızda çalışır - Gizlilik",
        "badge": "Yerel",
        "badge_color": "#7196A2",
        "needs_key": False,
        "models": [],
        "env_key": None,
        "llm_type": "ollama",
    },
}


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


class ProviderCard(QFrame):
    """Clickable provider selection card"""
    clicked = pyqtSignal(str)

    def __init__(self, provider_id: str, info: dict, parent=None):
        super().__init__(parent)
        self.provider_id = provider_id
        self._selected = False
        self.setFixedHeight(72)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._setup(info)

    def _setup(self, info):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)

        # Provider name + description
        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)

        name = QLabel(info["name"])
        name.setFont(QFont("SF Pro Display", 15, QFont.Weight.DemiBold))
        name.setStyleSheet("color: #252F33; background: transparent;")
        text_layout.addWidget(name)

        desc = QLabel(info["desc"])
        desc.setStyleSheet("color: #8E8E93; font-size: 12px; background: transparent;")
        text_layout.addWidget(desc)

        layout.addLayout(text_layout, 1)

        # Badge
        badge = QLabel(info["badge"])
        badge.setFixedHeight(24)
        badge.setStyleSheet(f"""
            QLabel {{
                background-color: {info['badge_color']}; color: white;
                border-radius: 12px; padding: 2px 12px;
                font-size: 11px; font-weight: bold;
            }}
        """)
        layout.addWidget(badge)

        self._update_style()

    def _update_style(self):
        border = "#7196A2" if self._selected else "#E5E5EA"
        bg = "#F0F7F9" if self._selected else "#FFFFFF"
        self.setStyleSheet(f"""
            ProviderCard {{
                background-color: {bg};
                border: 2px solid {border};
                border-radius: 12px;
            }}
        """)

    def set_selected(self, selected: bool):
        self._selected = selected
        self._update_style()

    def mousePressEvent(self, event):
        self.clicked.emit(self.provider_id)
        super().mousePressEvent(event)


class SetupWizard(QDialog):
    """Multi-page wizard for first-run configuration"""

    finished = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Wiqo Kurulum Sihirbazı")
        self.setFixedSize(620, 560)
        self.setModal(True)
        self.config: Dict[str, Any] = {
            "provider": "groq",
            "llm_type": "groq",
            "api_key": "",
            "ollama_host": "http://localhost:11434",
            "model": "llama-3.3-70b-versatile",
            "telegram_token": "",
            "user_id": "",
        }
        self.setup_completed = False
        self._provider_cards: dict[str, ProviderCard] = {}
        self._setup_ui()

    # ── UI Setup ─────────────────────────────────────────

    def _setup_ui(self):
        self.setStyleSheet("QWidget { background-color: #FFFFFF; color: #252F33; }")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._create_welcome_page())      # 0
        self.stack.addWidget(self._create_provider_page())      # 1
        self.stack.addWidget(self._create_model_page())         # 2
        self.stack.addWidget(self._create_telegram_page())      # 3
        self.stack.addWidget(self._create_verification_page())  # 4

        layout.addWidget(self.stack)

    # ── Page 0: Welcome ──────────────────────────────────

    def _create_welcome_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(40, 50, 40, 40)
        layout.setSpacing(16)

        logo = QLabel("WIQO")
        logo.setFont(QFont("SF Pro Display", 48, QFont.Weight.Bold))
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setStyleSheet("color: #252F33; letter-spacing: -2px;")
        layout.addWidget(logo)

        title = QLabel("Akıllı Dijital Asistan")
        title.setFont(QFont("SF Pro Display", 20, QFont.Weight.DemiBold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("color: #7196A2;")
        layout.addWidget(title)

        desc = QLabel(
            "Wiqo, bilgisayarınızı doğal dille kontrol etmenizi sağlar.\n"
            "Kurulum sadece 2 dakika sürer."
        )
        desc.setWordWrap(True)
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setStyleSheet("color: #8E8E93; font-size: 14px;")
        layout.addWidget(desc)

        layout.addStretch()

        btn = AnimatedButton("Başlayalım", primary=True)
        btn.clicked.connect(lambda: self.stack.setCurrentIndex(1))
        layout.addWidget(btn)

        return page

    # ── Page 1: Provider Selection ───────────────────────

    def _create_provider_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(40, 30, 40, 30)
        layout.setSpacing(12)

        layout.addWidget(SectionHeader("Adım 1: Yapay Zeka Motoru"))

        desc = QLabel("Wiqo'nun zeka kaynağını seçin:")
        desc.setStyleSheet("color: #8E8E93; font-size: 13px;")
        layout.addWidget(desc)

        # Provider cards
        for pid, info in PROVIDERS.items():
            card = ProviderCard(pid, info)
            card.clicked.connect(self._on_provider_selected)
            self._provider_cards[pid] = card
            layout.addWidget(card)

        # API Key input (visible for cloud providers)
        self._api_frame = QFrame()
        api_layout = QVBoxLayout(self._api_frame)
        api_layout.setContentsMargins(0, 8, 0, 0)

        self._api_label = QLabel("API Anahtarı:")
        self._api_label.setStyleSheet("color: #252F33; font-weight: bold; font-size: 13px;")
        api_layout.addWidget(self._api_label)

        self._api_input = QLineEdit()
        self._api_input.setPlaceholderText("API anahtarınızı yapıştırın...")
        self._api_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_input.setStyleSheet("""
            QLineEdit {
                background: #F2F2F7; border: 1px solid #D1D1D6;
                border-radius: 8px; padding: 10px; color: #252F33; font-size: 13px;
            }
            QLineEdit:focus { border-color: #7196A2; background: #FFFFFF; }
        """)
        api_layout.addWidget(self._api_input)
        layout.addWidget(self._api_frame)

        layout.addStretch()

        # Navigation
        nav = QHBoxLayout()
        back = AnimatedButton("Geri", primary=False)
        back.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        nav.addWidget(back)

        fwd = AnimatedButton("Devam", primary=True)
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

        needs_key = PROVIDERS[provider_id]["needs_key"]
        self._api_frame.setVisible(needs_key)

    def _provider_next(self):
        p = self.config["provider"]
        if PROVIDERS[p]["needs_key"]:
            key = self._api_input.text().strip()
            if not key:
                QMessageBox.warning(self, "Uyarı", "Lütfen API anahtarını girin.")
                return
            self.config["api_key"] = key

        # Prepare model page
        self._populate_models()
        self.stack.setCurrentIndex(2)

    # ── Page 2: Model Selection ──────────────────────────

    def _create_model_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(40, 30, 40, 30)
        layout.setSpacing(16)

        layout.addWidget(SectionHeader("Adım 2: Model Seçimi"))

        self._model_desc = QLabel("")
        self._model_desc.setStyleSheet("color: #8E8E93; font-size: 13px;")
        self._model_desc.setWordWrap(True)
        layout.addWidget(self._model_desc)

        self._model_combo = QComboBox()
        self._model_combo.setStyleSheet("""
            QComboBox {
                background: #F2F2F7; border: 1px solid #D1D1D6;
                border-radius: 8px; padding: 10px; color: #252F33; font-size: 14px;
            }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView {
                background: #FFFFFF; color: #252F33;
                selection-background-color: #7196A2; selection-color: white;
            }
        """)
        layout.addWidget(self._model_combo)

        # Ollama-specific: no models warning
        self._ollama_warning = QLabel("")
        self._ollama_warning.setWordWrap(True)
        self._ollama_warning.setStyleSheet("color: #FF9500; font-size: 12px;")
        self._ollama_warning.hide()
        layout.addWidget(self._ollama_warning)

        layout.addStretch()

        nav = QHBoxLayout()
        back = AnimatedButton("Geri", primary=False)
        back.clicked.connect(lambda: self.stack.setCurrentIndex(1))
        nav.addWidget(back)

        fwd = AnimatedButton("Devam", primary=True)
        fwd.clicked.connect(self._model_next)
        nav.addWidget(fwd)
        layout.addLayout(nav)

        return page

    def _populate_models(self):
        self._model_combo.clear()
        self._ollama_warning.hide()

        p = self.config["provider"]
        info = PROVIDERS[p]

        if p == "ollama":
            models = _get_ollama_models()
            if models:
                self._model_combo.addItems(models)
                self._model_desc.setText("Bilgisayarınızda yüklü olan modeller:")
            else:
                self._model_combo.addItems(["llama3.2:3b", "llama3.1:8b", "mistral"])
                self._model_desc.setText("Yüklü model bulunamadı. Önerilen modeller:")
                self._ollama_warning.setText(
                    "Ollama yüklü değil veya model bulunamadı.\n"
                    "Terminalde 'ollama pull llama3.2:3b' komutunu çalıştırın."
                )
                self._ollama_warning.show()
        else:
            self._model_combo.addItems(info["models"])
            self._model_desc.setText(f"{info['name']} için kullanılabilir modeller:")

    def _model_next(self):
        self.config["model"] = self._model_combo.currentText()
        self.stack.setCurrentIndex(3)

    # ── Page 3: Telegram ─────────────────────────────────

    def _create_telegram_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(40, 30, 40, 30)
        layout.setSpacing(14)

        layout.addWidget(SectionHeader("Adım 3: Telegram Bağlantısı"))

        instructions = QLabel(
            "1. Telegram'da @BotFather'ı bulun\n"
            "2. /newbot komutuyla bir bot oluşturun\n"
            "3. Size verilen token'ı aşağıya yapıştırın"
        )
        instructions.setStyleSheet("color: #8E8E93; font-size: 13px; line-height: 1.5;")
        layout.addWidget(instructions)

        self._tg_input = QLineEdit()
        self._tg_input.setPlaceholderText("Bot Token (Örn: 123456:ABC-DEF...)")
        self._tg_input.setStyleSheet("""
            QLineEdit {
                background: #F2F2F7; border: 1px solid #D1D1D6;
                border-radius: 8px; padding: 10px; color: #252F33; font-size: 13px;
            }
            QLineEdit:focus { border-color: #7196A2; background: #FFFFFF; }
        """)
        layout.addWidget(self._tg_input)

        layout.addStretch()

        nav = QHBoxLayout()
        back = AnimatedButton("Geri", primary=False)
        back.clicked.connect(lambda: self.stack.setCurrentIndex(2))
        nav.addWidget(back)

        fwd = AnimatedButton("Doğrula", primary=True)
        fwd.clicked.connect(self._tg_next)
        nav.addWidget(fwd)
        layout.addLayout(nav)

        return page

    def _tg_next(self):
        token = self._tg_input.text().strip()
        if not token:
            QMessageBox.warning(self, "Uyarı", "Lütfen Telegram bot token'ını girin.")
            return
        self.config["telegram_token"] = token
        self.stack.setCurrentIndex(4)
        self._start_verification()

    # ── Page 4: Verification ─────────────────────────────

    def _create_verification_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(40, 60, 40, 40)
        layout.setSpacing(24)

        self._v_status = QLabel("Bağlantı Doğrulanıyor...")
        self._v_status.setFont(QFont("SF Pro Display", 22, QFont.Weight.Bold))
        self._v_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._v_status)

        self._v_pulse = PulseLabel("Telefonunuzdan botunuza herhangi bir mesaj gönderin.")
        self._v_pulse.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._v_pulse)

        self._v_progress = QProgressBar()
        self._v_progress.setRange(0, 0)
        self._v_progress.setStyleSheet("""
            QProgressBar { background: #F2F2F7; border-radius: 4px; height: 6px; border: none; }
            QProgressBar::chunk { background: #7196A2; border-radius: 4px; }
        """)
        layout.addWidget(self._v_progress)

        layout.addStretch()

        self._finish_btn = AnimatedButton("Kurulumu Tamamla", primary=True)
        self._finish_btn.hide()
        self._finish_btn.clicked.connect(self._on_finish)
        layout.addWidget(self._finish_btn)

        return page

    def _start_verification(self):
        self._v_pulse.start()
        self._polling = True
        self._last_update_id = 0
        self._v_timer = QTimer(self)
        self._v_timer.timeout.connect(self._check_verification)
        self._v_timer.start(3000)

    def _check_verification(self):
        if not self._polling:
            return

        token = self.config["telegram_token"]
        try:
            import requests
            resp = requests.get(
                f"https://api.telegram.org/bot{token}/getUpdates",
                params={"offset": self._last_update_id + 1, "timeout": 1},
                timeout=5
            )
            data = resp.json()
            if data.get("ok") and data.get("result"):
                update = data["result"][-1]
                user_id = update.get("message", {}).get("from", {}).get("id")
                self.config["user_id"] = str(user_id) if user_id else ""
                self._on_verification_success()
        except Exception as e:
            logger.debug(f"Verification polling: {e}")

    def _on_verification_success(self):
        self._polling = False
        self._v_timer.stop()
        self._v_status.setText("Bağlantı Başarılı")
        self._v_status.setStyleSheet("color: #34C759; font-weight: bold;")
        self._v_pulse.stop()
        self._v_pulse.setText(f"Telegram bağlantısı kuruldu (ID: {self.config['user_id']}).")
        self._v_progress.setRange(0, 100)
        self._v_progress.setValue(100)
        self._finish_btn.show()

    # ── Finish & Save ────────────────────────────────────

    def _on_finish(self):
        p = self.config["provider"]
        info = PROVIDERS[p]

        # Build .env content
        env_lines = [
            f"TELEGRAM_BOT_TOKEN={self.config['telegram_token']}",
            f"ALLOWED_USER_IDS={self.config['user_id']}",
            f"LLM_TYPE={info['llm_type']}",
            f"OLLAMA_HOST={self.config['ollama_host']}",
            f"OLLAMA_MODEL={self.config['model']}",
        ]

        if info["needs_key"] and info["env_key"]:
            env_lines.append(f"{info['env_key']}={self.config['api_key']}")

        env_path = Path(__file__).parent.parent / ".env"
        with open(env_path, "w") as f:
            f.write("\n".join(env_lines) + "\n")

        # Save to settings.json
        try:
            from config.settings_manager import SettingsPanel
            settings = SettingsPanel()
            settings.update({
                "telegram_token": self.config["telegram_token"],
                "allowed_user_ids": [self.config["user_id"]] if self.config["user_id"] else [],
                "llm_provider": info["llm_type"],
                "llm_model": self.config["model"],
                "api_key": self.config.get("api_key", ""),
                "ollama_host": self.config["ollama_host"],
            })
        except Exception as e:
            logger.error(f"Settings save error: {e}")

        logger.info(f"Setup completed: provider={p}, model={self.config['model']}")
        self.setup_completed = True
        self.finished.emit(self.config)
        self.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    wizard = SetupWizard()
    wizard.show()
    sys.exit(app.exec())
