"""
Elyan Settings Panel - Apple-inspired, clean, professional
3 categories: AI, Telegram, General
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QFrame, QComboBox, QPushButton,
    QSlider, QSpinBox, QStackedWidget, QScrollArea
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread, QTimer
from PyQt6.QtGui import QFont
from typing import Any

from ui.components import (
    ElyanTheme as T, GlassFrame, AnimatedButton, SidebarButton, 
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


class _ChannelActionWorker(QThread):
    result = pyqtSignal(dict)

    def __init__(self, operation: str, payload: dict[str, Any] | None = None):
        super().__init__()
        self._operation = operation
        self._payload = payload or {}

    def run(self):
        try:
            import httpx

            if self._operation == "telegram_verify":
                token = str(self._payload.get("token") or "").strip()
                if not token:
                    raise ValueError("Telegram token bulunamadı.")
                resp = httpx.get(f"https://api.telegram.org/bot{token}/getMe", timeout=8)
                body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
                ok = resp.status_code == 200 and bool(body.get("ok"))
                self.result.emit(
                    {
                        "ok": ok,
                        "message": "Telegram token doğrulandı." if ok else f"Telegram doğrulama başarısız: HTTP {resp.status_code}",
                        "status_code": resp.status_code,
                        "data": body,
                    }
                )
                return

            if self._operation == "gateway_request":
                base_url = str(self._payload.get("base_url") or "").rstrip("/")
                path = str(self._payload.get("path") or "").strip()
                method = str(self._payload.get("method") or "post").strip().lower()
                if not base_url or not path:
                    raise ValueError("Gateway URL eksik.")
                url = f"{base_url}{path}"
                request_kwargs = {"timeout": float(self._payload.get("timeout", 12.0))}
                if self._payload.get("json") is not None:
                    request_kwargs["json"] = self._payload.get("json")
                if self._payload.get("params") is not None:
                    request_kwargs["params"] = self._payload.get("params")
                resp = getattr(httpx, method)(url, **request_kwargs)
                try:
                    body = resp.json()
                except Exception:
                    body = {"raw": resp.text}
                ok = 200 <= resp.status_code < 300
                if isinstance(body, dict):
                    ok = ok and bool(body.get("ok", True))
                message = ""
                if isinstance(body, dict):
                    message = str(body.get("message") or body.get("error") or "")
                if not message:
                    message = f"HTTP {resp.status_code}"
                self.result.emit(
                    {
                        "ok": ok,
                        "message": message,
                        "status_code": resp.status_code,
                        "data": body,
                        "url": url,
                    }
                )
                return

            if self._operation == "gateway_bulk_upsert_sync":
                base_url = str(self._payload.get("base_url") or "").rstrip("/")
                channels = self._payload.get("channels", [])
                timeout = float(self._payload.get("timeout", 12.0))
                if not base_url:
                    raise ValueError("Gateway URL eksik.")
                if not isinstance(channels, list):
                    channels = []

                upserted = 0
                failures: list[str] = []

                with httpx.Client(timeout=timeout) as client:
                    for item in channels:
                        if not isinstance(item, dict):
                            continue
                        ctype = str(item.get("type") or "").strip().lower()
                        if not ctype:
                            continue
                        try:
                            resp = client.post(
                                f"{base_url}/api/channels/upsert",
                                json={"channel": item, "sync": False},
                            )
                            body = resp.json() if "application/json" in resp.headers.get("content-type", "") else {}
                            ok = 200 <= resp.status_code < 300 and bool(body.get("ok", True))
                            if ok:
                                upserted += 1
                            else:
                                failures.append(f"{ctype}: HTTP {resp.status_code}")
                        except Exception as exc:
                            failures.append(f"{ctype}: {exc}")

                    sync_resp = client.post(f"{base_url}/api/channels/sync")
                    try:
                        sync_body = sync_resp.json()
                    except Exception:
                        sync_body = {"message": sync_resp.text}
                    sync_ok = 200 <= sync_resp.status_code < 300 and bool(sync_body.get("ok", True))
                    sync_msg = str(sync_body.get("message") or f"HTTP {sync_resp.status_code}")

                ok = sync_ok and (upserted > 0 or len(channels) == 0)
                msg = f"{upserted} kanal güncellendi. {sync_msg}"
                if failures:
                    msg = f"{msg} Hata: {'; '.join(failures[:3])}"

                self.result.emit(
                    {
                        "ok": ok,
                        "message": msg,
                        "data": {
                            "upserted": upserted,
                            "failures": failures,
                            "sync_ok": sync_ok,
                            "sync_message": sync_msg,
                        },
                        "url": base_url,
                    }
                )
                return

            raise ValueError(f"Bilinmeyen işlem: {self._operation}")
        except Exception as e:
            self.result.emit({"ok": False, "message": str(e), "error": str(e), "data": {}})


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
        pc_layout.addWidget(_Card.row("Provider", self._provider_combo, "Elyan'ın kullanacağı AI servisi"))

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

        ac_layout.addWidget(Divider())

        # Operator mode level (execution power policy)
        self._operator_mode_combo = _styled_combo(
            ["Advisory", "Assisted", "Confirmed", "Trusted", "Operator"],
            width=170
        )
        self._operator_mode_combo.setCurrentText(self.config.get("operator_mode_level", "Confirmed"))
        self._operator_mode_combo.currentTextChanged.connect(self._on_operator_mode_change)
        ac_layout.addWidget(_Card.row("Operator Mode", self._operator_mode_combo, "Sistem erişim gücü ve onay davranışı"))

        self._operator_policy_note = QLabel("")
        self._operator_policy_note.setWordWrap(True)
        self._operator_policy_note.setStyleSheet(f"color: {T.TEXT_SECONDARY}; font-size: 11px; padding: 2px 4px;")
        op_wrap = QWidget()
        op_wrap_layout = QVBoxLayout(op_wrap)
        op_wrap_layout.setContentsMargins(20, 2, 20, 6)
        op_wrap_layout.addWidget(self._operator_policy_note)
        ac_layout.addWidget(op_wrap)

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
        self._on_operator_mode_change(self._operator_mode_combo.currentText())

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

    def _operator_policy_text(self, level: str) -> str:
        lv = str(level or "Confirmed")
        mapping = {
            "Advisory": "Sadece öneri üretir. Sistem/destructive aksiyonlar engelli.",
            "Assisted": "Sistem aksiyonları açılır, destructive aksiyonlar kapalı.",
            "Confirmed": "Sistem/destructive aksiyonlar açık; riskli işlemlerde onay ister.",
            "Trusted": "Sistem/destructive açık; riskli işlemlerde minimum onay.",
            "Operator": "Maksimum operasyon gücü. Güvenlik blokları yine aktif kalır.",
        }
        return mapping.get(lv, mapping["Confirmed"])

    def _on_operator_mode_change(self, value: str):
        if hasattr(self, "_operator_policy_note"):
            self._operator_policy_note.setText(self._operator_policy_text(value))
        self._on_change()

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
            "operator_mode_level": self._operator_mode_combo.currentText(),
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

        self._tone = _styled_combo(
            ["natural_concise", "warm_operator", "mentor", "formal"], width=180
        )
        current_tone = str(self.config.get("communication_tone", "natural_concise") or "natural_concise")
        if current_tone == "professional_friendly":
            current_tone = "natural_concise"
        self._tone.setCurrentText(current_tone)
        self._tone.currentTextChanged.connect(self._on_change)
        cl.addWidget(_Card.row("Conversation Tone", self._tone, "Mesajların ne kadar kısa, sıcak veya resmi olacağını belirler"))

        cl.addWidget(Divider())

        self._response_length = _styled_combo(["short", "medium", "detailed"], width=140)
        self._response_length.setCurrentText(str(self.config.get("response_length", "short") or "short"))
        self._response_length.currentTextChanged.connect(self._on_change)
        cl.addWidget(_Card.row("Response Length", self._response_length, "Kısa mesaj mı, daha açıklayıcı yanıt mı istediğini belirler"))

        cl.addWidget(Divider())

        self._internet_reach = _styled_check(self.config.get("internet_reach_enabled", True))
        self._internet_reach.toggled.connect(self._on_change)
        cl.addWidget(_Card.row("Internet Reach", self._internet_reach, "Web, GitHub, YouTube, Reddit ve RSS kaynaklarını birleşik olarak okuyabilsin"))

        cl.addWidget(Divider())

        self._internet_platforms = _styled_input("web,github,youtube,reddit,rss", width=260)
        platforms = self.config.get("internet_reach_platforms", ["web", "github", "youtube", "reddit", "rss"])
        if isinstance(platforms, list):
            self._internet_platforms.setText(",".join(str(x).lower() for x in platforms))
        self._internet_platforms.textChanged.connect(self._on_change)
        cl.addWidget(_Card.row("Reach Platforms", self._internet_platforms, "Virgülle ayır: web,github,youtube,reddit,rss"))

        cl.addWidget(Divider())

        self._liteparse = _styled_check(self.config.get("liteparse_enabled", True))
        self._liteparse.toggled.connect(self._on_change)
        cl.addWidget(_Card.row("LiteParse Parser", self._liteparse, "Varsa LiteParse'i belge okuma için birinci parser olarak kullan"))

        cl.addWidget(Divider())

        self._repair_aggressiveness = _styled_combo(["balanced", "conservative", "aggressive"], width=160)
        self._repair_aggressiveness.setCurrentText(str(self.config.get("repair_aggressiveness", "balanced") or "balanced"))
        self._repair_aggressiveness.currentTextChanged.connect(self._on_change)
        cl.addWidget(_Card.row("Repair Policy", self._repair_aggressiveness, "UI/operator recovery denemelerinin ne kadar agresif olacağını belirler"))

        cl.addWidget(Divider())

        channel_enablement = self.config.get("mobile_channel_enablement", {"telegram": True, "imessage": True, "sms": False})
        self._mobile_telegram = _styled_check(bool(channel_enablement.get("telegram", True)))
        self._mobile_imessage = _styled_check(bool(channel_enablement.get("imessage", True)))
        self._mobile_sms = _styled_check(bool(channel_enablement.get("sms", False)))
        self._mobile_telegram.toggled.connect(self._on_change)
        self._mobile_imessage.toggled.connect(self._on_change)
        self._mobile_sms.toggled.connect(self._on_change)
        cl.addWidget(_Card.row("Mobile Telegram", self._mobile_telegram, "Telefon lane için primary channel"))
        cl.addWidget(_Card.row("Mobile iMessage", self._mobile_imessage, "macOS varsa aynı session/runtime lane'ine bağlanır"))
        cl.addWidget(_Card.row("Mobile SMS", self._mobile_sms, "Local SMS bridge varsa etkin olur, yoksa unavailable kalır"))

        cl.addWidget(Divider())

        self._conversation_privacy = _styled_combo(["balanced", "maximum"], width=160)
        self._conversation_privacy.setCurrentText(str(self.config.get("conversation_privacy_mode", "balanced") or "balanced"))
        self._conversation_privacy.currentTextChanged.connect(self._on_change)
        cl.addWidget(_Card.row("Conversation Privacy", self._conversation_privacy, "Balanced redacted öğrenmeyi açık tutar, Maximum chat learning'i kapatır"))

        cl.addWidget(Divider())

        # Auto re-plan on execution failure
        self._auto_replan = _styled_check(self.config.get("auto_replan_enabled", True))
        self._auto_replan.toggled.connect(self._on_change)
        cl.addWidget(_Card.row("Auto Re-Plan", self._auto_replan, "Plan başarısız olursa otomatik olarak yeni plan dene"))

        cl.addWidget(Divider())

        self._require_plan_confirm = _styled_check(self.config.get("require_plan_confirmation", True))
        self._require_plan_confirm.toggled.connect(self._on_change)
        cl.addWidget(_Card.row("Require Plan Confirmation", self._require_plan_confirm, "Karmaşık planlar çalışmadan önce kullanıcı onayı iste"))

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

        name_lbl = QLabel("Elyan v24.0 Pro")
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
        internet_platforms = [x.strip().lower() for x in self._internet_platforms.text().split(",") if x.strip()]
        if not internet_platforms:
            internet_platforms = ["web", "github", "youtube", "reddit", "rss"]
        return {
            "notifications_enabled": _switch_checked(self._notif),
            "minimize_to_tray": _switch_checked(self._tray),
            "context_memory": self._ctx.value(),
            "preferred_language": self._preferred_lang.currentText(),
            "enabled_languages": enabled_languages,
            "communication_tone": self._tone.currentText(),
            "assistant_style": self._tone.currentText(),
            "response_length": self._response_length.currentText(),
            "internet_reach_enabled": _switch_checked(self._internet_reach),
            "internet_reach_platforms": internet_platforms,
            "liteparse_enabled": _switch_checked(self._liteparse),
            "repair_aggressiveness": self._repair_aggressiveness.currentText(),
            "mobile_channel_enablement": {
                "telegram": _switch_checked(self._mobile_telegram),
                "imessage": _switch_checked(self._mobile_imessage),
                "sms": _switch_checked(self._mobile_sms),
            },
            "conversation_privacy_mode": self._conversation_privacy.currentText(),
            "auto_replan_enabled": _switch_checked(self._auto_replan),
            "require_plan_confirmation": _switch_checked(self._require_plan_confirm),
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
# Channels Settings Page
# ═══════════════════════════════════════════════════════════════
class _ChannelsPage(QWidget):
    settings_changed = pyqtSignal(dict)

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self.config = config
        self._workers: list[QThread] = []
        self._last_auth_url = ""
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        layout.addWidget(SectionHeader("Channel Control Center"))

        desc = QLabel("Kanalları tek ekranda kurun, doğrulayın ve runtime'a uygulayın.")
        desc.setFont(QFont(T.FONT_UI, 12))
        desc.setStyleSheet(f"color: {T.TEXT_SECONDARY}; padding: 0 4px;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        channels_data = self.config.get("channels", {})
        if not isinstance(channels_data, dict):
            channels_data = {}

        self._runtime_card = _Card()
        rc = self._runtime_card._row_layout
        self._runtime_status = QLabel("Hazır")
        self._runtime_status.setWordWrap(True)
        self._runtime_status.setStyleSheet(f"color: {T.TEXT_SECONDARY}; font-size: 11px;")
        self._channel_scope = _styled_combo(["all", "telegram", "discord", "slack", "whatsapp", "webchat"], width=180)
        self._sync_btn = _styled_btn("Sync Channels", primary=True)
        self._test_btn = _styled_btn("Test Channels", primary=False)
        self._sync_btn.clicked.connect(self._sync_channels)
        self._test_btn.clicked.connect(self._test_channels)
        runtime_row = QWidget()
        runtime_row.setStyleSheet("background: transparent;")
        rhl = QHBoxLayout(runtime_row)
        rhl.setContentsMargins(20, 12, 20, 12)
        rhl.setSpacing(10)
        rhl.addWidget(self._runtime_status, 1)
        rhl.addWidget(self._channel_scope)
        rhl.addWidget(self._sync_btn)
        rhl.addWidget(self._test_btn)
        rc.addWidget(runtime_row)

        rc.addWidget(Divider())
        self._gw_port = QSpinBox()
        self._gw_port.setRange(1024, 65535)
        self._gw_port.setValue(int(self.config.get("gateway_port", 18789)))
        self._gw_port.setFixedWidth(110)
        self._gw_port.setFixedHeight(34)
        self._gw_port.setStyleSheet(f"""
            QSpinBox {{
                background: {T.BG_SECONDARY};
                border: 1px solid {T.BORDER_LIGHT};
                border-radius: 8px;
                padding: 0 10px;
                font-size: 13px;
                color: {T.TEXT_PRIMARY};
            }}
        """)
        self._gw_port.valueChanged.connect(self._on_change)
        rc.addWidget(_Card.row("Gateway Port", self._gw_port, "Local API ve kanal runtime portu"))

        rc.addWidget(Divider())
        self._webhook_auth = _styled_input("Bearer token", password=True, width=220)
        self._webhook_auth.setText(str(self.config.get("webhook_auth_token", "") or ""))
        self._webhook_auth.textChanged.connect(self._on_change)
        rc.addWidget(_Card.row("Webhook Token", self._webhook_auth, "Harici webhook doğrulaması için"))
        layout.addWidget(self._runtime_card)

        layout.addWidget(SectionHeader("Telegram"))
        telegram_card = _Card()
        tc = telegram_card._row_layout
        self._telegram_note = QLabel("Token, Telegram ayarlarından okunur. Buradan sadece doğrulama yapılır.")
        self._telegram_note.setWordWrap(True)
        self._telegram_note.setStyleSheet(f"color: {T.TEXT_SECONDARY}; font-size: 11px;")
        self._telegram_status = QLabel("Doğrulama bekliyor")
        self._telegram_status.setStyleSheet(f"color: {T.TEXT_SECONDARY}; font-size: 11px;")
        self._telegram_verify_btn = _styled_btn("Verify Telegram Token", primary=True)
        self._telegram_verify_btn.clicked.connect(self._verify_telegram_token)
        telegram_row = QWidget()
        telegram_row.setStyleSheet("background: transparent;")
        trl = QHBoxLayout(telegram_row)
        trl.setContentsMargins(20, 12, 20, 12)
        trl.setSpacing(10)
        trl.addWidget(self._telegram_note, 1)
        trl.addWidget(self._telegram_status)
        trl.addWidget(self._telegram_verify_btn)
        tc.addWidget(telegram_row)
        layout.addWidget(telegram_card)

        layout.addWidget(SectionHeader("WhatsApp"))
        wa_card = _Card()
        wc = wa_card._row_layout
        wa = channels_data.get("whatsapp", {}) if isinstance(channels_data, dict) else {}
        self._wa_enabled = _styled_check(wa.get("enabled", False))
        self._wa_enabled.toggled.connect(self._on_change)
        wc.addWidget(_Card.row("Etkin", self._wa_enabled, "WhatsApp kanalını aktif eder"))
        wc.addWidget(Divider())
        self._wa_mode = _styled_combo(["bridge", "cloud"], width=140)
        self._wa_mode.setCurrentText(str(wa.get("mode", "bridge") or "bridge").strip().lower())
        self._wa_mode.currentTextChanged.connect(self._on_whatsapp_mode_changed)
        wc.addWidget(_Card.row("Mode", self._wa_mode, "Bridge QR akışı veya Cloud API webhook"))
        wc.addWidget(Divider())
        self._wa_phone = _styled_input("+90...", width=220)
        self._wa_phone.setText(str(wa.get("phone_number", "") or ""))
        self._wa_phone.textChanged.connect(self._on_change)
        wc.addWidget(_Card.row("Phone Number", self._wa_phone, "Eski yapı ile uyum için korunur"))
        wc.addWidget(Divider())
        self._wa_bridge_url = _styled_input("http://127.0.0.1:18792", width=260)
        self._wa_bridge_url.setText(str(wa.get("bridge_url", "") or ""))
        self._wa_bridge_url.textChanged.connect(self._on_change)
        self._wa_bridge_token = _styled_input("Bridge token", password=True, width=220)
        self._wa_bridge_token.setText(str(wa.get("bridge_token", "") or ""))
        self._wa_bridge_token.textChanged.connect(self._on_change)
        wc.addWidget(_Card.row("Bridge URL", self._wa_bridge_url, "Bridge modunda yerel eşleştirme adresi"))
        wc.addWidget(_Card.row("Bridge Token", self._wa_bridge_token, "Bridge modunda güvenlik anahtarı"))
        wc.addWidget(Divider())
        self._wa_phone_number_id = _styled_input("Phone number ID", width=220)
        self._wa_phone_number_id.setText(str(wa.get("phone_number_id", "") or ""))
        self._wa_phone_number_id.textChanged.connect(self._on_change)
        self._wa_access_token = _styled_input("Access token", password=True, width=240)
        self._wa_access_token.setText(str(wa.get("access_token", "") or ""))
        self._wa_access_token.textChanged.connect(self._on_change)
        self._wa_verify_token = _styled_input("Verify token", password=True, width=220)
        self._wa_verify_token.setText(str(wa.get("verify_token", "") or ""))
        self._wa_verify_token.textChanged.connect(self._on_change)
        self._wa_webhook_path = _styled_input("/whatsapp/webhook", width=220)
        self._wa_webhook_path.setText(str(wa.get("webhook_path", "") or ""))
        self._wa_webhook_path.textChanged.connect(self._on_change)
        wc.addWidget(_Card.row("Phone Number ID", self._wa_phone_number_id, "WhatsApp Cloud API phone number id"))
        wc.addWidget(_Card.row("Access Token", self._wa_access_token, "Meta / WhatsApp Cloud API token"))
        wc.addWidget(_Card.row("Verify Token", self._wa_verify_token, "Webhook verification token"))
        wc.addWidget(_Card.row("Webhook Path", self._wa_webhook_path, "Gateway webhook path"))
        wc.addWidget(Divider())
        self._wa_hint = QLabel("Bridge mode: local QR pairing ve yerel bridge URL kullanılır.")
        self._wa_hint.setStyleSheet(f"color: {T.TEXT_SECONDARY}; font-size: 11px; padding: 0 4px;")
        wc.addWidget(self._wa_hint)
        layout.addWidget(wa_card)

        layout.addWidget(SectionHeader("Slack / Discord"))
        sd_card = _Card()
        sc = sd_card._row_layout
        discord = channels_data.get("discord", {}) if isinstance(channels_data, dict) else {}
        slack = channels_data.get("slack", {}) if isinstance(channels_data, dict) else {}
        self._discord_enabled = _styled_check(discord.get("enabled", False))
        self._discord_enabled.toggled.connect(self._on_change)
        sc.addWidget(_Card.row("Discord Etkin", self._discord_enabled, "Discord bot kanalını açar"))
        self._discord_token = _styled_input("Discord bot token", password=True, width=280)
        self._discord_token.setText(str(discord.get("token", "") or ""))
        self._discord_token.textChanged.connect(self._on_change)
        sc.addWidget(_Card.row("Discord Token", self._discord_token, "Discord Developer Portal token"))
        sc.addWidget(Divider())
        self._slack_enabled = _styled_check(slack.get("enabled", False))
        self._slack_enabled.toggled.connect(self._on_change)
        sc.addWidget(_Card.row("Slack Etkin", self._slack_enabled, "Slack workspace kanalını açar"))
        self._slack_token = _styled_input("Slack bot token", password=True, width=280)
        self._slack_token.setText(str(slack.get("bot_token", "") or ""))
        self._slack_token.textChanged.connect(self._on_change)
        self._slack_signing = _styled_input("Signing secret", password=True, width=260)
        self._slack_signing.setText(str(slack.get("signing_secret", "") or ""))
        self._slack_signing.textChanged.connect(self._on_change)
        sc.addWidget(_Card.row("Slack Bot Token", self._slack_token, "Slack App bot token"))
        sc.addWidget(_Card.row("Signing Secret", self._slack_signing, "Request doğrulama anahtarı"))
        sc.addWidget(Divider())
        self._oauth_provider = _styled_combo(["slack", "google", "discord"], width=150)
        self._oauth_status = QLabel("OAuth connect bekliyor")
        self._oauth_status.setWordWrap(True)
        self._oauth_status.setStyleSheet(f"color: {T.TEXT_SECONDARY}; font-size: 11px;")
        self._oauth_connect_btn = _styled_btn("Run OAuth Connect", primary=True)
        self._oauth_connect_btn.clicked.connect(self._run_oauth_connect)
        self._oauth_open_btn = _styled_btn("Open Auth URL", primary=False)
        self._oauth_open_btn.setEnabled(False)
        self._oauth_open_btn.clicked.connect(self._open_auth_url)
        oauth_row = QWidget()
        oauth_row.setStyleSheet("background: transparent;")
        ohl = QHBoxLayout(oauth_row)
        ohl.setContentsMargins(20, 12, 20, 12)
        ohl.setSpacing(10)
        ohl.addWidget(self._oauth_status, 1)
        ohl.addWidget(self._oauth_provider)
        ohl.addWidget(self._oauth_connect_btn)
        ohl.addWidget(self._oauth_open_btn)
        sc.addWidget(oauth_row)
        layout.addWidget(sd_card)

        layout.addWidget(SectionHeader("WebChat"))
        web_card = _Card()
        xc = web_card._row_layout
        self._webchat_enabled = _styled_check(channels_data.get("webchat", {}).get("enabled", True))
        self._webchat_enabled.toggled.connect(self._on_change)
        xc.addWidget(_Card.row("Etkin", self._webchat_enabled, "Tarayıcı tabanlı sohbet arayüzü"))
        layout.addWidget(web_card)

        layout.addStretch()
        self._sync_whatsapp_mode_ui(self._wa_mode.currentText())
        self._set_runtime_status("Hazır")

    def _on_change(self):
        self.settings_changed.emit(self.get_settings())

    def _gateway_base_url(self) -> str:
        port = self._gw_port.value() if hasattr(self, "_gw_port") else self.config.get("gateway_port", 18789)
        try:
            port = int(port)
        except Exception:
            port = 18789
        port = max(1024, min(65535, port))
        return f"http://127.0.0.1:{port}"

    def _set_runtime_status(self, text: str, ok: bool | None = None):
        self._runtime_status.setText(text)
        if ok is True:
            self._runtime_status.setStyleSheet("color: #34C759; font-size: 11px;")
        elif ok is False:
            self._runtime_status.setStyleSheet("color: #FF3B30; font-size: 11px;")
        else:
            self._runtime_status.setStyleSheet(f"color: {T.TEXT_SECONDARY}; font-size: 11px;")

    def _set_telegram_status(self, text: str, ok: bool | None = None):
        self._telegram_status.setText(text)
        if ok is True:
            self._telegram_status.setStyleSheet("color: #34C759; font-size: 11px;")
        elif ok is False:
            self._telegram_status.setStyleSheet("color: #FF3B30; font-size: 11px;")
        else:
            self._telegram_status.setStyleSheet(f"color: {T.TEXT_SECONDARY}; font-size: 11px;")

    def _set_oauth_status(self, text: str, ok: bool | None = None):
        self._oauth_status.setText(text)
        if ok is True:
            self._oauth_status.setStyleSheet("color: #34C759; font-size: 11px;")
        elif ok is False:
            self._oauth_status.setStyleSheet("color: #FF3B30; font-size: 11px;")
        else:
            self._oauth_status.setStyleSheet(f"color: {T.TEXT_SECONDARY}; font-size: 11px;")

    def _set_busy(self, busy: bool):
        for widget in [self._sync_btn, self._test_btn, self._telegram_verify_btn, self._oauth_connect_btn]:
            widget.setEnabled(not busy)
        self._oauth_open_btn.setEnabled(bool(self._last_auth_url) and not busy)

    def _track_worker(self, worker: QThread, callback):
        self._workers.append(worker)

        def _cleanup():
            if worker in self._workers:
                self._workers.remove(worker)

        worker.finished.connect(_cleanup)
        worker.result.connect(callback)
        worker.start()

    def _verify_telegram_token(self):
        try:
            from config.settings_manager import SettingsPanel

            token = str(SettingsPanel().get("telegram_token", "") or "").strip()
        except Exception:
            token = ""
        if not token:
            self._set_telegram_status("Telegram token bulunamadı.", False)
            return
        self._set_telegram_status("Telegram token doğrulanıyor...")
        self._set_busy(True)
        worker = _ChannelActionWorker("telegram_verify", {"token": token})
        self._track_worker(worker, self._handle_telegram_verify_result)

    def _handle_telegram_verify_result(self, payload: dict):
        self._set_busy(False)
        self._set_telegram_status(str(payload.get("message") or "Telegram doğrulama tamamlandı."), bool(payload.get("ok")))

    def _sync_channels(self):
        self._set_runtime_status("Kanal konfigürasyonu runtime'a uygulanıyor...")
        self._set_busy(True)
        channels = self._collect_runtime_channels()
        worker = _ChannelActionWorker(
            "gateway_bulk_upsert_sync",
            {"base_url": self._gateway_base_url(), "channels": channels},
        )
        self._track_worker(worker, self._handle_sync_result)

    def _test_channels(self):
        target = self._channel_scope.currentText().strip().lower() or "all"
        self._set_runtime_status(f"Kanallar test ediliyor: {target}...")
        self._set_busy(True)
        worker = _ChannelActionWorker(
            "gateway_request",
            {
                "base_url": self._gateway_base_url(),
                "path": "/api/channels/test",
                "method": "post",
                "json": {"channel": target},
            },
        )
        self._track_worker(worker, self._handle_test_result)

    def _handle_sync_result(self, payload: dict):
        self._set_busy(False)
        self._set_runtime_status(str(payload.get("message") or "Sync tamamlandı."), bool(payload.get("ok")))

    def _collect_runtime_channels(self) -> list[dict]:
        channels: list[dict] = []

        try:
            from config.settings_manager import SettingsPanel

            telegram_token = str(SettingsPanel().get("telegram_token", "") or "").strip()
        except Exception:
            telegram_token = ""
        if telegram_token:
            channels.append(
                {
                    "type": "telegram",
                    "id": "telegram",
                    "enabled": True,
                    "token": telegram_token,
                }
            )

        discord_token = self._discord_token.text().strip()
        if _switch_checked(self._discord_enabled) or discord_token:
            channels.append(
                {
                    "type": "discord",
                    "id": "discord",
                    "enabled": _switch_checked(self._discord_enabled),
                    "token": discord_token,
                }
            )

        slack_bot = self._slack_token.text().strip()
        slack_signing = self._slack_signing.text().strip()
        if _switch_checked(self._slack_enabled) or slack_bot or slack_signing:
            channels.append(
                {
                    "type": "slack",
                    "id": "slack",
                    "enabled": _switch_checked(self._slack_enabled),
                    "bot_token": slack_bot,
                    "signing_secret": slack_signing,
                }
            )

        channels.append(
            {
                "type": "whatsapp",
                "id": "whatsapp",
                "enabled": _switch_checked(self._wa_enabled),
                "mode": self._wa_mode.currentText().strip().lower() or "bridge",
                "phone_number": self._wa_phone.text().strip(),
                "bridge_url": self._wa_bridge_url.text().strip(),
                "bridge_token": self._wa_bridge_token.text().strip(),
                "phone_number_id": self._wa_phone_number_id.text().strip(),
                "access_token": self._wa_access_token.text().strip(),
                "verify_token": self._wa_verify_token.text().strip(),
                "webhook_path": self._wa_webhook_path.text().strip(),
            }
        )

        channels.append(
            {
                "type": "webchat",
                "id": "webchat",
                "enabled": _switch_checked(self._webchat_enabled),
            }
        )
        return channels

    def _handle_test_result(self, payload: dict):
        self._set_busy(False)
        data = payload.get("data") or {}
        if isinstance(data, dict):
            auth_url = str(data.get("auth_url") or data.get("launch_url") or "").strip()
            if auth_url:
                self._last_auth_url = auth_url
        self._oauth_open_btn.setEnabled(bool(self._last_auth_url))
        self._set_runtime_status(str(payload.get("message") or "Test tamamlandı."), bool(payload.get("ok")))

    def _run_oauth_connect(self):
        provider = self._oauth_provider.currentText().strip().lower()
        self._set_oauth_status(f"{provider} OAuth başlatılıyor...")
        self._set_busy(True)
        worker = _ChannelActionWorker(
            "gateway_request",
            {
                "base_url": self._gateway_base_url(),
                "path": "/api/integrations/connect",
                "method": "post",
                "json": {"provider": provider, "app_name": provider, "mode": "auto"},
            },
        )
        self._track_worker(worker, self._handle_oauth_result)

    def _handle_oauth_result(self, payload: dict):
        self._set_busy(False)
        data = payload.get("data") or {}
        auth_url = ""
        if isinstance(data, dict):
            auth_url = str(data.get("auth_url") or data.get("launch_url") or "").strip()
        self._last_auth_url = auth_url
        self._oauth_open_btn.setEnabled(bool(self._last_auth_url))
        text = str(payload.get("message") or "OAuth akışı tamamlandı.")
        if self._last_auth_url:
            text = f"{text} Auth URL hazır."
        self._set_oauth_status(text, bool(payload.get("ok")))

    def _open_auth_url(self):
        if not self._last_auth_url:
            return
        try:
            import webbrowser

            webbrowser.open(self._last_auth_url)
            self._set_oauth_status("Auth URL tarayıcıda açıldı.", True)
        except Exception as exc:
            self._set_oauth_status(f"Auth URL açılamadı: {exc}", False)

    def _on_whatsapp_mode_changed(self, value: str):
        self._sync_whatsapp_mode_ui(value)
        self._on_change()

    def _sync_whatsapp_mode_ui(self, value: str):
        bridge_mode = str(value or "bridge").strip().lower() == "bridge"
        for widget in [self._wa_bridge_url, self._wa_bridge_token]:
            widget.setEnabled(bridge_mode)
        for widget in [self._wa_phone_number_id, self._wa_access_token, self._wa_verify_token, self._wa_webhook_path]:
            widget.setEnabled(not bridge_mode)
        self._wa_hint.setText(
            "Bridge mode: local QR pairing ve yerel bridge URL kullanılır."
            if bridge_mode
            else "Cloud mode: Meta Cloud API, webhook ve access token kullanılır."
        )

    def get_settings(self) -> dict:
        return {
            "channels": {
                "discord": {
                    "enabled": _switch_checked(self._discord_enabled),
                    "token": self._discord_token.text().strip(),
                },
                "slack": {
                    "enabled": _switch_checked(self._slack_enabled),
                    "bot_token": self._slack_token.text().strip(),
                    "signing_secret": self._slack_signing.text().strip(),
                },
                "whatsapp": {
                    "enabled": _switch_checked(self._wa_enabled),
                    "mode": self._wa_mode.currentText().strip().lower() or "bridge",
                    "phone_number": self._wa_phone.text().strip(),
                    "bridge_url": self._wa_bridge_url.text().strip(),
                    "bridge_token": self._wa_bridge_token.text().strip(),
                    "phone_number_id": self._wa_phone_number_id.text().strip(),
                    "access_token": self._wa_access_token.text().strip(),
                    "verify_token": self._wa_verify_token.text().strip(),
                    "webhook_path": self._wa_webhook_path.text().strip(),
                },
                "webchat": {
                    "enabled": _switch_checked(self._webchat_enabled),
                },
            },
            "gateway_port": self._gw_port.value(),
            "webhook_auth_token": self._webhook_auth.text().strip(),
        }


# ═══════════════════════════════════════════════════════════════
# Cron & Scheduler Settings Page
# ═══════════════════════════════════════════════════════════════
class _CronPage(QWidget):
    settings_changed = pyqtSignal(dict)

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self.config = config
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        layout.addWidget(SectionHeader("Zamanlanmış Görevler"))

        desc = QLabel("Cron ifadeleri ile otomatik görevler tanımlayın")
        desc.setFont(QFont(T.FONT_UI, 12))
        desc.setStyleSheet(f"color: {T.TEXT_SECONDARY}; padding: 0 4px;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # Add new job
        layout.addWidget(SectionHeader("Yeni Görev Ekle"))
        add_card = _Card()
        ac = add_card._row_layout

        self._cron_expr = _styled_input("0 6 * * *  (her gün 06:00)", width=200)
        ac.addWidget(_Card.row("Cron İfadesi", self._cron_expr, "Standart cron formatı: dakika saat gün ay haftagünü"))

        ac.addWidget(Divider())

        self._cron_prompt = _styled_input("Sabah brifingini hazırla", width=320)
        ac.addWidget(_Card.row("Görev Prompt", self._cron_prompt, "Agent'a gönderilecek komut"))

        ac.addWidget(Divider())

        self._cron_channel = _styled_combo(["telegram", "discord", "slack", "webchat"], width=160)
        ac.addWidget(_Card.row("Hedef Kanal", self._cron_channel, "Sonucun gönderileceği kanal"))

        ac.addWidget(Divider())

        add_btn = _styled_btn("Görev Ekle", primary=True)
        add_btn.clicked.connect(self._add_job)
        add_wrap = QWidget()
        add_wrap.setStyleSheet("background: transparent;")
        awl = QHBoxLayout(add_wrap)
        awl.setContentsMargins(20, 8, 20, 8)
        awl.addStretch()
        awl.addWidget(add_btn)
        ac.addWidget(add_wrap)

        layout.addWidget(add_card)

        # Existing jobs
        layout.addWidget(SectionHeader("Mevcut Görevler"))

        self._jobs_card = _Card()
        self._jobs_layout = self._jobs_card._row_layout
        self._refresh_jobs_list()

        layout.addWidget(self._jobs_card)

        # Heartbeat
        layout.addWidget(SectionHeader("Heartbeat"))
        hb_card = _Card()
        hc = hb_card._row_layout

        self._hb_enabled = _styled_check(self.config.get("heartbeat_enabled", False))
        self._hb_enabled.toggled.connect(self._on_change)
        hc.addWidget(_Card.row("Heartbeat Etkin", self._hb_enabled, "Periyodik sistem uyanma mekanizması"))

        hc.addWidget(Divider())

        self._hb_interval = QSpinBox()
        self._hb_interval.setRange(5, 1440)
        self._hb_interval.setValue(int(self.config.get("heartbeat_interval_minutes", 360)))
        self._hb_interval.setFixedWidth(100)
        self._hb_interval.setFixedHeight(34)
        self._hb_interval.setStyleSheet(f"""
            QSpinBox {{
                background: {T.BG_SECONDARY};
                border: 1px solid {T.BORDER_LIGHT};
                border-radius: 8px;
                padding: 0 10px;
                font-size: 13px;
                color: {T.TEXT_PRIMARY};
            }}
        """)
        self._hb_interval.valueChanged.connect(self._on_change)
        hc.addWidget(_Card.row("Aralık (dakika)", self._hb_interval, "Uyanma sıklığı"))

        layout.addWidget(hb_card)
        layout.addStretch()

    def _add_job(self):
        expr = self._cron_expr.text().strip()
        prompt = self._cron_prompt.text().strip()
        channel = self._cron_channel.currentText()
        if not expr or not prompt:
            return

        cron_jobs = self.config.get("cron_jobs", [])
        cron_jobs.append({
            "expression": expr,
            "prompt": prompt,
            "channel": channel,
            "enabled": True,
        })
        self.config["cron_jobs"] = cron_jobs
        self._cron_expr.clear()
        self._cron_prompt.clear()
        self._refresh_jobs_list()
        self._on_change()

    def _remove_job(self, index: int):
        cron_jobs = self.config.get("cron_jobs", [])
        if 0 <= index < len(cron_jobs):
            cron_jobs.pop(index)
            self.config["cron_jobs"] = cron_jobs
            self._refresh_jobs_list()
            self._on_change()

    def _refresh_jobs_list(self):
        while self._jobs_layout.count():
            item = self._jobs_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        cron_jobs = self.config.get("cron_jobs", [])
        if not cron_jobs:
            empty = QLabel("Henüz zamanlanmış görev yok")
            empty.setStyleSheet(f"color: {T.TEXT_SECONDARY}; font-size: 12px; padding: 16px;")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._jobs_layout.addWidget(empty)
            return

        for i, job in enumerate(cron_jobs):
            row = QWidget()
            row.setStyleSheet("background: transparent;")
            rl = QHBoxLayout(row)
            rl.setContentsMargins(20, 8, 20, 8)
            rl.setSpacing(12)

            expr_lbl = QLabel(job.get("expression", ""))
            expr_lbl.setFont(QFont(T.FONT_MONO, 12))
            expr_lbl.setStyleSheet(f"color: {T.ACCENT_BLUE}; background: transparent;")
            expr_lbl.setFixedWidth(120)
            rl.addWidget(expr_lbl)

            prompt_lbl = QLabel(job.get("prompt", "")[:50])
            prompt_lbl.setStyleSheet(f"color: {T.TEXT_PRIMARY}; font-size: 12px; background: transparent;")
            rl.addWidget(prompt_lbl, 1)

            ch_lbl = QLabel(job.get("channel", "telegram"))
            ch_lbl.setStyleSheet(f"color: {T.TEXT_SECONDARY}; font-size: 11px; background: transparent;")
            rl.addWidget(ch_lbl)

            del_btn = QPushButton("Sil")
            del_btn.setFixedSize(50, 28)
            del_btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    color: #FF3B30;
                    border: 1px solid #FF3B30;
                    border-radius: 6px;
                    font-size: 11px;
                }}
                QPushButton:hover {{ background: #FF3B3010; }}
            """)
            del_btn.clicked.connect(lambda _, idx=i: self._remove_job(idx))
            rl.addWidget(del_btn)

            self._jobs_layout.addWidget(row)
            if i < len(cron_jobs) - 1:
                self._jobs_layout.addWidget(Divider())

    def _on_change(self):
        self.settings_changed.emit(self.get_settings())

    def get_settings(self) -> dict:
        return {
            "cron_jobs": self.config.get("cron_jobs", []),
            "heartbeat_enabled": _switch_checked(self._hb_enabled),
            "heartbeat_interval_minutes": self._hb_interval.value(),
        }


