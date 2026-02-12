"""
Wiqo Settings Panel - Apple-inspired, clean, professional
3 categories: AI, Telegram, General
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QFrame, QComboBox, QPushButton,
    QSlider, QSpinBox, QStackedWidget, QScrollArea
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread
from PyQt6.QtGui import QFont

from ui.components import (
    WiqoTheme as T, GlassFrame, AnimatedButton, SidebarButton, 
    Switch, SectionHeader, Divider
)
from core.pricing_tracker import DEFAULT_PRICING_PER_1K, get_pricing_tracker

# Provider info
PROVIDERS = {
    "groq": {
        "label": "Groq",
        "desc": "Ultra-fast, free cloud API",
        "tag": "Free",
        "tag_color": "#34C759",
        "models": ["llama-3.3-70b-versatile", "mixtral-8x7b-32768", "llama-3.1-8b-instant"],
        "llm_type": "groq",
        "key_env": "GROQ_API_KEY",
        "needs_key": True,
    },
    "gemini": {
        "label": "Google Gemini",
        "desc": "Powerful, free tier available",
        "tag": "Free Tier",
        "tag_color": "#34C759",
        "models": ["gemini-2.0-flash", "gemini-1.5-pro", "gemini-1.5-flash"],
        "llm_type": "api",
        "key_env": "GOOGLE_API_KEY",
        "needs_key": True,
    },
    "openai": {
        "label": "OpenAI",
        "desc": "GPT-4o, industry standard",
        "tag": "Paid",
        "tag_color": "#FF9500",
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"],
        "llm_type": "openai",
        "key_env": "OPENAI_API_KEY",
        "needs_key": True,
    },
    "ollama": {
        "label": "Ollama",
        "desc": "100% local, private",
        "tag": "Local",
        "tag_color": "#007AFF",
        "models": [],
        "llm_type": "ollama",
        "key_env": None,
        "needs_key": False,
    },
}


# ═══════════════════════════════════════════════════════════════
# API Test Worker (background thread)
# ═══════════════════════════════════════════════════════════════
class _APITestWorker(QThread):
    result = pyqtSignal(bool, str)

    def __init__(self, provider_key: str, api_key: str):
        super().__init__()
        self._provider = provider_key
        self._api_key = api_key

    def run(self):
        try:
            import httpx
            if self._provider == "groq":
                r = httpx.get("https://api.groq.com/openai/v1/models",
                              headers={"Authorization": f"Bearer {self._api_key}"}, timeout=8)
                self.result.emit(r.status_code == 200,
                                 "Basarili" if r.status_code == 200 else f"Hata: {r.status_code}")
            elif self._provider == "gemini":
                r = httpx.get(f"https://generativelanguage.googleapis.com/v1beta/models?key={self._api_key}", timeout=8)
                self.result.emit(r.status_code == 200,
                                 "Basarili" if r.status_code == 200 else f"Hata: {r.status_code}")
            elif self._provider == "openai":
                r = httpx.get("https://api.openai.com/v1/models",
                              headers={"Authorization": f"Bearer {self._api_key}"}, timeout=8)
                self.result.emit(r.status_code == 200,
                                 "Basarili" if r.status_code == 200 else f"Hata: {r.status_code}")
            else:
                self.result.emit(False, "Bilinmeyen provider")
        except Exception as e:
            self.result.emit(False, str(e))


class _Card(GlassFrame):
    """Internal card component using the standard GlassFrame"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"""
            background: {T.CARD_BG};
            border: 1px solid {T.BORDER_LIGHT};
            border-radius: 14px;
        """)
        # GlassFrame already handles basic setup, refine layout
        self._row_layout = QVBoxLayout(self)
        self._row_layout.setContentsMargins(8, 8, 8, 8)
        self._row_layout.setSpacing(8)

    @staticmethod
    def row(label_text: str, control: QWidget, desc: str = "") -> QWidget:
        """Create a premium label + control row"""
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(24, 14, 24, 14)
        h.setSpacing(16)

        left = QVBoxLayout()
        left.setSpacing(4)
        lbl = QLabel(label_text)
        lbl.setFont(QFont(T.FONT_UI, 13, QFont.Weight.Medium))
        lbl.setStyleSheet(f"color: {T.TEXT_PRIMARY}; background: transparent;")
        left.addWidget(lbl)
        if desc:
            d = QLabel(desc)
            d.setFont(QFont(T.FONT_UI, 11))
            d.setStyleSheet(f"color: {T.TEXT_SECONDARY}; background: transparent;")
            d.setWordWrap(True)
            left.addWidget(d)
        h.addLayout(left, 1)
        h.addWidget(control)
        return w


def _styled_combo(items: list, width: int = 200) -> QComboBox:
    c = QComboBox()
    c.addItems(items)
    c.setFixedWidth(width)
    c.setFixedHeight(34)
    # Applying glassmorphic combo styling
    c.setStyleSheet(f"""
        QComboBox {{
            background: {T.BG_SECONDARY};
            border: 1px solid {T.BORDER_LIGHT};
            border-radius: 8px;
            padding: 0 12px;
            font-size: 13px;
            color: {T.TEXT_PRIMARY};
            font-family: "{T.FONT_UI}";
        }}
        QComboBox::drop-down {{ border: none; width: 28px; }}
        QComboBox QAbstractItemView {{
            background: {T.CARD_BG};
            border: 1px solid {T.BORDER_LIGHT};
            border-radius: 8px;
            selection-background-color: {T.ACCENT_BLUE};
            selection-color: white;
            outline: none;
        }}
    """)
    return c


def _styled_input(placeholder: str = "", password: bool = False, width: int = 240) -> QLineEdit:
    e = QLineEdit()
    e.setPlaceholderText(placeholder)
    if password:
        e.setEchoMode(QLineEdit.EchoMode.Password)
    e.setFixedHeight(34)
    e.setMinimumWidth(width)
    e.setStyleSheet(f"""
        QLineEdit {{
            background: {T.BG_SECONDARY};
            border: 1px solid {T.BORDER_LIGHT};
            border-radius: 8px;
            padding: 0 12px;
            font-size: 13px;
            color: {T.TEXT_PRIMARY};
            font-family: "{T.FONT_UI}";
        }}
        QLineEdit:focus {{
            border: 1px solid {T.ACCENT_BLUE};
            background: {T.CARD_BG};
        }}
    """)
    return e


def _styled_btn(text: str, primary: bool = False) -> AnimatedButton:
    # Using the imported AnimatedButton
    btn = AnimatedButton(text, primary=primary)
    btn.setFixedHeight(34)
    return btn


def _styled_check(checked: bool = False) -> Switch:
    # Using the primitive Switch from components.py
    sw = Switch(checked)
    return sw


def _switch_checked(sw: Switch) -> bool:
    """Read switch value in a backwards-compatible way."""
    if hasattr(sw, "is_checked"):
        return bool(sw.is_checked())
    return bool(getattr(sw, "_checked", False))


def _set_switch_checked(sw: Switch, value: bool):
    """Set switch value in a backwards-compatible way."""
    if hasattr(sw, "set_checked"):
        sw.set_checked(bool(value))
        return
    if hasattr(sw, "setChecked"):
        sw.setChecked(bool(value))
        return
    setattr(sw, "_checked", bool(value))


# ═══════════════════════════════════════════════════════════════
# AI Settings Page
# ═══════════════════════════════════════════════════════════════
class _AIPage(QWidget):
    settings_changed = pyqtSignal(dict)

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self.config = config
        self._worker = None
        self._model_memory: dict[str, str] = {}
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # -- Provider --
        layout.addWidget(SectionHeader("AI Provider"))

        provider_card = _Card()
        pc_layout = provider_card._row_layout

        self._provider_combo = _styled_combo(
            [PROVIDERS[k]["label"] for k in PROVIDERS], width=220
        )
        self._provider_combo.currentTextChanged.connect(self._on_provider_change)
        pc_layout.addWidget(_Card.row("Provider", self._provider_combo, "Wiqo'nun kullanacağı AI servisi"))

        pc_layout.addWidget(Divider())

        # API Key row
        key_row = QWidget()
        key_row.setStyleSheet("background: transparent;")
        kr_layout = QHBoxLayout(key_row)
        kr_layout.setContentsMargins(20, 12, 20, 12)
        kr_layout.setSpacing(12)

        kr_left = QVBoxLayout()
        kr_left.setSpacing(2)
        kr_lbl = QLabel("API Key")
        kr_lbl.setFont(QFont(T.FONT_UI, 13, QFont.Weight.Medium))
        kr_lbl.setStyleSheet(f"color: {T.TEXT_PRIMARY}; background: transparent;")
        kr_left.addWidget(kr_lbl)
        self._key_status = QLabel("")
        self._key_status.setFont(QFont(T.FONT_UI, 11))
        self._key_status.setStyleSheet(f"color: {T.TEXT_SECONDARY}; background: transparent;")
        kr_left.addWidget(self._key_status)
        kr_layout.addLayout(kr_left, 1)

        self._api_input = _styled_input("API key girin", password=True, width=200)
        self._api_input.textChanged.connect(self._on_change)
        kr_layout.addWidget(self._api_input)

        self._test_btn = _styled_btn("Test")
        self._test_btn.setFixedWidth(64)
        self._test_btn.clicked.connect(self._test_api)
        kr_layout.addWidget(self._test_btn)

        self._api_row = key_row
        pc_layout.addWidget(key_row)

        pc_layout.addWidget(Divider())

        self._ollama_host_input = _styled_input("http://localhost:11434", width=240)
        self._ollama_host_input.setText(self.config.get("ollama_host", "http://localhost:11434"))
        self._ollama_host_input.textChanged.connect(self._on_change)
        self._ollama_host_row = _Card.row("Ollama Host", self._ollama_host_input, "Yerel model sunucusu adresi")
        pc_layout.addWidget(self._ollama_host_row)

        layout.addWidget(provider_card)

        # -- Model --
        layout.addWidget(SectionHeader("Model"))

        model_card = _Card()
        mc_layout = model_card._row_layout

        self._model_combo = _styled_combo([], width=260)
        self._model_combo.setEditable(True)
        self._model_combo.currentTextChanged.connect(self._on_change)
        mc_layout.addWidget(_Card.row("Model", self._model_combo, "Kullanılacak AI modeli"))

        layout.addWidget(model_card)

        # -- Advanced --
        layout.addWidget(SectionHeader("Advanced"))

        adv_card = _Card()
        ac_layout = adv_card._row_layout

        # Temperature
        temp_w = QWidget()
        temp_w.setStyleSheet("background: transparent;")
        tw_layout = QHBoxLayout(temp_w)
        tw_layout.setContentsMargins(0, 0, 0, 0)
        tw_layout.setSpacing(12)
        
        self._temp_slider = QSlider(Qt.Orientation.Horizontal)
        self._temp_slider.setRange(0, 100)
        self._temp_slider.setValue(70)
        self._temp_slider.setFixedWidth(160)
        self._temp_slider.setStyleSheet(f"""
            QSlider::groove:horizontal {{ background: {T.BG_SECONDARY}; height: 4px; border-radius: 2px; }}
            QSlider::handle:horizontal {{
                background: {T.ACCENT_BLUE}; width: 16px; height: 16px;
                margin: -6px 0; border-radius: 8px;
            }}
            QSlider::sub-page:horizontal {{ background: {T.ACCENT_BLUE}; border-radius: 2px; }}
        """)
        self._temp_slider.valueChanged.connect(self._on_temp)
        tw_layout.addWidget(self._temp_slider)
        
        self._temp_label = QLabel("0.7")
        self._temp_label.setFixedWidth(32)
        self._temp_label.setStyleSheet(f"color: {T.TEXT_SECONDARY}; font-size: 13px; font-weight: 500;")
        tw_layout.addWidget(self._temp_label)

        ac_layout.addWidget(_Card.row("Temperature", temp_w, "0.0: Tutarlı, 1.0: Yaratıcı"))

        ac_layout.addWidget(Divider())

        # Max tokens
        self._tokens_spin = QSpinBox()
        self._tokens_spin.setRange(256, 16384)
        self._tokens_spin.setValue(2048)
        self._tokens_spin.setFixedWidth(100)
        self._tokens_spin.setFixedHeight(34)
        self._tokens_spin.setStyleSheet(f"""
            QSpinBox {{
                background: {T.BG_SECONDARY};
                border: 1px solid {T.BORDER_LIGHT};
                border-radius: 8px;
                padding: 0 10px;
                font-size: 13px;
                color: {T.TEXT_PRIMARY};
            }}
        """)
        self._tokens_spin.valueChanged.connect(self._on_change)
        ac_layout.addWidget(_Card.row("Max Token", self._tokens_spin, "Yanıt uzunluğu limiti"))

        ac_layout.addWidget(Divider())

        # Cost saver
        self._cost_guard = _styled_check(self.config.get("cost_guard", True))
        self._cost_guard.toggled.connect(self._on_change)
        ac_layout.addWidget(_Card.row("Cost Saver", self._cost_guard, "LLM çağrılarını minimize et, token tüketimini düşür"))

        ac_layout.addWidget(Divider())

        self._sticky_switch = _styled_check(self.config.get("llm_sticky_selection", True))
        self._sticky_switch.toggled.connect(self._on_change)
        ac_layout.addWidget(_Card.row("Model Stickiness", self._sticky_switch, "Seçilen provider/model öncelikli ve sabit çalışsın"))

        ac_layout.addWidget(Divider())

        self._fallback_combo = _styled_combo(["conservative", "aggressive"], width=160)
        self._fallback_combo.setCurrentText(self.config.get("llm_fallback_mode", "conservative"))
        self._fallback_combo.currentTextChanged.connect(self._on_change)
        ac_layout.addWidget(_Card.row("Fallback Mode", self._fallback_combo, "Conservative: yalnız seçilen provider, Aggressive: sıradaki provider'lara geç"))

        ac_layout.addWidget(Divider())

        # Autonomy / planning depth
        self._autonomy_combo = _styled_combo(["Strict", "Balanced", "Flexible"], width=160)
        self._autonomy_combo.setCurrentText(self.config.get("autonomy_level", "Balanced"))
        self._autonomy_combo.currentTextChanged.connect(self._on_change)
        ac_layout.addWidget(_Card.row("Autonomy", self._autonomy_combo, "Görevleri ne kadar agresif planlasın?"))

        self._planning_combo = _styled_combo(["adaptive", "compact", "deep"], width=160)
        self._planning_combo.setCurrentText(self.config.get("task_planning_depth", "adaptive"))
        self._planning_combo.currentTextChanged.connect(self._on_change)
        ac_layout.addWidget(_Card.row("Planning Depth", self._planning_combo, "Alt görev parçalama derinliği"))

        # Max steps slider
        max_steps_w = QWidget()
        ms_layout = QHBoxLayout(max_steps_w)
        ms_layout.setContentsMargins(0, 0, 0, 0)
        ms_layout.setSpacing(10)
        self._steps_slider = QSlider(Qt.Orientation.Horizontal)
        self._steps_slider.setRange(3, 20)
        self._steps_slider.setValue(self.config.get("planner_max_steps", 10))
        self._steps_slider.setFixedWidth(200)
        self._steps_slider.setStyleSheet(f"""
            QSlider::groove:horizontal {{ background: {T.BG_SECONDARY}; height: 4px; border-radius: 2px; }}
            QSlider::handle:horizontal {{
                background: {T.ACCENT_BLUE}; width: 14px; height: 14px;
                margin: -5px 0; border-radius: 7px;
            }}
            QSlider::sub-page:horizontal {{ background: {T.ACCENT_BLUE}; border-radius: 2px; }}
        """)
        self._steps_slider.valueChanged.connect(self._on_steps_change)
        self._steps_label = QLabel(str(self._steps_slider.value()))
        self._steps_label.setStyleSheet(f"color: {T.TEXT_SECONDARY}; font-size: 13px;")
        ms_layout.addWidget(self._steps_slider)
        ms_layout.addWidget(self._steps_label)

        ac_layout.addWidget(_Card.row("Max Steps", max_steps_w, "Plan başına alt görev sınırı"))

        layout.addWidget(adv_card)
        layout.addStretch()

        # -- Init values --
        current_provider = self.config.get("llm_provider", "groq")
        for label, info in PROVIDERS.items():
            if label == current_provider or info["llm_type"] == current_provider:
                self._provider_combo.setCurrentText(info["label"])
                break

        self._api_input.setText(self.config.get("api_key", ""))
        self._temp_slider.setValue(int(self.config.get("llm_temperature", 0.7) * 100))
        self._tokens_spin.setValue(self.config.get("llm_max_tokens", 2048))
        self._steps_slider.setValue(self.config.get("planner_max_steps", 10))
        self._steps_label.setText(str(self._steps_slider.value()))
        _set_switch_checked(self._cost_guard, self.config.get("cost_guard", True))
        _set_switch_checked(self._sticky_switch, self.config.get("llm_sticky_selection", True))

        # Trigger provider change to set up model list
        self._on_provider_change(self._provider_combo.currentText())

        # Set model after populate
        saved_model = self.config.get("llm_model", "")
        if saved_model:
            idx = self._model_combo.findText(saved_model)
            if idx >= 0:
                self._model_combo.setCurrentIndex(idx)
            else:
                self._model_combo.setCurrentText(saved_model)

    def _get_provider_key(self) -> str:
        text = self._provider_combo.currentText()
        for key, info in PROVIDERS.items():
            if info["label"] == text:
                return key
        return "groq"

    def _on_provider_change(self, text: str):
        pkey = self._get_provider_key()
        info = PROVIDERS.get(pkey, {})
        previous_model = self._model_combo.currentText().strip()
        if previous_model:
            prev_provider = self.config.get("llm_provider", "groq")
            self._model_memory[str(prev_provider)] = previous_model

        # Show/hide API key
        self._api_row.setVisible(info.get("needs_key", True))
        self._ollama_host_row.setVisible(pkey == "ollama")

        # Populate models
        self._model_combo.blockSignals(True)
        self._model_combo.clear()
        if pkey == "ollama":
            self._load_ollama_models()
        else:
            self._model_combo.addItems(info.get("models", []))
        self._model_combo.blockSignals(False)

        preferred_model = (
            self._model_memory.get(pkey)
            or self.config.get("llm_model", "")
        )
        if preferred_model:
            idx = self._model_combo.findText(preferred_model)
            if idx >= 0:
                self._model_combo.setCurrentIndex(idx)
            else:
                self._model_combo.setCurrentText(preferred_model)
        self.config["llm_provider"] = pkey

        self._key_status.setText("")
        self._fallback_combo.setEnabled(not _switch_checked(self._sticky_switch))
        self._on_change()

    def _load_ollama_models(self):
        try:
            import subprocess
            result = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=3)
            models = []
            for line in result.stdout.strip().splitlines()[1:]:
                parts = line.split()
                if parts:
                    models.append(parts[0])
            if models:
                self._model_combo.addItems(models)
            else:
                self._model_combo.addItems(["llama3.2:3b", "llama3.1:8b", "mistral"])
        except Exception:
            self._model_combo.addItems(["llama3.2:3b", "llama3.1:8b", "mistral"])

    def _on_temp(self, val: int):
        self._temp_label.setText(f"{val / 100:.1f}")
        self._on_change()

    def _test_api(self):
        key = self._api_input.text().strip()
        if not key:
            self._key_status.setText("API key girin")
            self._key_status.setStyleSheet(f"color: #FF3B30; font-size: 11px;")
            return

        pkey = self._get_provider_key()
        self._test_btn.setEnabled(False)
        self._test_btn.setText("...")
        self._key_status.setText("Test ediliyor...")
        self._key_status.setStyleSheet(f"color: {T.TEXT_SECONDARY}; font-size: 11px;")

        self._worker = _APITestWorker(pkey, key)
        self._worker.result.connect(self._on_test_result)
        self._worker.start()

    def _on_test_result(self, success: bool, msg: str):
        self._test_btn.setEnabled(True)
        self._test_btn.setText("Test")
        if success:
            self._key_status.setText("Bağlantı başarılı")
            self._key_status.setStyleSheet(f"color: #34C759; font-size: 11px;")
        else:
            self._key_status.setText(f"Hata: {msg}")
            self._key_status.setStyleSheet(f"color: #FF3B30; font-size: 11px;")

    def _on_change(self):
        if hasattr(self, "_fallback_combo") and hasattr(self, "_sticky_switch"):
            self._fallback_combo.setEnabled(not _switch_checked(self._sticky_switch))
        self.settings_changed.emit(self.get_settings())

    def _on_steps_change(self, value: int):
        self._steps_label.setText(str(value))
        self._on_change()

    def get_settings(self) -> dict:
        pkey = self._get_provider_key()
        sticky = _switch_checked(self._sticky_switch)
        return {
            "llm_provider": pkey,
            "llm_model": self._model_combo.currentText(),
            "api_key": self._api_input.text().strip(),
            "ollama_host": self._ollama_host_input.text().strip() or "http://localhost:11434",
            "llm_temperature": self._temp_slider.value() / 100,
            "llm_max_tokens": self._tokens_spin.value(),
            "cost_guard": _switch_checked(self._cost_guard),
            "llm_sticky_selection": sticky,
            "llm_fallback_mode": "conservative" if sticky else self._fallback_combo.currentText(),
            "autonomy_level": self._autonomy_combo.currentText(),
            "task_planning_depth": self._planning_combo.currentText(),
            "planner_max_steps": self._steps_slider.value(),
        }


# ═══════════════════════════════════════════════════════════════
# Telegram Settings Page
# ═══════════════════════════════════════════════════════════════
class _TelegramPage(QWidget):
    settings_changed = pyqtSignal(dict)

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self.config = config
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        layout.addWidget(SectionHeader("Bot Configuration"))

        card = _Card()
        cl = card._row_layout

        # Token
        self._token = _styled_input("Bot token (@BotFather)", password=True, width=280)
        self._token.setText(self.config.get("telegram_token", ""))
        self._token.textChanged.connect(self._on_change)
        cl.addWidget(_Card.row("Bot Token", self._token, "@BotFather'dan aldığınız token"))

        cl.addWidget(Divider())

        # User IDs
        self._users = _styled_input("123456789", width=200)
        users_list = self.config.get("allowed_user_ids", [])
        if isinstance(users_list, list):
            self._users.setText(", ".join(str(u) for u in users_list))
        else:
            self._users.setText(str(users_list))
        self._users.textChanged.connect(self._on_change)
        cl.addWidget(_Card.row("User IDs", self._users, "Botu kullanabilecek Telegram ID'leri"))

        cl.addWidget(Divider())

        self._photo_dir = _styled_input("Ornek: ~/Desktop/TelegramInbox/Photos", width=320)
        self._photo_dir.setText(self.config.get("photo_save_dir", "~/Desktop/TelegramInbox/Photos"))
        self._photo_dir.textChanged.connect(self._on_change)
        cl.addWidget(_Card.row("Photo Save Dir", self._photo_dir, "Telegram'dan gelen fotograflarin kayit dizini"))

        cl.addWidget(Divider())

        self._document_dir = _styled_input("Ornek: ~/Desktop/TelegramInbox/Files", width=320)
        self._document_dir.setText(self.config.get("document_save_dir", "~/Desktop/TelegramInbox/Files"))
        self._document_dir.textChanged.connect(self._on_change)
        cl.addWidget(_Card.row("Document Save Dir", self._document_dir, "Telegram'dan gelen dosyalarin kayit dizini"))

        cl.addWidget(Divider())

        # Test
        test_btn = _styled_btn("Test Connection", primary=True)
        test_btn.clicked.connect(self._test_connection)
        self._test_status = QLabel("")
        self._test_status.setStyleSheet(f"color: {T.TEXT_SECONDARY}; font-size: 11px;")

        test_w = QWidget()
        test_w.setStyleSheet("background: transparent;")
        tl = QHBoxLayout(test_w)
        tl.setContentsMargins(20, 12, 20, 12)
        tl.setSpacing(12)
        tl.addWidget(self._test_status, 1)
        tl.addWidget(test_btn)
        cl.addWidget(test_w)

        layout.addWidget(card)
        layout.addStretch()

    def _test_connection(self):
        token = self._token.text().strip()
        if not token:
            self._test_status.setText("Token girin")
            self._test_status.setStyleSheet(f"color: #FF3B30; font-size: 11px;")
            return
        try:
            import httpx
            r = httpx.get(f"https://api.telegram.org/bot{token}/getMe", timeout=5)
            if r.status_code == 200 and r.json().get("ok"):
                name = r.json()["result"].get("first_name", "Bot")
                self._test_status.setText(f"Başarılı: {name}")
                self._test_status.setStyleSheet(f"color: #34C759; font-size: 11px;")
            else:
                self._test_status.setText("Token geçersiz")
                self._test_status.setStyleSheet(f"color: #FF3B30; font-size: 11px;")
        except Exception as e:
            self._test_status.setText(f"Hata: {e}")
            self._test_status.setStyleSheet(f"color: #FF3B30; font-size: 11px;")

    def _on_change(self):
        self.settings_changed.emit(self.get_settings())

    def get_settings(self) -> dict:
        return {
            "telegram_token": self._token.text().strip(),
            "allowed_user_ids": [u.strip() for u in self._users.text().split(",") if u.strip()],
            "photo_save_dir": self._photo_dir.text().strip() or "~/Desktop/TelegramInbox/Photos",
            "document_save_dir": self._document_dir.text().strip() or "~/Desktop/TelegramInbox/Files",
        }


# ═══════════════════════════════════════════════════════════════
# General Settings Page
# ═══════════════════════════════════════════════════════════════
class _GeneralPage(QWidget):
    settings_changed = pyqtSignal(dict)

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self.config = config
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        layout.addWidget(SectionHeader("Application"))

        card = _Card()
        cl = card._row_layout

        # Notifications
        self._notif = _styled_check(self.config.get("notifications_enabled", True))
        self._notif.toggled.connect(self._on_change)
        cl.addWidget(_Card.row("Notifications", self._notif, "İşlem tamamlandığında bildirim göster"))

        cl.addWidget(Divider())

        # Tray
        self._tray = _styled_check(self.config.get("minimize_to_tray", True))
        self._tray.toggled.connect(self._on_change)
        cl.addWidget(_Card.row("Minimize to Tray", self._tray, "Kapatıldığında arka planda çalış"))

        cl.addWidget(Divider())

        # Context memory
        self._ctx = QSpinBox()
        self._ctx.setRange(0, 20)
        self._ctx.setValue(self.config.get("context_memory", 10))
        self._ctx.setFixedWidth(100)
        self._ctx.setFixedHeight(34)
        self._ctx.setStyleSheet(f"""
            QSpinBox {{
                background: {T.BG_SECONDARY};
                border: 1px solid {T.BORDER_LIGHT};
                border-radius: 8px;
                padding: 0 10px;
                font-size: 13px;
                color: {T.TEXT_PRIMARY};
            }}
        """)
        self._ctx.valueChanged.connect(self._on_change)
        cl.addWidget(_Card.row("Context Memory", self._ctx, "Hatırlanacak mesaj sayısı"))

        cl.addWidget(Divider())

        # Preferred language
        self._preferred_lang = _styled_combo(
            ["auto", "tr", "en", "es", "de", "fr", "it", "pt", "ar", "ru"], width=140
        )
        self._preferred_lang.setCurrentText(str(self.config.get("preferred_language", "auto")).lower())
        self._preferred_lang.currentTextChanged.connect(self._on_change)
        cl.addWidget(_Card.row("Preferred Language", self._preferred_lang, "Yanıt dili (auto = mesajdan algıla)"))

        cl.addWidget(Divider())

        self._enabled_langs = _styled_input("tr,en", width=180)
        enabled = self.config.get("enabled_languages", ["tr", "en"])
        if isinstance(enabled, list):
            self._enabled_langs.setText(",".join(str(x).lower() for x in enabled))
        self._enabled_langs.textChanged.connect(self._on_change)
        cl.addWidget(_Card.row("Enabled Languages", self._enabled_langs, "Virgülle ayır: tr,en,es,de..."))

        cl.addWidget(Divider())

        # Auto re-plan on execution failure
        self._auto_replan = _styled_check(self.config.get("auto_replan_enabled", True))
        self._auto_replan.toggled.connect(self._on_change)
        cl.addWidget(_Card.row("Auto Re-Plan", self._auto_replan, "Plan başarısız olursa otomatik olarak yeni plan dene"))

        cl.addWidget(Divider())

        self._replan_attempts = QSpinBox()
        self._replan_attempts.setRange(0, 3)
        self._replan_attempts.setValue(int(self.config.get("auto_replan_max_attempts", 1) or 1))
        self._replan_attempts.setFixedWidth(100)
        self._replan_attempts.setFixedHeight(34)
        self._replan_attempts.setStyleSheet(f"""
            QSpinBox {{
                background: {T.BG_SECONDARY};
                border: 1px solid {T.BORDER_LIGHT};
                border-radius: 8px;
                padding: 0 10px;
                font-size: 13px;
                color: {T.TEXT_PRIMARY};
            }}
        """)
        self._replan_attempts.valueChanged.connect(self._on_change)
        cl.addWidget(_Card.row("Re-Plan Attempts", self._replan_attempts, "0 kapatır, 1-3 yeniden plan deneme sayısı"))

        cl.addWidget(Divider())

        self._privacy_strict = _styled_check(self.config.get("privacy_mode_strict", True))
        self._privacy_strict.toggled.connect(self._on_change)
        cl.addWidget(_Card.row("Strict Privacy", self._privacy_strict, "Bulut LLM'e giderken hassas verileri maskele"))

        cl.addWidget(Divider())

        self._privacy_storage = _styled_check(self.config.get("privacy_redact_storage", True))
        self._privacy_storage.toggled.connect(self._on_change)
        cl.addWidget(_Card.row("Redact Stored Data", self._privacy_storage, "Bellek/öğrenme kayıtlarında hassas veriyi maskele"))

        layout.addWidget(card)

        # About
        layout.addWidget(SectionHeader("About"))

        about = _Card()
        al = about._row_layout
        al.setContentsMargins(20, 16, 20, 16)
        al.setSpacing(4)

        name_lbl = QLabel("Wiqo v24.0 Pro")
        name_lbl.setFont(QFont(T.FONT_DISPLAY, 15, QFont.Weight.Bold))
        name_lbl.setStyleSheet(f"color: {T.TEXT_PRIMARY}; background: transparent;")
        al.addWidget(name_lbl)

        desc_lbl = QLabel("Professional Strategic Assistant for macOS")
        desc_lbl.setFont(QFont(T.FONT_UI, 12))
        desc_lbl.setStyleSheet(f"color: {T.TEXT_SECONDARY}; background: transparent;")
        al.addWidget(desc_lbl)

        layout.addWidget(about)
        layout.addStretch()

    def _on_change(self):
        self.settings_changed.emit(self.get_settings())

    def get_settings(self) -> dict:
        enabled_languages = [x.strip().lower() for x in self._enabled_langs.text().split(",") if x.strip()]
        if not enabled_languages:
            enabled_languages = ["tr", "en"]
        return {
            "notifications_enabled": _switch_checked(self._notif),
            "minimize_to_tray": _switch_checked(self._tray),
            "context_memory": self._ctx.value(),
            "preferred_language": self._preferred_lang.currentText(),
            "enabled_languages": enabled_languages,
            "auto_replan_enabled": _switch_checked(self._auto_replan),
            "auto_replan_max_attempts": self._replan_attempts.value(),
            "privacy_mode_strict": _switch_checked(self._privacy_strict),
            "privacy_redact_storage": _switch_checked(self._privacy_storage),
        }


class _PricingPage(QWidget):
    settings_changed = pyqtSignal(dict)

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self.config = config
        self._tracker = get_pricing_tracker()
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        layout.addWidget(SectionHeader("Pricing & Usage"))

        card = _Card()
        cl = card._row_layout

        summary = self._tracker.summary().get("lifetime", {})
        requests = int(summary.get("requests", 0))
        total_tokens = int(summary.get("prompt_tokens", 0)) + int(summary.get("completion_tokens", 0))
        total_cost = float(summary.get("estimated_cost_usd", 0.0))
        monthly_budget = float(self.config.get("monthly_budget_usd", 20.0))
        usage_pct = (total_cost / monthly_budget * 100.0) if monthly_budget > 0 else 0.0

        self._summary_label = QLabel(
            f"Requests: {requests}  |  Tokens: {total_tokens}  |  Estimated Cost: ${total_cost:.4f}  |  Budget: %{usage_pct:.1f}"
        )
        self._summary_label.setStyleSheet(f"color: {T.TEXT_SECONDARY}; font-size: 12px;")
        self._summary_label.setWordWrap(True)
        wrap = QWidget()
        wl = QVBoxLayout(wrap)
        wl.setContentsMargins(20, 10, 20, 10)
        wl.addWidget(self._summary_label)
        cl.addWidget(wrap)
        cl.addWidget(Divider())

        self._monthly_budget = _styled_input("20.0", width=120)
        self._monthly_budget.setText(str(self.config.get("monthly_budget_usd", 20.0)))
        self._monthly_budget.textChanged.connect(self._on_change)
        cl.addWidget(_Card.row("Monthly Budget (USD)", self._monthly_budget, "Aylık tahmini LLM bütçesi"))

        self._budget_threshold = _styled_input("80", width=90)
        self._budget_threshold.setText(str(self.config.get("budget_alert_threshold_pct", 80)))
        self._budget_threshold.textChanged.connect(self._on_change)
        cl.addWidget(_Card.row("Alert Threshold %", self._budget_threshold, "Bütçe uyarısı için eşik"))

        self._pricing_alerts = _styled_check(bool(self.config.get("pricing_alerts_enabled", True)))
        self._pricing_alerts.toggled.connect(self._on_change)
        cl.addWidget(_Card.row("Pricing Alerts", self._pricing_alerts, "Eşik ve limit aşımlarında uyarı gönder"))

        cl.addWidget(Divider())

        current_rates = DEFAULT_PRICING_PER_1K.copy()
        configured = self.config.get("pricing_rates_per_1k", {})
        if isinstance(configured, dict):
            for p, r in configured.items():
                if isinstance(r, dict):
                    current_rates[str(p).lower()] = {
                        "input": float(r.get("input", current_rates.get(str(p).lower(), {}).get("input", 0.0))),
                        "output": float(r.get("output", current_rates.get(str(p).lower(), {}).get("output", 0.0))),
                    }

        self._rate_inputs = {}
        for provider in ["groq", "gemini", "openai", "ollama"]:
            p_row = QWidget()
            pl = QHBoxLayout(p_row)
            pl.setContentsMargins(20, 8, 20, 8)
            pl.setSpacing(8)
            name = QLabel(provider.upper())
            name.setFixedWidth(70)
            name.setStyleSheet(f"color: {T.TEXT_PRIMARY}; font-size: 12px; font-weight: 600;")
            pl.addWidget(name)
            inp = _styled_input("input /1K", width=90)
            out = _styled_input("output /1K", width=90)
            inp.setText(str(current_rates.get(provider, {}).get("input", 0.0)))
            out.setText(str(current_rates.get(provider, {}).get("output", 0.0)))
            inp.textChanged.connect(self._on_change)
            out.textChanged.connect(self._on_change)
            pl.addWidget(inp)
            pl.addWidget(out)
            pl.addStretch()
            cl.addWidget(p_row)
            self._rate_inputs[provider] = {"input": inp, "output": out}

        cl.addWidget(Divider())
        reset_btn = QPushButton("Reset Usage Stats")
        reset_btn.setFixedHeight(30)
        reset_btn.setStyleSheet(
            f"background: {T.BG_SECONDARY}; border: 1px solid {T.BORDER_LIGHT}; border-radius: 8px; color: {T.TEXT_PRIMARY};"
        )
        reset_btn.clicked.connect(self._reset_stats)
        reset_wrap = QWidget()
        rwl = QHBoxLayout(reset_wrap)
        rwl.setContentsMargins(20, 8, 20, 8)
        rwl.addWidget(reset_btn)
        rwl.addStretch()
        cl.addWidget(reset_wrap)

        layout.addWidget(card)
        layout.addStretch()

    def _reset_stats(self):
        self._tracker.reset()
        self._summary_label.setText("Requests: 0  |  Tokens: 0  |  Estimated Cost: $0.0000  |  Budget: %0.0")
        self._on_change()

    def _on_change(self):
        self.settings_changed.emit(self.get_settings())

    def get_settings(self) -> dict:
        rates = {}
        for provider, inputs in self._rate_inputs.items():
            try:
                in_rate = float(inputs["input"].text().strip() or 0.0)
            except ValueError:
                in_rate = 0.0
            try:
                out_rate = float(inputs["output"].text().strip() or 0.0)
            except ValueError:
                out_rate = 0.0
            rates[provider] = {"input": max(in_rate, 0.0), "output": max(out_rate, 0.0)}
        try:
            monthly_budget = float(self._monthly_budget.text().strip() or 20.0)
        except ValueError:
            monthly_budget = 20.0
        try:
            threshold = int(float(self._budget_threshold.text().strip() or 80))
        except ValueError:
            threshold = 80
        threshold = max(10, min(100, threshold))
        return {
            "pricing_rates_per_1k": rates,
            "monthly_budget_usd": max(monthly_budget, 0.0),
            "budget_alert_threshold_pct": threshold,
            "pricing_alerts_enabled": _switch_checked(self._pricing_alerts),
        }


# ═══════════════════════════════════════════════════════════════
# Main Settings Panel (with sidebar)
# ═══════════════════════════════════════════════════════════════
class SettingsPanelUI(QWidget):
    settings_changed = pyqtSignal(dict)

    def __init__(self, config: dict = None, parent=None):
        super().__init__(parent)
        self.config = config or {}
        self._build()

    def _build(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Sidebar
        sidebar = QFrame()
        sidebar.setFixedWidth(220)
        sidebar.setStyleSheet(f"""
            QFrame {{
                background: {T.BG_SECONDARY};
                border-right: 1px solid {T.BORDER_LIGHT};
            }}
        """)
        sb_layout = QVBoxLayout(sidebar)
        sb_layout.setContentsMargins(12, 24, 12, 24)
        sb_layout.setSpacing(4)

        # Title
        title = QLabel("Settings")
        title.setFont(QFont(T.FONT_DISPLAY, 20, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {T.TEXT_PRIMARY}; padding: 0 12px 16px 12px; background: transparent;")
        sb_layout.addWidget(title)

        # Nav items
        self._nav_btns = []
        categories = ["AI", "Telegram", "General", "Pricing"]

        for i, name in enumerate(categories):
            btn = SidebarButton("", name) # Icons removed per standard
            btn.clicked.connect(lambda checked, idx=i: self._nav_to(idx))
            sb_layout.addWidget(btn)
            self._nav_btns.append(btn)

        sb_layout.addStretch()

        # Version
        ver = QLabel("v24.0")
        ver.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ver.setStyleSheet(f"color: {T.TEXT_SECONDARY}; font-size: 11px; font-weight: 600; background: transparent;")
        sb_layout.addWidget(ver)

        layout.addWidget(sidebar)

        # Content
        self._stack = QStackedWidget()
        self._stack.setStyleSheet(f"background: {T.CARD_BG}; border-left: 1px solid {T.BORDER_LIGHT};")

        self._ai = _AIPage(self.config)
        self._ai.settings_changed.connect(self._on_change)

        self._telegram = _TelegramPage(self.config)
        self._telegram.settings_changed.connect(self._on_change)

        self._general = _GeneralPage(self.config)
        self._general.settings_changed.connect(self._on_change)

        self._pricing = _PricingPage(self.config)
        self._pricing.settings_changed.connect(self._on_change)

        for page in [self._ai, self._telegram, self._general, self._pricing]:
            scroll = QScrollArea()
            scroll.setWidget(page)
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll.setStyleSheet(f"""
                QScrollArea {{ border: none; background: {T.CARD_BG}; }}
                QScrollBar:vertical {{
                    background: transparent; width: 6px;
                }}
                QScrollBar::handle:vertical {{
                    background: {T.BORDER_LIGHT}; border-radius: 3px;
                }}
                QScrollBar::handle:vertical:hover {{
                    background: {T.NEUTRAL_BLUE};
                }}
            """)
            self._stack.addWidget(scroll)

        content = QWidget()
        cl = QVBoxLayout(content)
        cl.setContentsMargins(40, 30, 40, 30)
        cl.setSpacing(16)
        cl.addWidget(self._stack)
        layout.addWidget(content, 1)

        # Default selection
        self._nav_to(0)

    def _nav_to(self, idx: int):
        for i, btn in enumerate(self._nav_btns):
            btn.set_active(i == idx)
        
        # Add a subtle fade transition if possible, or just switch
        self._stack.setCurrentIndex(idx)

    def _on_change(self, settings: dict):
        # Merge all pages settings
        all_s = self.get_settings()
        self.settings_changed.emit(all_s)

    def get_settings(self) -> dict:
        s = {}
        s.update(self._ai.get_settings())
        s.update(self._telegram.get_settings())
        s.update(self._general.get_settings())
        s.update(self._pricing.get_settings())
        return s
