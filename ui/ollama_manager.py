"""
Ollama Manager - Auto-installer and manager for local LLM
"""

import os
import sys
import subprocess
import platform
import shutil
from pathlib import Path
from typing import Optional, List, Dict, Any, Callable
from dataclasses import dataclass
from enum import Enum
import json
import asyncio

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QFrame, QGroupBox, QComboBox, QMessageBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QApplication
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QColor

from utils.logger import get_logger

logger = get_logger("ollama_manager")


class OllamaStatus(Enum):
    NOT_INSTALLED = "not_installed"
    INSTALLED = "installed"
    RUNNING = "running"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass
class OllamaModel:
    name: str
    size: str
    description: str
    recommended: bool = False


AVAILABLE_MODELS = [
    OllamaModel("llama3.2:3b", "2.0 GB", "Hızlı ve verimli, günlük kullanım için ideal", recommended=True),
    OllamaModel("llama3.2:1b", "1.3 GB", "Hafif model, düşük kaynak kullanımı"),
    OllamaModel("llama3.1:8b", "4.7 GB", "Daha yetenekli, karmaşık görevler için"),
    OllamaModel("mistral:7b", "4.1 GB", "Güçlü alternatif model"),
    OllamaModel("codellama:7b", "3.8 GB", "Kod yazma ve analiz için özelleştirilmiş"),
    OllamaModel("phi3:mini", "2.3 GB", "Microsoft'un kompakt modeli"),
    OllamaModel("gemma2:2b", "1.6 GB", "Google'ın hafif modeli"),
    OllamaModel("qwen2:7b", "4.4 GB", "Alibaba'nın güçlü modeli"),
]