# ═══════════════════════════════════════════════════════════════
# Security Settings Page
# ═══════════════════════════════════════════════════════════════
class _SecurityPage(QWidget):
    settings_changed = pyqtSignal(dict)

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self.config = config
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        layout.addWidget(SectionHeader("Güvenlik & İzolasyon"))

        # Tool Policy
        layout.addWidget(SectionHeader("Tool Politikası"))
        policy_card = _Card()
        pc = policy_card._row_layout

        self._sandbox_enabled = _styled_check(self.config.get("sandbox_enabled", False))
        self._sandbox_enabled.toggled.connect(self._on_change)
        pc.addWidget(_Card.row("Docker Sandbox", self._sandbox_enabled, "Komut çalıştırmayı Docker container'da izole et"))

        pc.addWidget(Divider())

        self._tool_approval = _styled_check(self.config.get("tool_approval_required", True))
        self._tool_approval.toggled.connect(self._on_change)
        pc.addWidget(_Card.row("Tool Onayı", self._tool_approval, "Riskli araç kullanımında kullanıcı onayı iste"))

        pc.addWidget(Divider())

        self._destructive_block = _styled_check(self.config.get("block_destructive", True))
        self._destructive_block.toggled.connect(self._on_change)
        pc.addWidget(_Card.row("Yıkıcı İşlem Engeli", self._destructive_block, "rm -rf, format gibi tehlikeli komutları engelle"))

        layout.addWidget(policy_card)

        # Rate Limiting
        layout.addWidget(SectionHeader("Hız Limitleri"))
        rate_card = _Card()
        rc = rate_card._row_layout

        self._rate_limit = QSpinBox()
        self._rate_limit.setRange(1, 100)
        self._rate_limit.setValue(int(self.config.get("rate_limit_per_minute", 30)))
        self._rate_limit.setFixedWidth(100)
        self._rate_limit.setFixedHeight(34)
        self._rate_limit.setStyleSheet(f"""
            QSpinBox {{
                background: {T.BG_SECONDARY};
                border: 1px solid {T.BORDER_LIGHT};
                border-radius: 8px;
                padding: 0 10px;
                font-size: 13px;
                color: {T.TEXT_PRIMARY};
            }}
        """)
        self._rate_limit.valueChanged.connect(self._on_change)
        rc.addWidget(_Card.row("İstek/Dakika", self._rate_limit, "Dakikadaki maksimum istek sayısı"))

        rc.addWidget(Divider())

        self._daily_token_limit = QSpinBox()
        self._daily_token_limit.setRange(0, 1000000)
        self._daily_token_limit.setSingleStep(10000)
        self._daily_token_limit.setValue(int(self.config.get("daily_token_limit", 100000)))
        self._daily_token_limit.setFixedWidth(140)
        self._daily_token_limit.setFixedHeight(34)
        self._daily_token_limit.setStyleSheet(f"""
            QSpinBox {{
                background: {T.BG_SECONDARY};
                border: 1px solid {T.BORDER_LIGHT};
                border-radius: 8px;
                padding: 0 10px;
                font-size: 13px;
                color: {T.TEXT_PRIMARY};
            }}
        """)
        self._daily_token_limit.valueChanged.connect(self._on_change)
        rc.addWidget(_Card.row("Günlük Token Limiti", self._daily_token_limit, "0 = sınırsız"))

        layout.addWidget(rate_card)

        # Audit
        layout.addWidget(SectionHeader("Denetim"))
        audit_card = _Card()
        auc = audit_card._row_layout

        self._audit_enabled = _styled_check(self.config.get("audit_logging", True))
        self._audit_enabled.toggled.connect(self._on_change)
        auc.addWidget(_Card.row("Audit Logging", self._audit_enabled, "Tüm agent işlemlerini kaydet"))

        auc.addWidget(Divider())

        self._audit_retention = QSpinBox()
        self._audit_retention.setRange(1, 365)
        self._audit_retention.setValue(int(self.config.get("audit_retention_days", 30)))
        self._audit_retention.setFixedWidth(100)
        self._audit_retention.setFixedHeight(34)
        self._audit_retention.setStyleSheet(f"""
            QSpinBox {{
                background: {T.BG_SECONDARY};
                border: 1px solid {T.BORDER_LIGHT};
                border-radius: 8px;
                padding: 0 10px;
                font-size: 13px;
                color: {T.TEXT_PRIMARY};
            }}
        """)
        self._audit_retention.valueChanged.connect(self._on_change)
        auc.addWidget(_Card.row("Log Saklama (gün)", self._audit_retention, "Eski loglar otomatik temizlenir"))

        layout.addWidget(audit_card)

        # Keychain
        layout.addWidget(SectionHeader("Keychain"))
        kc_card = _Card()
        kcc = kc_card._row_layout

        self._keychain_enabled = _styled_check(self.config.get("keychain_enabled", False))
        self._keychain_enabled.toggled.connect(self._on_change)
        kcc.addWidget(_Card.row("macOS Keychain", self._keychain_enabled, "API anahtarlarını Keychain'de sakla (.env yerine)"))

        layout.addWidget(kc_card)
        layout.addStretch()

    def _on_change(self):
        self.settings_changed.emit(self.get_settings())

    def get_settings(self) -> dict:
        return {
            "sandbox_enabled": _switch_checked(self._sandbox_enabled),
            "tool_approval_required": _switch_checked(self._tool_approval),
            "block_destructive": _switch_checked(self._destructive_block),
            "rate_limit_per_minute": self._rate_limit.value(),
            "daily_token_limit": self._daily_token_limit.value(),
            "audit_logging": _switch_checked(self._audit_enabled),
            "audit_retention_days": self._audit_retention.value(),
            "keychain_enabled": _switch_checked(self._keychain_enabled),
        }


