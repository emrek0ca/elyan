"""
AI settings panel for Elyan.
Extracted from clean_main_app to keep UI code modular.
"""

from __future__ import annotations

import os
import subprocess
import time
from typing import Optional

from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QLineEdit,
    QComboBox,
)

from config.settings_manager import SettingsPanel
from core.model_orchestrator import model_orchestrator
from ui.components import GlassFrame, AnimatedButton
from utils.logger import get_logger

logger = get_logger("ai_settings_panel")


class ConnectionTestWorker(QThread):
    """Runs provider connection checks without blocking the UI thread."""

    finished_signal = pyqtSignal(bool, str, str, int)

    def __init__(self, provider: str, api_key: str, host: str):
        super().__init__()
        self.provider = provider
        self.api_key = api_key
        self.host = host

    def run(self):
        started_at = time.time()
        ok = False
        summary = "Bağlantı doğrulanamadı"
        detail = ""
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                ok, summary, detail, retryable = self._validate()
                if ok:
                    break
                if not retryable or attempt == max_attempts:
                    break
            except Exception as exc:
                summary = "Bağlantı testi hata verdi"
                detail = str(exc)
                retryable = True
                if attempt == max_attempts:
                    break
            # Exponential backoff: 0.5s, 1.0s
            time.sleep(0.5 * (2 ** (attempt - 1)))

        if not ok and summary:
            summary = f"{summary} (deneme {min(max_attempts, attempt)}/{max_attempts})"
        latency_ms = int((time.time() - started_at) * 1000)
        self.finished_signal.emit(ok, summary, detail, latency_ms)

    def _validate(self) -> tuple[bool, str, str, bool]:
        provider = self.provider.strip().lower()
        if provider == "ollama":
            env = os.environ.copy()
            env["OLLAMA_HOST"] = self.host
            result = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=6, env=env)
            if result.returncode == 0:
                return True, "Ollama erişilebilir", self.host, False
            detail = (result.stderr or result.stdout or "Yanıt alınamadı").strip()[:280]
            return False, "Ollama erişilemiyor", detail, True

        if not self.api_key:
            return False, "API key boş", "Cloud provider için API key gerekli.", False

        import httpx
        if provider == "groq":
            headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
            body = {"model": "llama-3.3-70b-versatile", "messages": [{"role": "user", "content": "ping"}], "max_tokens": 5}
            r = httpx.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=body, timeout=8.0)
            retryable = r.status_code in {408, 429, 500, 502, 503, 504}
            return (r.status_code == 200, "Groq API doğrulandı" if r.status_code == 200 else "Groq API hatası", f"HTTP {r.status_code}", retryable)
        if provider == "gemini":
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={self.api_key}"
            r = httpx.post(url, json={"contents": [{"parts": [{"text": "ping"}]}]}, timeout=8.0)
            retryable = r.status_code in {408, 429, 500, 502, 503, 504}
            return (r.status_code == 200, "Gemini API doğrulandı" if r.status_code == 200 else "Gemini API hatası", f"HTTP {r.status_code}", retryable)
        if provider == "openai":
            headers = {"Authorization": f"Bearer {self.api_key}"}
            r = httpx.get("https://api.openai.com/v1/models", headers=headers, timeout=8.0)
            retryable = r.status_code in {408, 429, 500, 502, 503, 504}
            return (r.status_code == 200, "OpenAI API doğrulandı" if r.status_code == 200 else "OpenAI API hatası", f"HTTP {r.status_code}", retryable)
        if provider == "anthropic":
            headers = {
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            }
            body = {
                "model": "claude-3-5-haiku-latest",
                "max_tokens": 8,
                "messages": [{"role": "user", "content": "ping"}],
            }
            r = httpx.post("https://api.anthropic.com/v1/messages", headers=headers, json=body, timeout=8.0)
            retryable = r.status_code in {408, 429, 500, 502, 503, 504}
            return (r.status_code == 200, "Anthropic API doğrulandı" if r.status_code == 200 else "Anthropic API hatası", f"HTTP {r.status_code}", retryable)
        return False, "Bilinmeyen provider", provider, False