class OllamaInstallerWorker(QThread):
    """Background worker for Ollama installation"""

    progress = pyqtSignal(int, str)
    finished = pyqtSignal(bool, str)
    model_progress = pyqtSignal(str, int)

    def __init__(self, model_name: str = "llama3.2:3b"):
        super().__init__()
        self.model_name = model_name
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            # Check if Ollama is installed
            self.progress.emit(5, "Ollama kurulumu kontrol ediliyor...")

            ollama_installed = self._check_ollama_installed()

            if not ollama_installed:
                self.progress.emit(10, "Ollama indiriliyor ve kuruluyor...")

                if platform.system() == "Darwin":  # macOS
                    success = self._install_macos()
                elif platform.system() == "Linux":
                    success = self._install_linux()
                elif platform.system() == "Windows":
                    success = self._install_windows()
                else:
                    self.finished.emit(False, f"Desteklenmeyen işletim sistemi: {platform.system()}")
                    return

                if not success:
                    self.finished.emit(False, "Ollama kurulumu başarısız oldu")
                    return

                self.progress.emit(40, "Ollama kuruldu!")
            else:
                self.progress.emit(40, "Ollama zaten yüklü")

            if self._cancelled:
                return

            # Start Ollama service
            self.progress.emit(50, "Ollama servisi başlatılıyor...")
            self._start_ollama_service()

            import time
            time.sleep(3)

            if self._cancelled:
                return

            # Pull the model
            self.progress.emit(60, f"{self.model_name} modeli indiriliyor...")
            success = self._pull_model(self.model_name)

            if success:
                self.progress.emit(100, "Kurulum tamamlandı!")
                self.finished.emit(True, f"Ollama ve {self.model_name} başarıyla kuruldu!")
            else:
                self.finished.emit(False, f"{self.model_name} modeli indirilemedi")

        except Exception as e:
            logger.error(f"Installation error: {e}")
            self.finished.emit(False, str(e))

    def _check_ollama_installed(self) -> bool:
        """Check if Ollama is installed"""
        try:
            result = subprocess.run(
                ["which", "ollama"] if platform.system() != "Windows" else ["where", "ollama"],
                capture_output=True,
                text=True
            )
            return result.returncode == 0
        except:
            return False

    def _install_macos(self) -> bool:
        """Install Ollama on macOS"""
        try:
            # Try using brew first
            brew_check = subprocess.run(["which", "brew"], capture_output=True)

            if brew_check.returncode == 0:
                self.progress.emit(20, "Homebrew ile Ollama kuruluyor...")
                result = subprocess.run(
                    ["brew", "install", "ollama"],
                    capture_output=True,
                    text=True
                )
                if result.returncode == 0:
                    return True

            # Fallback to curl installer
            self.progress.emit(25, "Ollama installer indiriliyor...")
            result = subprocess.run(
                ["curl", "-fsSL", "https://ollama.com/install.sh", "-o", "/tmp/ollama_install.sh"],
                capture_output=True
            )

            if result.returncode == 0:
                subprocess.run(["chmod", "+x", "/tmp/ollama_install.sh"])
                result = subprocess.run(
                    ["/bin/bash", "/tmp/ollama_install.sh"],
                    capture_output=True
                )
                return result.returncode == 0

            return False

        except Exception as e:
            logger.error(f"macOS installation error: {e}")
            return False

    def _install_linux(self) -> bool:
        """Install Ollama on Linux"""
        try:
            self.progress.emit(20, "Ollama Linux kurulumu...")
            result = subprocess.run(
                ["curl", "-fsSL", "https://ollama.com/install.sh"],
                capture_output=True,
                text=True
            )

            if result.returncode == 0:
                # Run the installer script
                process = subprocess.Popen(
                    ["sh", "-c", result.stdout],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )
                process.wait()
                return process.returncode == 0

            return False

        except Exception as e:
            logger.error(f"Linux installation error: {e}")
            return False

    def _install_windows(self) -> bool:
        """Install Ollama on Windows"""
        try:
            self.progress.emit(20, "Ollama Windows kurulumu...")

            # Download installer
            import urllib.request
            installer_url = "https://ollama.com/download/OllamaSetup.exe"
            installer_path = Path.home() / "Downloads" / "OllamaSetup.exe"

            urllib.request.urlretrieve(installer_url, str(installer_path))

            # Run installer
            subprocess.run([str(installer_path), "/SILENT"], check=True)
            return True

        except Exception as e:
            logger.error(f"Windows installation error: {e}")
            return False

    def _start_ollama_service(self):
        """Start Ollama service"""
        try:
            # Check if already running
            try:
                import httpx
                response = httpx.get("http://localhost:11434/api/tags", timeout=2)
                if response.status_code == 200:
                    return  # Already running
            except:
                pass

            # Start the service
            if platform.system() == "Darwin":
                subprocess.Popen(
                    ["ollama", "serve"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True
                )
            elif platform.system() == "Linux":
                subprocess.Popen(
                    ["systemctl", "--user", "start", "ollama"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
            elif platform.system() == "Windows":
                subprocess.Popen(
                    ["ollama", "serve"],
                    creationflags=subprocess.CREATE_NO_WINDOW
                )

        except Exception as e:
            logger.error(f"Service start error: {e}")

    def _pull_model(self, model_name: str) -> bool:
        """Pull a model"""
        try:
            process = subprocess.Popen(
                ["ollama", "pull", model_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True
            )

            while True:
                if self._cancelled:
                    process.terminate()
                    return False

                line = process.stdout.readline()
                if not line and process.poll() is not None:
                    break

                if "pulling" in line.lower() or "%" in line:
                    # Parse progress if possible
                    self.progress.emit(70, f"Model indiriliyor: {model_name}")

            return process.returncode == 0

        except Exception as e:
            logger.error(f"Model pull error: {e}")
            return False


class OllamaStatusChecker(QThread):
    """Background worker for checking Ollama status"""

    status_updated = pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        self._running = True

    def stop(self):
        self._running = False

    def run(self):
        while self._running:
            status = self._check_status()
            self.status_updated.emit(status)

            import time
            time.sleep(5)  # Check every 5 seconds

    def _check_status(self) -> dict:
        """Check Ollama status and get installed models"""
        status = {
            "status": OllamaStatus.NOT_INSTALLED,
            "version": None,
            "models": [],
            "running": False
        }

        try:
            # Check if installed
            result = subprocess.run(
                ["ollama", "--version"],
                capture_output=True,
                text=True
            )

            if result.returncode == 0:
                status["status"] = OllamaStatus.INSTALLED
                status["version"] = result.stdout.strip()

                # Check if running
                try:
                    import httpx
                    response = httpx.get("http://localhost:11434/api/tags", timeout=2)
                    if response.status_code == 200:
                        status["status"] = OllamaStatus.RUNNING
                        status["running"] = True

                        # Get models
                        data = response.json()
                        status["models"] = [
                            {
                                "name": m["name"],
                                "size": self._format_size(m.get("size", 0)),
                                "modified": m.get("modified_at", "")
                            }
                            for m in data.get("models", [])
                        ]
                except:
                    status["status"] = OllamaStatus.STOPPED

        except:
            status["status"] = OllamaStatus.NOT_INSTALLED

        return status

    def _format_size(self, size_bytes: int) -> str:
        """Format size in bytes to human readable"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_bytes < 1024:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f} TB"


class OllamaManager(QWidget):
    """Ollama Manager UI Widget"""

    status_changed = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)

        self._installer = None
        self._status_checker = None
        self._current_status = {}

        self._setup_ui()
        self._start_status_checker()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        # Header
        header = self._create_header()
        layout.addWidget(header)

        # Status Card
        status_card = self._create_status_card()
        layout.addWidget(status_card)

        # Models section
        models_section = self._create_models_section()
        layout.addWidget(models_section)

        # Install section
        install_section = self._create_install_section()
        layout.addWidget(install_section)

        layout.addStretch()

    def _create_header(self) -> QFrame:
        """Create header"""
        header = QFrame()
        header.setStyleSheet("""
            QFrame {
                background-color: #1a1a1a;
                border-radius: 12px;
                padding: 16px;
            }
        """)

        layout = QHBoxLayout(header)

        # Icon and title
        icon_label = QLabel("🦙")
        icon_label.setStyleSheet("font-size: 32px;")
        layout.addWidget(icon_label)

        title_layout = QVBoxLayout()
        title = QLabel("Ollama Manager")
        title.setStyleSheet("color: #ffffff; font-size: 20px; font-weight: bold;")
        title_layout.addWidget(title)

        subtitle = QLabel("Yerel yapay zeka modellerinizi yönetin")
        subtitle.setStyleSheet("color: #71717a; font-size: 13px;")
        title_layout.addWidget(subtitle)

        layout.addLayout(title_layout)
        layout.addStretch()

        # Quick actions
        refresh_btn = QPushButton("")
        refresh_btn.setFixedSize(36, 36)
        refresh_btn.setToolTip("Durumu yenile")
        refresh_btn.setStyleSheet("""
            QPushButton {
                background-color: #27272a;
                border: none;
                border-radius: 18px;
                font-size: 16px;
            }
            QPushButton:hover { background-color: #3f3f46; }
        """)
        refresh_btn.clicked.connect(self._refresh_status)
        layout.addWidget(refresh_btn)

        return header

    def _create_status_card(self) -> QFrame:
        """Create status indicator card"""
        card = QFrame()
        card.setStyleSheet("""
            QFrame {
                background-color: #1a1a1a;
                border-radius: 12px;
                padding: 16px;
            }
        """)

        layout = QHBoxLayout(card)

        # Status indicator
        self._status_dot = QLabel("●")
        self._status_dot.setStyleSheet("color: #ef4444; font-size: 24px;")
        layout.addWidget(self._status_dot)

        # Status text
        status_text_layout = QVBoxLayout()

        self._status_label = QLabel("Durum Kontrol Ediliyor...")
        self._status_label.setStyleSheet("color: #ffffff; font-size: 16px; font-weight: bold;")
        status_text_layout.addWidget(self._status_label)

        self._version_label = QLabel("")
        self._version_label.setStyleSheet("color: #71717a; font-size: 12px;")
        status_text_layout.addWidget(self._version_label)

        layout.addLayout(status_text_layout)
        layout.addStretch()

        # Control buttons
        self._start_btn = QPushButton("▶ Başlat")
        self._start_btn.setStyleSheet("""
            QPushButton {
                background-color: #10b981;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 8px 16px;
                font-size: 13px;
            }
            QPushButton:hover { background-color: #059669; }
            QPushButton:disabled { background-color: #3f3f46; }
        """)
        self._start_btn.clicked.connect(self._start_ollama)
        layout.addWidget(self._start_btn)

        self._stop_btn = QPushButton("⏹ Durdur")
        self._stop_btn.setStyleSheet("""
            QPushButton {
                background-color: #ef4444;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 8px 16px;
                font-size: 13px;
            }
            QPushButton:hover { background-color: #dc2626; }
            QPushButton:disabled { background-color: #3f3f46; }
        """)
        self._stop_btn.clicked.connect(self._stop_ollama)
        layout.addWidget(self._stop_btn)

        return card

    def _create_models_section(self) -> QGroupBox:
        """Create installed models section"""
        group = QGroupBox("Yüklü Modeller")
        group.setStyleSheet("""
            QGroupBox {
                color: #ffffff;
                font-size: 14px;
                font-weight: bold;
                border: 1px solid #3f3f46;
                border-radius: 12px;
                padding-top: 16px;
                margin-top: 8px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
            }
        """)

        layout = QVBoxLayout(group)

        # Models table
        self._models_table = QTableWidget()
        self._models_table.setColumnCount(3)
        self._models_table.setHorizontalHeaderLabels(["Model", "Boyut", "İşlem"])
        self._models_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._models_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self._models_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self._models_table.setColumnWidth(1, 100)
        self._models_table.setColumnWidth(2, 80)
        self._models_table.setStyleSheet("""
            QTableWidget {
                background-color: #0f0f0f;
                border: none;
                color: #ffffff;
            }
            QTableWidget::item {
                padding: 8px;
            }
            QHeaderView::section {
                background-color: #1a1a1a;
                color: #a1a1aa;
                padding: 8px;
                border: none;
            }
        """)
        self._models_table.setMaximumHeight(200)
        layout.addWidget(self._models_table)

        # No models message
        self._no_models_label = QLabel("Henüz yüklü model yok. Aşağıdan bir model yükleyin.")
        self._no_models_label.setStyleSheet("color: #71717a; font-size: 13px; padding: 20px;")
        self._no_models_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._no_models_label)

        return group

    def _create_install_section(self) -> QGroupBox:
        """Create model installation section"""
        group = QGroupBox("Model Yükle")
        group.setStyleSheet("""
            QGroupBox {
                color: #ffffff;
                font-size: 14px;
                font-weight: bold;
                border: 1px solid #3f3f46;
                border-radius: 12px;
                padding-top: 16px;
                margin-top: 8px;
            }
        """)

        layout = QVBoxLayout(group)

        # Model selection
        select_layout = QHBoxLayout()

        model_label = QLabel("Model:")
        model_label.setStyleSheet("color: #a1a1aa; font-size: 13px;")
        select_layout.addWidget(model_label)

        self._model_combo = QComboBox()
        for model in AVAILABLE_MODELS:
            display_text = f"{model.name} ({model.size})"
            if model.recommended:
                display_text += " ⭐"
            self._model_combo.addItem(display_text, model.name)
        self._model_combo.setStyleSheet("""
            QComboBox {
                background-color: #27272a;
                border: 1px solid #3f3f46;
                border-radius: 8px;
                padding: 10px 14px;
                color: #ffffff;
                font-size: 13px;
                min-width: 250px;
            }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView {
                background-color: #27272a;
                color: #ffffff;
                selection-background-color: #6366f1;
            }
        """)
        select_layout.addWidget(self._model_combo, 1)

        layout.addLayout(select_layout)

        # Model description
        self._model_desc = QLabel("")
        self._model_desc.setStyleSheet("color: #71717a; font-size: 12px; padding: 8px 0;")
        self._model_combo.currentIndexChanged.connect(self._update_model_description)
        self._update_model_description()
        layout.addWidget(self._model_desc)

        # Progress
        self._install_progress = QProgressBar()
        self._install_progress.setStyleSheet("""
            QProgressBar {
                background-color: #3f3f46;
                border-radius: 8px;
                height: 20px;
                text-align: center;
            }
            QProgressBar::chunk {
                background-color: #6366f1;
                border-radius: 8px;
            }
        """)
        self._install_progress.hide()
        layout.addWidget(self._install_progress)

        self._install_status = QLabel("")
        self._install_status.setStyleSheet("color: #a1a1aa; font-size: 12px;")
        self._install_status.hide()
        layout.addWidget(self._install_status)

        # Install button
        btn_layout = QHBoxLayout()

        self._install_btn = QPushButton("📥 Model Yükle")
        self._install_btn.setMinimumHeight(44)
        self._install_btn.setStyleSheet("""
            QPushButton {
                background-color: #6366f1;
                color: white;
                border: none;
                border-radius: 12px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #4f46e5; }
            QPushButton:disabled { background-color: #3f3f46; }
        """)
        self._install_btn.clicked.connect(self._install_model)
        btn_layout.addWidget(self._install_btn)

        self._cancel_btn = QPushButton("İptal")
        self._cancel_btn.setMinimumHeight(44)
        self._cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #27272a;
                color: white;
                border: 1px solid #3f3f46;
                border-radius: 12px;
                font-size: 14px;
            }
            QPushButton:hover { background-color: #3f3f46; }
        """)
        self._cancel_btn.hide()
        self._cancel_btn.clicked.connect(self._cancel_installation)
        btn_layout.addWidget(self._cancel_btn)

        layout.addLayout(btn_layout)

        return group

    def _start_status_checker(self):
        """Start background status checker"""
        self._status_checker = OllamaStatusChecker()
        self._status_checker.status_updated.connect(self._update_status)
        self._status_checker.start()

    def _update_status(self, status: dict):
        """Update UI based on status"""
        self._current_status = status

        if status["status"] == OllamaStatus.NOT_INSTALLED:
            self._status_dot.setStyleSheet("color: #ef4444; font-size: 24px;")
            self._status_label.setText("Ollama Yüklü Değil")
            self._version_label.setText("Önce Ollama'yı yükleyin")
            self._start_btn.setEnabled(False)
            self._stop_btn.setEnabled(False)

        elif status["status"] == OllamaStatus.RUNNING:
            self._status_dot.setStyleSheet("color: #10b981; font-size: 24px;")
            self._status_label.setText("Ollama Çalışıyor")
            self._version_label.setText(status.get("version", ""))
            self._start_btn.setEnabled(False)
            self._stop_btn.setEnabled(True)

        elif status["status"] == OllamaStatus.STOPPED:
            self._status_dot.setStyleSheet("color: #f59e0b; font-size: 24px;")
            self._status_label.setText("Ollama Durduruldu")
            self._version_label.setText(status.get("version", ""))
            self._start_btn.setEnabled(True)
            self._stop_btn.setEnabled(False)

        else:
            self._status_dot.setStyleSheet("color: #ef4444; font-size: 24px;")
            self._status_label.setText("Ollama Durumu Bilinmiyor")
            self._version_label.setText("")

        # Update models table
        models = status.get("models", [])
        self._update_models_table(models)

        self.status_changed.emit(status)

    def _update_models_table(self, models: List[dict]):
        """Update the models table"""
        self._models_table.setRowCount(len(models))

        if models:
            self._models_table.show()
            self._no_models_label.hide()

            for i, model in enumerate(models):
                name_item = QTableWidgetItem(model["name"])
                name_item.setForeground(QColor("#ffffff"))
                self._models_table.setItem(i, 0, name_item)

                size_item = QTableWidgetItem(model["size"])
                size_item.setForeground(QColor("#a1a1aa"))
                self._models_table.setItem(i, 1, size_item)

                # Delete button
                delete_btn = QPushButton("🗑️")
                delete_btn.setStyleSheet("""
                    QPushButton {
                        background-color: transparent;
                        border: none;
                        font-size: 14px;
                    }
                    QPushButton:hover { background-color: #3f3f46; border-radius: 4px; }
                """)
                delete_btn.clicked.connect(lambda checked, m=model["name"]: self._delete_model(m))
                self._models_table.setCellWidget(i, 2, delete_btn)
        else:
            self._models_table.hide()
            self._no_models_label.show()

    def _update_model_description(self):
        """Update model description based on selection"""
        model_name = self._model_combo.currentData()
        for model in AVAILABLE_MODELS:
            if model.name == model_name:
                desc = f" {model.description}"
                if model.recommended:
                    desc += " (Önerilen)"
                self._model_desc.setText(desc)
                break

    def _refresh_status(self):
        """Manually refresh status"""
        if self._status_checker:
            # Trigger immediate check
            self._status_checker.start()

    def _start_ollama(self):
        """Start Ollama service"""
        try:
            if platform.system() == "Darwin":
                subprocess.Popen(
                    ["ollama", "serve"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True
                )
            elif platform.system() == "Linux":
                subprocess.Popen(["systemctl", "--user", "start", "ollama"])
            elif platform.system() == "Windows":
                subprocess.Popen(["ollama", "serve"], creationflags=subprocess.CREATE_NO_WINDOW)

            QMessageBox.information(self, "Başarılı", " Ollama başlatılıyor...")

        except Exception as e:
            QMessageBox.warning(self, "Hata", f" Başlatma hatası: {e}")

    def _stop_ollama(self):
        """Stop Ollama service"""
        try:
            if platform.system() == "Darwin":
                subprocess.run(["pkill", "-f", "ollama"])
            elif platform.system() == "Linux":
                subprocess.run(["systemctl", "--user", "stop", "ollama"])
            elif platform.system() == "Windows":
                subprocess.run(["taskkill", "/f", "/im", "ollama.exe"])

            QMessageBox.information(self, "Başarılı", " Ollama durduruldu")

        except Exception as e:
            QMessageBox.warning(self, "Hata", f" Durdurma hatası: {e}")

    def _install_model(self):
        """Install selected model"""
        model_name = self._model_combo.currentData()

        self._install_progress.show()
        self._install_progress.setValue(0)
        self._install_status.show()
        self._install_btn.setEnabled(False)
        self._cancel_btn.show()

        self._installer = OllamaInstallerWorker(model_name)
        self._installer.progress.connect(self._on_install_progress)
        self._installer.finished.connect(self._on_install_finished)
        self._installer.start()

    def _on_install_progress(self, value: int, status: str):
        """Handle installation progress"""
        self._install_progress.setValue(value)
        self._install_status.setText(status)

    def _on_install_finished(self, success: bool, message: str):
        """Handle installation completion"""
        self._install_progress.hide()
        self._install_status.hide()
        self._install_btn.setEnabled(True)
        self._cancel_btn.hide()

        if success:
            self._install_status.setText(f" {message}")
            self._install_status.setStyleSheet("color: #10b981; font-size: 12px;")
            self._install_status.show()
            QMessageBox.information(self, "Başarılı", message)
        else:
            self._install_status.setText(f" {message}")
            self._install_status.setStyleSheet("color: #ef4444; font-size: 12px;")
            self._install_status.show()
            QMessageBox.warning(self, "Hata", message)

    def _cancel_installation(self):
        """Cancel ongoing installation"""
        if self._installer:
            self._installer.cancel()
            self._install_progress.hide()
            self._install_status.hide()
            self._install_btn.setEnabled(True)
            self._cancel_btn.hide()

    def _delete_model(self, model_name: str):
        """Delete a model"""
        reply = QMessageBox.question(
            self, "Onay",
            f"'{model_name}' modelini silmek istediğinizden emin misiniz?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            try:
                subprocess.run(["ollama", "rm", model_name], capture_output=True)
                QMessageBox.information(self, "Başarılı", f" {model_name} silindi")
                self._refresh_status()
            except Exception as e:
                QMessageBox.warning(self, "Hata", f" Silme hatası: {e}")

    def closeEvent(self, event):
        """Clean up on close"""
        if self._status_checker:
            self._status_checker.stop()
            self._status_checker.wait()
        event.accept()