# ═══════════════════════════════════════════════════════════════
# Operator Intelligence Settings Page
# ═══════════════════════════════════════════════════════════════
class _OperatorIntelligencePage(QWidget):
    settings_changed = pyqtSignal(dict)
    user_data_delete_requested = pyqtSignal()

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self.config = config
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        layout.addWidget(SectionHeader("Operator Intelligence"))

        intro = QLabel("Consensus, öğrenme politikası ve canlı çalışma metrikleri.")
        intro.setFont(QFont(T.FONT_UI, 12))
        intro.setStyleSheet(f"color: {T.TEXT_SECONDARY}; padding: 0 4px;")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        # Consensus
        layout.addWidget(SectionHeader("Consensus"))
        consensus_card = _Card()
        cc = consensus_card._row_layout

        self._consensus_enabled = _styled_check(bool(self.config.get("consensus_enabled", True)))
        self._consensus_enabled.toggled.connect(self._on_change)
        cc.addWidget(_Card.row("Consensus", self._consensus_enabled, "Kritik görevlerde çok ajanlı karar mekanizması"))

        cc.addWidget(Divider())

        self._veto_policy = _styled_combo(["require_approval", "block"], width=180)
        self._veto_policy.setCurrentText(str(self.config.get("consensus_veto_policy", "require_approval")))
        self._veto_policy.currentTextChanged.connect(self._on_change)
        cc.addWidget(_Card.row("Veto Policy", self._veto_policy, "HIGH/CRITICAL risk geldiğinde davranış"))

        layout.addWidget(consensus_card)

        # Learning
        layout.addWidget(SectionHeader("Learning"))
        learning_card = _Card()
        lc = learning_card._row_layout

        balance_wrap = QWidget()
        balance_wrap.setStyleSheet("background: transparent;")
        bw = QHBoxLayout(balance_wrap)
        bw.setContentsMargins(0, 0, 0, 0)
        bw.setSpacing(10)

        self._explore_slider = QSlider(Qt.Orientation.Horizontal)
        self._explore_slider.setRange(1, 100)
        current_explore = float(self.config.get("consensus_explore_exploit_level", 0.25) or 0.25)
        self._explore_slider.setValue(max(1, min(100, int(round(current_explore * 100)))))
        self._explore_slider.setFixedWidth(220)
        self._explore_slider.setStyleSheet(f"""
            QSlider::groove:horizontal {{ background: {T.BG_SECONDARY}; height: 4px; border-radius: 2px; }}
            QSlider::handle:horizontal {{
                background: {T.ACCENT_BLUE}; width: 16px; height: 16px;
                margin: -6px 0; border-radius: 8px;
            }}
            QSlider::sub-page:horizontal {{ background: {T.ACCENT_BLUE}; border-radius: 2px; }}
        """)
        self._explore_slider.valueChanged.connect(self._on_explore_change)
        bw.addWidget(self._explore_slider)

        self._explore_label = QLabel("")
        self._explore_label.setFixedWidth(92)
        self._explore_label.setStyleSheet(f"color: {T.TEXT_SECONDARY}; font-size: 13px; font-weight: 500;")
        bw.addWidget(self._explore_label)

        lc.addWidget(_Card.row("Explore / Exploit", balance_wrap, "UCB keşif katsayısı seviyesi"))

        lc.addWidget(Divider())

        self._learning_mode = _styled_combo(["hybrid", "explicit"], width=140)
        self._learning_mode.setCurrentText(str(self.config.get("learning_mode", "hybrid")))
        self._learning_mode.currentTextChanged.connect(self._on_change)
        lc.addWidget(_Card.row("Learning Mode", self._learning_mode, "hybrid: açık+örtük, explicit: sadece kullanıcı feedback"))

        layout.addWidget(learning_card)

        # Retention
        layout.addWidget(SectionHeader("Retention"))
        retention_card = _Card()
        rc = retention_card._row_layout

        self._retention_policy = _styled_combo(["long", "short", "aggregate"], width=160)
        self._retention_policy.setCurrentText(str(self.config.get("learning_retention_policy", "long")))
        self._retention_policy.currentTextChanged.connect(self._on_retention_change)
        rc.addWidget(_Card.row("Retention Policy", self._retention_policy, "Öğrenme sinyali saklama politikası"))

        rc.addWidget(Divider())

        retention_view = QWidget()
        retention_view.setStyleSheet("background: transparent;")
        rv = QVBoxLayout(retention_view)
        rv.setContentsMargins(20, 10, 20, 10)
        rv.setSpacing(4)

        retention_title = QLabel("Policy Preview")
        retention_title.setFont(QFont(T.FONT_UI, 12, QFont.Weight.Medium))
        retention_title.setStyleSheet(f"color: {T.TEXT_PRIMARY}; background: transparent;")
        rv.addWidget(retention_title)

        self._retention_preview = QLabel("")
        self._retention_preview.setWordWrap(True)
        self._retention_preview.setStyleSheet(f"color: {T.TEXT_SECONDARY}; font-size: 11px; background: transparent;")
        rv.addWidget(self._retention_preview)
        rc.addWidget(retention_view)

        layout.addWidget(retention_card)

        # Controls
        layout.addWidget(SectionHeader("Controls"))
        control_card = _Card()
        cl = control_card._row_layout

        self._delete_hint = QLabel("Kullanıcı bazlı öğrenme verisini silme isteği runtime katmanına iletilir.")
        self._delete_hint.setWordWrap(True)
        self._delete_hint.setStyleSheet(f"color: {T.TEXT_SECONDARY}; font-size: 11px; padding: 2px 4px;")

        delete_wrap = QWidget()
        delete_wrap.setStyleSheet("background: transparent;")
        dl = QVBoxLayout(delete_wrap)
        dl.setContentsMargins(20, 12, 20, 12)
        dl.setSpacing(8)
        dl.addWidget(self._delete_hint)

        delete_btn = QPushButton("Kullanıcı Verisini Sil")
        delete_btn.setFixedHeight(32)
        delete_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: #FF3B30;
                border: 1px solid #FF3B30;
                border-radius: 8px;
                padding: 0 14px;
                font-size: 12px;
                font-weight: 600;
            }}
            QPushButton:hover {{ background: #FF3B3014; }}
            QPushButton:pressed {{ background: #FF3B3020; }}
        """)
        delete_btn.clicked.connect(self._emit_delete_request)
        dl.addWidget(delete_btn, 0, Qt.AlignmentFlag.AlignLeft)
        cl.addWidget(delete_wrap)

        layout.addWidget(control_card)

        # Metrics
        layout.addWidget(SectionHeader("Live Metrics"))
        metrics_card = _Card()
        ml = metrics_card._row_layout

        self._active_mode_metric = self._metric_label("")
        self._deadlock_metric = self._metric_label("")
        self._override_metric = self._metric_label("")
        self._learning_score_metric = self._metric_label("")

        ml.addWidget(_Card.row("Active Mode", self._active_mode_metric, "Current operator state"))
        ml.addWidget(Divider())
        ml.addWidget(_Card.row("Deadlock Rate", self._deadlock_metric, "Observed deadlock percentage"))
        ml.addWidget(Divider())
        ml.addWidget(_Card.row("Consensus Overrides", self._override_metric, "Manual overrides since last reset"))
        ml.addWidget(Divider())
        ml.addWidget(_Card.row("Learning Score", self._learning_score_metric, "Current learning quality signal"))

        layout.addWidget(metrics_card)
        layout.addStretch()

        self._refresh_retention_preview()
        self._refresh_metrics()
        self._on_explore_change(self._explore_slider.value())
        self._metrics_timer = QTimer(self)
        self._metrics_timer.timeout.connect(self._refresh_metrics)
        self._metrics_timer.start(2500)

    def _metric_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setFont(QFont(T.FONT_UI, 12, QFont.Weight.Medium))
        lbl.setStyleSheet(f"color: {T.TEXT_PRIMARY}; background: transparent;")
        return lbl

    def _retention_description(self, policy: str) -> str:
        mapping = {
            "long": "Ham öğrenme sinyalleri uzun süre saklanır.",
            "short": "Ham sinyaller kısa ömürlü tutulur (yaklaşık 30 gün).",
            "aggregate": "Ham sinyaller tutulmaz, sadece agregalar kalır.",
        }
        return mapping.get(policy, mapping["long"])

    def _refresh_retention_preview(self):
        policy = self._retention_policy.currentText()
        self._retention_preview.setText(self._retention_description(policy))

    def _refresh_metrics(self):
        mode = "UNKNOWN"
        deadlock_rate = 0.0
        overrides = 0
        learning_score = 0.0
        try:
            from core.cognitive_layer_integrator import get_cognitive_integrator

            runtime = get_cognitive_integrator().get_runtime_metrics("local")
            mode = str(runtime.get("mode", "UNKNOWN"))
            deadlock_rate = float(runtime.get("deadlock_rate", 0.0) or 0.0)
            overrides = int(runtime.get("consensus_overrides", 0) or 0)
            learning_score = float(runtime.get("learning_score", 0.0) or 0.0)
        except Exception:
            pass
        self._active_mode_metric.setText(mode)
        self._deadlock_metric.setText(f"{deadlock_rate:.2f}%")
        self._override_metric.setText(str(overrides))
        self._learning_score_metric.setText(f"{learning_score:.2f}/100")

    def _on_explore_change(self, value: int):
        ratio = max(0.01, min(1.0, value / 100.0))
        if ratio <= 0.25:
            label = "Exploit"
        elif ratio <= 0.6:
            label = "Balanced"
        else:
            label = "Explore"
        self._explore_label.setText(f"{ratio:.2f} ({label})")
        self._refresh_metrics()
        self._on_change()

    def _on_retention_change(self, _text: str):
        self._refresh_retention_preview()
        self._refresh_metrics()
        self._on_change()

    def _emit_delete_request(self):
        self.user_data_delete_requested.emit()

    def _on_change(self):
        self._refresh_metrics()
        self.settings_changed.emit(self.get_settings())

    def get_settings(self) -> dict:
        return {
            "consensus_enabled": _switch_checked(self._consensus_enabled),
            "consensus_veto_policy": self._veto_policy.currentText(),
            "consensus_explore_exploit_level": round(max(0.01, min(1.0, self._explore_slider.value() / 100.0)), 3),
            "learning_mode": self._learning_mode.currentText(),
            "learning_retention_policy": self._retention_policy.currentText(),
        }


# ═══════════════════════════════════════════════════════════════
# Skills Settings Page
# ═══════════════════════════════════════════════════════════════
class _SkillsPage(QWidget):
    settings_changed = pyqtSignal(dict)

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self.config = config
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        layout.addWidget(SectionHeader("Skill Yönetimi"))

        desc = QLabel("Yüklü skill/plugin'leri yönetin. Skill'ler ~/.elyan/skills/ dizininde bulunur.")
        desc.setFont(QFont(T.FONT_UI, 12))
        desc.setStyleSheet(f"color: {T.TEXT_SECONDARY}; padding: 0 4px;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # Built-in skills
        layout.addWidget(SectionHeader("Dahili Skill'ler"))
        builtin_card = _Card()
        bc = builtin_card._row_layout

        skills_config = self.config.get("skills", {})
        self._skill_switches = {}

        builtin_skills = [
            ("system", "Sistem", "Sistem bilgisi, ekran görüntüsü, ses kontrolü"),
            ("files", "Dosya", "Dosya okuma, yazma, arama işlemleri"),
            ("research", "Araştırma", "Web araştırma, rapor oluşturma"),
            ("browser", "Tarayıcı", "Web otomasyon, sayfa gezinme"),
            ("office", "Ofis", "Excel, PDF, belge işleme"),
            ("email", "E-posta", "E-posta gönderme ve okuma"),
        ]

        for i, (key, label, desc_text) in enumerate(builtin_skills):
            sw = _styled_check(skills_config.get(key, {}).get("enabled", True))
            sw.toggled.connect(self._on_change)
            bc.addWidget(_Card.row(label, sw, desc_text))
            self._skill_switches[key] = sw
            if i < len(builtin_skills) - 1:
                bc.addWidget(Divider())

        layout.addWidget(builtin_card)

        # External skills
        layout.addWidget(SectionHeader("Harici Skill'ler"))
        ext_card = _Card()
        ec = ext_card._row_layout

        ext_skills = [
            ("github", "GitHub", "Repo, PR, issue yönetimi"),
            ("spotify", "Spotify", "Müzik kontrolü ve playlist"),
        ]

        for i, (key, label, desc_text) in enumerate(ext_skills):
            sw = _styled_check(skills_config.get(key, {}).get("enabled", False))
            sw.toggled.connect(self._on_change)
            ec.addWidget(_Card.row(label, sw, desc_text))
            self._skill_switches[key] = sw
            if i < len(ext_skills) - 1:
                ec.addWidget(Divider())

        layout.addWidget(ext_card)
        layout.addStretch()

    def _on_change(self):
        self.settings_changed.emit(self.get_settings())

    def get_settings(self) -> dict:
        skills = {}
        for key, sw in self._skill_switches.items():
            skills[key] = {"enabled": _switch_checked(sw)}
        return {"skills": skills}


# ═══════════════════════════════════════════════════════════════
# Main Settings Panel (with sidebar)
# ═══════════════════════════════════════════════════════════════
class SettingsPanelUI(QWidget):
    settings_changed = pyqtSignal(dict)
    user_data_delete_requested = pyqtSignal()

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
        categories = ["AI", "Telegram", "Kanallar", "Cron", "Skill'ler", "Güvenlik", "Operator Intelligence", "Genel", "Fiyatlama"]

        for i, name in enumerate(categories):
            btn = SidebarButton("", name)
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

        self._channels = _ChannelsPage(self.config)
        self._channels.settings_changed.connect(self._on_change)

        self._cron = _CronPage(self.config)
        self._cron.settings_changed.connect(self._on_change)

        self._skills = _SkillsPage(self.config)
        self._skills.settings_changed.connect(self._on_change)

        self._security = _SecurityPage(self.config)
        self._security.settings_changed.connect(self._on_change)

        self._operator_intelligence = _OperatorIntelligencePage(self.config)
        self._operator_intelligence.settings_changed.connect(self._on_change)
        self._operator_intelligence.user_data_delete_requested.connect(self.user_data_delete_requested.emit)

        self._general = _GeneralPage(self.config)
        self._general.settings_changed.connect(self._on_change)

        self._pricing = _PricingPage(self.config)
        self._pricing.settings_changed.connect(self._on_change)

        for page in [self._ai, self._telegram, self._channels, self._cron, self._skills, self._security, self._operator_intelligence, self._general, self._pricing]:
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
        s.update(self._channels.get_settings())
        s.update(self._cron.get_settings())
        s.update(self._skills.get_settings())
        s.update(self._security.get_settings())
        s.update(self._operator_intelligence.get_settings())
        s.update(self._general.get_settings())
        s.update(self._pricing.get_settings())
        return s