class CleanAIPanel(QWidget):
    """AI control center with provider/model switching."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._settings = SettingsPanel()
        self._connection_worker: Optional[ConnectionTestWorker] = None
        self._providers = {
            "groq": ["llama-3.3-70b-versatile", "mixtral-8x7b-32768", "llama-3.1-8b-instant"],
            "gemini": ["gemini-2.0-flash", "gemini-1.5-pro", "gemini-1.5-flash"],
            "openai": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"],
            "anthropic": ["claude-opus-4-5-20251101", "claude-3-5-sonnet-latest", "claude-3-5-haiku-latest"],
            "ollama": [],
        }
        self._setup_ui()
        self._load_settings()

    def _setup_ui(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background-color: transparent; }")

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(12)

        header = QLabel("AI")
        header.setFont(QFont(".AppleSystemUIFont", 24, QFont.Weight.DemiBold))
        header.setStyleSheet("color: #111318; border: none; letter-spacing: -0.5px;")
        layout.addWidget(header)

        desc = QLabel("Otomatik çalışan temel LLM ayarları")
        desc.setFont(QFont(".AppleSystemUIFont", 12))
        desc.setStyleSheet("color: #8B95A7;")
        layout.addWidget(desc)

        provider_card = GlassFrame()
        provider_layout = QVBoxLayout(provider_card)
        provider_layout.setContentsMargins(18, 16, 18, 16)
        provider_layout.setSpacing(10)

        row_provider = QHBoxLayout()
        provider_label = QLabel("Sağlayıcı")
        provider_label.setFont(QFont(".AppleSystemUIFont", 13, QFont.Weight.Medium))
        provider_label.setFixedWidth(100)
        provider_label.setStyleSheet("color: #8B95A7;")
        row_provider.addWidget(provider_label)

        self._provider_combo = QComboBox()
        self._provider_combo.addItems(["groq", "gemini", "openai", "anthropic", "ollama"])
        self._provider_combo.currentTextChanged.connect(self._on_provider_changed)
        self._provider_combo.setStyleSheet(
            """
            QComboBox {
                background-color: #F8FAFC;
                border: 1px solid #E2E8F0;
                border-radius: 8px;
                padding: 10px 16px;
                color: #0F172A;
            }
            QComboBox::drop-down { border: none; }
            """
        )
        row_provider.addWidget(self._provider_combo, 1)
        provider_layout.addLayout(row_provider)

        row_api = QHBoxLayout()
        api_label = QLabel("API Key")
        api_label.setFont(QFont(".AppleSystemUIFont", 13, QFont.Weight.Medium))
        api_label.setFixedWidth(100)
        api_label.setStyleSheet("color: #8B95A7;")
        row_api.addWidget(api_label)

        self._api_key_input = QLineEdit()
        self._api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_key_input.setPlaceholderText("Provider API anahtarını girin")
        self._api_key_input.setStyleSheet(
            """
            QLineEdit {
                background-color: #F8FAFC;
                border: 1px solid #E2E8F0;
                border-radius: 8px;
                padding: 10px 16px;
                color: #0F172A;
            }
            QLineEdit:focus { border-color: #3b82f6; }
            """
        )
        row_api.addWidget(self._api_key_input, 1)
        provider_layout.addLayout(row_api)

        self._host_row_widget = QWidget()
        row_host = QHBoxLayout(self._host_row_widget)
        row_host.setContentsMargins(0, 0, 0, 0)
        host_label = QLabel("Ollama Host")
        host_label.setFont(QFont(".AppleSystemUIFont", 13, QFont.Weight.Medium))
        host_label.setFixedWidth(100)
        host_label.setStyleSheet("color: #8B95A7;")
        row_host.addWidget(host_label)
        self._host_input = QLineEdit()
        self._host_input.setPlaceholderText("http://localhost:11434")
        self._host_input.setStyleSheet(
            """
            QLineEdit {
                background-color: #F8FAFC;
                border: 1px solid #E2E8F0;
                border-radius: 8px;
                padding: 10px 16px;
                color: #0F172A;
            }
            QLineEdit:focus { border-color: #3b82f6; }
            """
        )
        row_host.addWidget(self._host_input, 1)
        provider_layout.addWidget(self._host_row_widget)

        model_row = QHBoxLayout()
        model_label = QLabel("Model")
        model_label.setFont(QFont(".AppleSystemUIFont", 13, QFont.Weight.Medium))
        model_label.setFixedWidth(100)
        model_label.setStyleSheet("color: #8B95A7;")
        model_row.addWidget(model_label)
        self._model_combo = QComboBox()
        self._model_combo.setEditable(True)
        self._model_combo.setStyleSheet(
            """
            QComboBox {
                background-color: #F8FAFC;
                border: 1px solid #E2E8F0;
                border-radius: 8px;
                padding: 10px 16px;
                color: #0F172A;
            }
            QComboBox::drop-down { border: none; }
            """
        )
        model_row.addWidget(self._model_combo, 1)
        provider_layout.addLayout(model_row)

        layout.addWidget(provider_card)

        status_card = GlassFrame()
        status_layout = QHBoxLayout(status_card)
        status_layout.setContentsMargins(18, 14, 18, 14)

        self._ollama_status = QLabel("Bağlantı durumu kontrol ediliyor...")
        self._ollama_status.setFont(QFont(".AppleSystemUIFont", 13))
        self._ollama_status.setStyleSheet("color: #94a3b8; border: none;")
        status_layout.addWidget(self._ollama_status, 1)

        self._test_btn = QPushButton("Bağlantıyı Test Et")
        self._test_btn.clicked.connect(self._test_connection)
        self._test_btn.setFont(QFont(".AppleSystemUIFont", 11))
        self._test_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._test_btn.setStyleSheet(
            """
            QPushButton {
                background-color: #0ea5e9;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 7px 12px;
            }
            QPushButton:hover { background-color: #0284c7; }
            """
        )
        status_layout.addWidget(self._test_btn)
        layout.addWidget(status_card)

        self._connection_detail = QLabel("Son test: henüz yapılmadı")
        self._connection_detail.setWordWrap(True)
        self._connection_detail.setFont(QFont(".AppleSystemUIFont", 11))
        self._connection_detail.setStyleSheet("color: #64748b; padding: 2px 2px;")
        layout.addWidget(self._connection_detail)

        actions = QHBoxLayout()
        actions.addStretch()
        self._save_btn = AnimatedButton("Ayarları Kaydet", primary=True)
        self._save_btn.clicked.connect(self._save_settings)
        actions.addWidget(self._save_btn)
        layout.addLayout(actions)

        layout.addStretch()
        scroll.setWidget(content)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(scroll)

    def _load_settings(self):
        provider = str(self._settings.get("llm_provider", "groq")).strip().lower()
        if provider not in self._providers:
            provider = "groq"
        self._provider_combo.setCurrentText(provider)
        self._api_key_input.setText(str(self._settings.get("api_key", "")))
        self._host_input.setText(str(self._settings.get("ollama_host", "http://localhost:11434")))
        self._on_provider_changed(provider)
        model = str(self._settings.get("llm_model", "")).strip()
        if model:
            idx = self._model_combo.findText(model)
            if idx >= 0:
                self._model_combo.setCurrentIndex(idx)
            else:
                self._model_combo.setCurrentText(model)
        self._refresh_ollama_status()

    def _refresh_models(self, provider: str):
        self._model_combo.clear()
        if provider == "ollama":
            self._model_combo.addItems(self._get_local_ollama_models())
            return
        self._model_combo.addItems(self._providers.get(provider, []))

    def _on_provider_changed(self, provider: str):
        self._host_row_widget.setVisible(provider == "ollama")
        self._api_key_input.setVisible(provider != "ollama")
        self._refresh_models(provider)
        self._refresh_ollama_status()

    def _get_local_ollama_models(self) -> list[str]:
        try:
            host = self._host_input.text().strip() or "http://localhost:11434"
            env = os.environ.copy()
            env["OLLAMA_HOST"] = host
            result = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=4, env=env)
            models: list[str] = []
            for line in result.stdout.strip().splitlines()[1:]:
                parts = line.split()
                if parts:
                    models.append(parts[0])
            return models or ["llama3.2:3b", "llama3.1:8b", "mistral"]
        except Exception:
            return ["llama3.2:3b", "llama3.1:8b", "mistral"]

    def _refresh_ollama_status(self):
        if self._provider_combo.currentText() != "ollama":
            self._set_status("info", "Cloud provider seçildi", "Cloud provider için API key doğrulaması kullanın.")
            return
        try:
            host = self._host_input.text().strip() or "http://localhost:11434"
            env = os.environ.copy()
            env["OLLAMA_HOST"] = host
            result = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=4, env=env)
            if result.returncode == 0:
                self._set_status("success", f"Ollama bağlı ({host})", "Yerel model listesi erişilebilir.")
            else:
                detail = (result.stderr or result.stdout or "Yanıt alınamadı").strip()[:240]
                self._set_status("error", "Ollama erişilemiyor", detail)
        except Exception:
            self._set_status("error", "Ollama erişilemiyor", "Lokal ollama servisi yanıt vermedi.")

    def _test_connection(self):
        provider = self._provider_combo.currentText().strip().lower()
        host = self._host_input.text().strip() or "http://localhost:11434"
        key = self._api_key_input.text().strip() if provider != "ollama" else ""
        self._set_status("info", "Bağlantı test ediliyor...", f"Provider: {provider}")
        self._test_btn.setEnabled(False)
        self._test_btn.setText("Test Ediliyor...")

        self._connection_worker = ConnectionTestWorker(provider=provider, api_key=key, host=host)
        self._connection_worker.finished_signal.connect(self._on_test_completed)
        self._connection_worker.start()

    def _on_test_completed(self, ok: bool, summary: str, detail: str, latency_ms: int):
        provider = self._provider_combo.currentText().strip().lower()
        if ok:
            self._set_status("success", summary, f"{detail} | Gecikme: {latency_ms} ms")
        else:
            self._set_status("error", summary, f"{detail} | Gecikme: {latency_ms} ms")
        self._test_btn.setEnabled(True)
        self._test_btn.setText("Bağlantıyı Test Et")
        if self._connection_worker is not None:
            self._connection_worker.deleteLater()
            self._connection_worker = None

    def _save_settings(self):
        provider = self._provider_combo.currentText().strip().lower()
        model = self._model_combo.currentText().strip()
        api_key = self._api_key_input.text().strip()
        if provider != "ollama" and not api_key:
            self._set_status("error", "Ayar kaydedilemedi", f"{provider} için API key gerekli.")
            return
        if provider == "ollama":
            host = self._host_input.text().strip() or "http://localhost:11434"
            if not (host.startswith("http://") or host.startswith("https://")):
                self._set_status("error", "Ayar kaydedilemedi", "Ollama host http:// veya https:// ile başlamalı.")
                return

        updates = {
            "llm_provider": provider,
            "llm_model": model,
            "api_key": api_key if provider != "ollama" else "",
            "ollama_host": self._host_input.text().strip() or "http://localhost:11434",
        }
        self._settings.update(updates)
        self._apply_live_llm_updates(updates)
        self._set_status("success", f"Ayarlar kaydedildi: {provider}/{model}", "Canlı LLM konfigürasyonu güncellendi.")

    def _set_status(self, level: str, title: str, detail: str = ""):
        color_map = {"success": "#16a34a", "error": "#dc2626", "info": "#2563eb"}
        color = color_map.get(level, "#64748b")
        self._ollama_status.setText(title)
        self._ollama_status.setStyleSheet(f"color: {color}; border: none;")
        if detail:
            self._connection_detail.setText(detail)

    def _apply_live_llm_updates(self, updates: dict):
        try:
            main_win = self.window()
            worker = getattr(main_win, "_bot_worker", None)
            agent = getattr(worker, "_agent", None) if worker else None
            llm = getattr(agent, "llm", None) if agent else None
            if not llm:
                return
            provider = str(updates.get("llm_provider", "ollama"))
            llm.llm_type = provider
            llm.model = str(updates.get("llm_model", llm.model))
            llm.host = str(updates.get("ollama_host", llm.host))
            api_key = str(updates.get("api_key", ""))
            if provider == "groq":
                llm.groq_api_key = api_key
            elif provider == "gemini":
                llm.api_key = api_key
            elif provider == "openai":
                llm.openai_api_key = api_key
            elif provider == "anthropic":
                llm.anthropic_api_key = api_key
            model_orchestrator._load_providers()
        except Exception as exc:
            logger.debug(f"Live LLM update skipped: {exc}")
