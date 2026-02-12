"""Main Window - PyQt6 Desktop Application"""

import sys
import io
import os
from pathlib import Path
from typing import Any

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.logger import get_logger

logger = get_logger("ui.main_window")


def check_pyqt6() -> bool:
    """Check if PyQt6 is available"""
    try:
        from PyQt6.QtWidgets import QApplication
        return True
    except ImportError:
        return False


class MainWindow:
    """Main desktop window for the bot"""

    def __init__(self, settings=None, qr_generator=None, bot_username=None):
        self.settings = settings
        self.qr_generator = qr_generator
        self.bot_username = bot_username
        self._app = None
        self._window = None
        self._qr_timer = None
        self._remaining_seconds = 300

    def _ensure_pyqt6(self):
        """Ensure PyQt6 is available"""
        if not check_pyqt6():
            raise ImportError(
                "PyQt6 kurulu değil. 'pip install PyQt6' çalıştırın."
            )

    def create_window(self):
        """Create the main application window"""
        self._ensure_pyqt6()

        from PyQt6.QtWidgets import (
            QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
            QLabel, QPushButton, QTextEdit, QTabWidget, QGroupBox,
            QLineEdit, QComboBox, QCheckBox, QSpinBox, QGridLayout, QFormLayout
        )
        from PyQt6.QtCore import Qt, QTimer
        from PyQt6.QtGui import QFont, QPixmap, QDesktopServices
        from PyQt6.QtCore import QUrl

        # Create application
        self._app = QApplication(sys.argv)
        self._app.setApplicationName("CDACS Bot")

        # Create main window
        self._window = QMainWindow()
        self._window.setWindowTitle("CDACS Bot - Bilgisayar Asistanı")
        self._window.setMinimumSize(800, 700)

        # Central widget
        central = QWidget()
        self._window.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # Create tabs
        tabs = QTabWidget()
        layout.addWidget(tabs)

        # Tab 1: Connection
        connection_tab = self._create_connection_tab()
        tabs.addTab(connection_tab, "🔗 Bağlantı")

        # Tab 2: Chat History
        history_tab = self._create_history_tab()
        tabs.addTab(history_tab, " Geçmiş")

        # Tab 3: Settings
        settings_tab = self._create_settings_tab()
        tabs.addTab(settings_tab, " Ayarlar")

        # Tab 4: Status
        status_tab = self._create_status_tab()
        tabs.addTab(status_tab, " Durum")

        # Generate initial QR code
        self._generate_and_display_qr()

        # Start timer for countdown
        self._qr_timer = QTimer()
        self._qr_timer.timeout.connect(self._update_timer)
        self._qr_timer.start(1000)  # Update every second

        return self._window

    def _create_connection_tab(self):
        """Create the connection/QR tab"""
        from PyQt6.QtWidgets import (
            QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QGroupBox
        )
        from PyQt6.QtCore import Qt
        from PyQt6.QtGui import QPixmap, QFont, QDesktopServices
        from PyQt6.QtCore import QUrl

        tab = QWidget()
        layout = QVBoxLayout(tab)

        # QR Code section
        qr_group = QGroupBox("Telegram Bağlantısı")
        qr_layout = QVBoxLayout(qr_group)

        # Instructions
        instructions = QLabel(
            "Telegram ile bağlanmak için:\n"
            "1. Aşağıdaki QR kodu telefonunuzla tarayın\n"
            "2. Veya bot linkine tıklayın\n"
            "3. Telegram'da /start komutunu gönderin"
        )
        instructions.setWordWrap(True)
        font = QFont()
        font.setPointSize(13)
        instructions.setFont(font)
        qr_layout.addWidget(instructions)

        # QR code display
        self._qr_label = QLabel()
        self._qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._qr_label.setMinimumSize(280, 280)
        self._qr_label.setMaximumSize(300, 300)
        self._qr_label.setStyleSheet("""
            background-color: white;
            border: 2px solid #4CAF50;
            border-radius: 10px;
            padding: 10px;
        """)
        qr_layout.addWidget(self._qr_label, alignment=Qt.AlignmentFlag.AlignCenter)

        # Bot link
        self._link_label = QLabel()
        self._link_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._link_label.setOpenExternalLinks(True)
        self._link_label.setStyleSheet("color: #2196F3; font-size: 14px;")
        qr_layout.addWidget(self._link_label)

        # Button row
        btn_layout = QHBoxLayout()

        # Regenerate button
        regen_btn = QPushButton(" Yeni QR Oluştur")
        regen_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                padding: 10px 20px;
                border: none;
                border-radius: 5px;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        regen_btn.clicked.connect(self._regenerate_qr)
        btn_layout.addWidget(regen_btn)

        # Open in Telegram button
        open_btn = QPushButton(" Telegram'da Aç")
        open_btn.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                padding: 10px 20px;
                border: none;
                border-radius: 5px;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #1976D2;
            }
        """)
        open_btn.clicked.connect(self._open_in_telegram)
        btn_layout.addWidget(open_btn)

        qr_layout.addLayout(btn_layout)

        # Timer label
        self._timer_label = QLabel("⏱️ QR Kod geçerlilik: 5:00")
        self._timer_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._timer_label.setStyleSheet("font-size: 13px; color: #666;")
        qr_layout.addWidget(self._timer_label)

        layout.addWidget(qr_group)

        # Connection status
        status_group = QGroupBox("Bağlantı Durumu")
        status_layout = QVBoxLayout(status_group)

        self._status_label = QLabel("⚪ Telegram bot çalışıyor, bağlantı bekleniyor...")
        self._status_label.setStyleSheet("font-size: 14px; padding: 10px;")
        status_layout.addWidget(self._status_label)

        # Bot info
        self._bot_info_label = QLabel()
        self._bot_info_label.setStyleSheet("font-size: 12px; color: #666; padding: 5px;")
        status_layout.addWidget(self._bot_info_label)

        layout.addWidget(status_group)
        layout.addStretch()

        return tab

    def _generate_and_display_qr(self):
        """Generate and display QR code"""
        from PyQt6.QtGui import QPixmap, QImage
        from PyQt6.QtCore import Qt

        try:
            # Get bot username from settings or use default
            bot_username = self.bot_username
            if not bot_username and self.settings:
                bot_username = self.settings.get("bot_username", "")

            if not bot_username:
                # Try to read from .env
                try:
                    from config.settings import TELEGRAM_TOKEN
                    if TELEGRAM_TOKEN:
                        # We can't get username from token directly
                        # User needs to set it in settings
                        bot_username = self.settings.get("bot_username", "") if self.settings else ""
                except:
                    pass

            # Generate QR code
            import qrcode
            from PIL import Image

            # Create URL - if no bot username, use a placeholder message
            if bot_username:
                url = f"https://t.me/{bot_username}"
                self._current_url = url
            else:
                # Generate QR for manual entry
                url = "https://t.me/"
                self._current_url = url

            # Create QR code
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_L,
                box_size=8,
                border=2,
            )
            qr.add_data(url)
            qr.make(fit=True)

            # Create image with green color
            img = qr.make_image(fill_color="#1a1a1a", back_color="white")

            # Convert PIL image to QPixmap
            buffer = io.BytesIO()
            img.save(buffer, format="PNG")
            buffer.seek(0)

            qimage = QImage()
            qimage.loadFromData(buffer.getvalue())
            pixmap = QPixmap.fromImage(qimage)

            # Scale to fit
            scaled_pixmap = pixmap.scaled(
                260, 260,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )

            self._qr_label.setPixmap(scaled_pixmap)

            # Update link label
            if bot_username:
                self._link_label.setText(f'<a href="{url}">{url}</a>')
                self._bot_info_label.setText(f"Bot: @{bot_username}")
            else:
                self._link_label.setText(" Bot kullanıcı adı ayarlanmamış - Ayarlar sekmesinden girin")
                self._bot_info_label.setText("Ayarlar > Bot Kullanıcı Adı kısmını doldurun")

            # Reset timer
            self._remaining_seconds = 300

            logger.info(f"QR code generated for: {url}")

        except ImportError as e:
            self._qr_label.setText(f"QR oluşturulamadı:\n{e}\n\npip install qrcode pillow")
            logger.error(f"QR generation import error: {e}")
        except Exception as e:
            self._qr_label.setText(f"Hata: {e}")
            logger.error(f"QR generation error: {e}")

    def _regenerate_qr(self):
        """Regenerate QR code"""
        logger.info("Regenerating QR code")
        self._generate_and_display_qr()
        self._status_label.setText(" Yeni QR kod oluşturuldu")

    def _open_in_telegram(self):
        """Open bot link in Telegram"""
        from PyQt6.QtGui import QDesktopServices
        from PyQt6.QtCore import QUrl

        if hasattr(self, '_current_url') and self._current_url:
            QDesktopServices.openUrl(QUrl(self._current_url))
        else:
            self._status_label.setText(" Bot linki oluşturulamadı")

    def _update_timer(self):
        """Update countdown timer"""
        if self._remaining_seconds > 0:
            self._remaining_seconds -= 1
            minutes = self._remaining_seconds // 60
            seconds = self._remaining_seconds % 60
            self._timer_label.setText(f"⏱️ QR Kod geçerlilik: {minutes}:{seconds:02d}")

            if self._remaining_seconds <= 60:
                self._timer_label.setStyleSheet("font-size: 13px; color: #f44336;")
            elif self._remaining_seconds <= 120:
                self._timer_label.setStyleSheet("font-size: 13px; color: #ff9800;")
            else:
                self._timer_label.setStyleSheet("font-size: 13px; color: #666;")
        else:
            self._timer_label.setText(" QR kod süresi doldu - Yeni QR oluşturun")
            self._timer_label.setStyleSheet("font-size: 13px; color: #f44336;")

    def _create_history_tab(self):
        """Create the chat history tab"""
        from PyQt6.QtWidgets import (
            QWidget, QVBoxLayout, QTextEdit, QPushButton, QHBoxLayout
        )

        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Chat history display
        self._history_display = QTextEdit()
        self._history_display.setReadOnly(True)
        self._history_display.setPlaceholderText("Sohbet geçmişi burada görünecek...\n\nTelegram'dan gönderilen komutlar ve yanıtlar burada listelenecek.")
        self._history_display.setStyleSheet("""
            QTextEdit {
                font-size: 13px;
                padding: 10px;
                border: 1px solid #ccc;
                border-radius: 5px;
            }
        """)
        layout.addWidget(self._history_display)

        # Control buttons
        btn_layout = QHBoxLayout()

        clear_btn = QPushButton("🗑️ Temizle")
        clear_btn.clicked.connect(self._clear_history)
        btn_layout.addWidget(clear_btn)

        export_btn = QPushButton("📤 Dışa Aktar")
        export_btn.clicked.connect(self._export_history)
        btn_layout.addWidget(export_btn)

        layout.addLayout(btn_layout)

        return tab

    def _create_settings_tab(self):
        """Create the comprehensive settings tab"""
        from PyQt6.QtWidgets import (
            QWidget, QVBoxLayout, QFormLayout, QGroupBox, QHBoxLayout,
            QLineEdit, QComboBox, QCheckBox, QSpinBox, QPushButton, QLabel,
            QTextEdit, QListWidget, QListWidgetItem, QSplitter, QScrollArea,
            QFrame, QTabWidget
        )
        from PyQt6.QtCore import Qt

        tab = QWidget()
        main_layout = QVBoxLayout(tab)

        # Create scroll area for better navigation
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        scroll_widget = QWidget()
        layout = QVBoxLayout(scroll_widget)

        # Settings tabs for organization
        settings_tabs = QTabWidget()
        layout.addWidget(settings_tabs)

        # Tab 1: Bot & Connection
        bot_tab = self._create_bot_settings_tab()
        settings_tabs.addTab(bot_tab, " Bot")

        # Tab 2: AI & LLM
        ai_tab = self._create_ai_settings_tab()
        settings_tabs.addTab(ai_tab, " AI")

        # Tab 3: Security & Permissions
        security_tab = self._create_security_settings_tab()
        settings_tabs.addTab(security_tab, " Güvenlik")

        # Tab 4: Performance & System
        perf_tab = self._create_performance_settings_tab()
        settings_tabs.addTab(perf_tab, "⚡ Performans")

        # Tab 5: Interface & Appearance
        ui_tab = self._create_ui_settings_tab()
        settings_tabs.addTab(ui_tab, " Arayüz")

        scroll.setWidget(scroll_widget)
        main_layout.addWidget(scroll)

        # Bottom buttons
        btn_layout = QHBoxLayout()

        save_btn = QPushButton(" Kaydet")
        save_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                padding: 12px 24px;
                border: none;
                border-radius: 5px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        save_btn.clicked.connect(self._save_all_settings)
        btn_layout.addWidget(save_btn)

        reset_btn = QPushButton(" Varsayılana Dön")
        reset_btn.setStyleSheet("""
            QPushButton {
                background-color: #ff9800;
                color: white;
                padding: 12px 24px;
                border: none;
                border-radius: 5px;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #f57c00;
            }
        """)
        reset_btn.clicked.connect(self._reset_settings)
        btn_layout.addWidget(reset_btn)

        export_btn = QPushButton("📤 Dışa Aktar")
        export_btn.clicked.connect(self._export_settings)
        btn_layout.addWidget(export_btn)

        import_btn = QPushButton("📥 İçe Aktar")
        import_btn.clicked.connect(self._import_settings)
        btn_layout.addWidget(import_btn)

        main_layout.addLayout(btn_layout)

        return tab

    def _create_status_tab(self):
        """Create the status/monitoring tab"""
        from PyQt6.QtWidgets import (
            QWidget, QVBoxLayout, QGroupBox, QLabel, QGridLayout, QPushButton
        )

        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Bot status
        bot_group = QGroupBox("Bot Durumu")
        bot_layout = QGridLayout(bot_group)

        bot_layout.addWidget(QLabel("Durum:"), 0, 0)
        self._bot_status_label = QLabel("🟢 Çalışıyor")
        self._bot_status_label.setStyleSheet("font-weight: bold;")
        bot_layout.addWidget(self._bot_status_label, 0, 1)

        bot_layout.addWidget(QLabel("LLM Model:"), 1, 0)
        self._model_label = QLabel("mistral")
        bot_layout.addWidget(self._model_label, 1, 1)

        bot_layout.addWidget(QLabel("Aktif Görevler:"), 2, 0)
        self._active_tasks_label = QLabel("0")
        bot_layout.addWidget(self._active_tasks_label, 2, 1)

        bot_layout.addWidget(QLabel("Toplam Komut:"), 3, 0)
        self._total_commands_label = QLabel("0")
        bot_layout.addWidget(self._total_commands_label, 3, 1)

        layout.addWidget(bot_group)

        # Cache stats
        cache_group = QGroupBox("Önbellek İstatistikleri")
        cache_layout = QGridLayout(cache_group)

        cache_layout.addWidget(QLabel("Önbellekteki Öğe:"), 0, 0)
        self._cache_size_label = QLabel("0")
        cache_layout.addWidget(self._cache_size_label, 0, 1)

        cache_layout.addWidget(QLabel("İsabet Oranı:"), 1, 0)
        self._cache_hit_label = QLabel("0%")
        cache_layout.addWidget(self._cache_hit_label, 1, 1)

        layout.addWidget(cache_group)

        # System info
        sys_group = QGroupBox("Sistem Bilgisi")
        sys_layout = QGridLayout(sys_group)

        import platform
        sys_layout.addWidget(QLabel("İşletim Sistemi:"), 0, 0)
        sys_layout.addWidget(QLabel(f"macOS {platform.mac_ver()[0]}"), 0, 1)

        sys_layout.addWidget(QLabel("Python:"), 1, 0)
        sys_layout.addWidget(QLabel(platform.python_version()), 1, 1)

        layout.addWidget(sys_group)

        # Refresh button
        refresh_btn = QPushButton(" Yenile")
        refresh_btn.clicked.connect(self._refresh_status)
        layout.addWidget(refresh_btn)

        layout.addStretch()

        return tab

    def _clear_history(self):
        """Clear chat history"""
        if self._history_display:
            self._history_display.clear()

    def _export_history(self):
        """Export chat history"""
        from PyQt6.QtWidgets import QFileDialog
        filename, _ = QFileDialog.getSaveFileName(
            self._window,
            "Geçmişi Kaydet",
            "chat_history.txt",
            "Text Files (*.txt)"
        )
        if filename:
            with open(filename, "w", encoding="utf-8") as f:
                f.write(self._history_display.toPlainText())
            logger.info(f"History exported to {filename}")

    def _save_settings(self):
        """Save settings"""
        if self.settings:
            self.settings.set("bot_name", self._bot_name_input.text())
            self.settings.set("bot_username", self._bot_username_input.text())
            self.settings.set("cache_enabled", self._cache_check.isChecked())
            self.settings.set("cache_ttl", self._cache_ttl_spin.value())

            # Update bot username for QR
            self.bot_username = self._bot_username_input.text()

        # Show success message
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.information(
            self._window,
            "Ayarlar Kaydedildi",
            "Ayarlarınız başarıyla kaydedildi.\n\nQR kodunu yenilemek için Bağlantı sekmesinde 'Yeni QR Oluştur' butonuna tıklayın."
        )
        logger.info("Settings saved")

    def _refresh_status(self):
        """Refresh status display"""
        logger.info("Refreshing status")
        # This would be connected to actual bot stats

    def update_connection_status(self, connected: bool, user_info: str = ""):
        """Update the connection status display"""
        if connected:
            self._status_label.setText(f"🟢 Bağlı: {user_info}")
            self._status_label.setStyleSheet("font-size: 14px; padding: 10px; color: #4CAF50;")
        else:
            self._status_label.setText("⚪ Bağlantı bekleniyor...")

    # ===== NEW COMPREHENSIVE SETTINGS METHODS =====

    def _create_bot_settings_tab(self):
        """Create bot connection and basic settings tab"""
        from PyQt6.QtWidgets import (
            QWidget, QVBoxLayout, QFormLayout, QGroupBox, QLabel
        )

        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Bot Identity
        identity_group = QGroupBox("Bot Kimliği")
        identity_layout = QFormLayout(identity_group)

        self._bot_name_input = QLineEdit()
        self._bot_name_input.setText(self.settings.get("bot_name", "CDACS Bot") if self.settings else "CDACS Bot")
        identity_layout.addRow("Bot Adı:", self._bot_name_input)

        self._bot_username_input = QLineEdit()
        self._bot_username_input.setText(self.settings.get("bot_username", "") if self.settings else "")
        identity_layout.addRow("Bot Kullanıcı Adı:", self._bot_username_input)

        self._bot_description_input = QTextEdit()
        self._bot_description_input.setMaximumHeight(60)
        self._bot_description_input.setPlainText(self.settings.get("bot_description", "Bilgisayar asistanı botu") if self.settings else "Bilgisayar asistanı botu")
        identity_layout.addRow("Açıklama:", self._bot_description_input)

        layout.addWidget(identity_group)

        # Connection Settings
        conn_group = QGroupBox("Bağlantı Ayarları")
        conn_layout = QFormLayout(conn_group)

        self._auto_start_check = QCheckBox()
        self._auto_start_check.setChecked(self.settings.get("auto_start", False) if self.settings else False)
        conn_layout.addRow("Başlangıçta otomatik başlat:", self._auto_start_check)

        self._menubar_check = QCheckBox()
        self._menubar_check.setChecked(self.settings.get("menubar_enabled", True) if self.settings else True)
        conn_layout.addRow("Menubar simgesi göster:", self._menubar_check)

        self._notifications_check = QCheckBox()
        self._notifications_check.setChecked(self.settings.get("notifications_enabled", True) if self.settings else True)
        conn_layout.addRow("Bildirimler aktif:", self._notifications_check)

        layout.addWidget(conn_group)

        layout.addStretch()
        return tab

    def _create_ai_settings_tab(self):
        """Create AI and LLM settings tab"""
        from PyQt6.QtWidgets import (
            QWidget, QVBoxLayout, QFormLayout, QGroupBox, QDoubleSpinBox
        )

        tab = QWidget()
        layout = QVBoxLayout(tab)

        # LLM Settings
        llm_group = QGroupBox("LLM Yapılandırması")
        llm_layout = QFormLayout(llm_group)

        self._llm_model_combo = QComboBox()
        self._llm_model_combo.addItems(["mistral", "phi3:mini", "tinyllama", "llama2", "codellama"])
        self._llm_model_combo.setCurrentText(self.settings.get("llm_model", "mistral") if self.settings else "mistral")
        llm_layout.addRow("Model:", self._llm_model_combo)

        self._llm_temp_spin = QDoubleSpinBox()
        self._llm_temp_spin.setRange(0.0, 2.0)
        self._llm_temp_spin.setSingleStep(0.1)
        self._llm_temp_spin.setValue(self.settings.get("llm_temperature", 0.1) if self.settings else 0.1)
        llm_layout.addRow("Sıcaklık:", self._llm_temp_spin)

        self._llm_max_tokens_spin = QSpinBox()
        self._llm_max_tokens_spin.setRange(100, 2000)
        self._llm_max_tokens_spin.setValue(self.settings.get("llm_max_tokens", 800) if self.settings else 800)
        llm_layout.addRow("Max Token:", self._llm_max_tokens_spin)

        layout.addWidget(llm_group)

        # Intent Parser Settings
        parser_group = QGroupBox("Intent Parser")
        parser_layout = QFormLayout(parser_group)

        self._intent_parser_check = QCheckBox()
        self._intent_parser_check.setChecked(self.settings.get("intent_parser_enabled", True) if self.settings else True)
        parser_layout.addRow("Intent Parser aktif:", self._intent_parser_check)

        self._fallback_llm_check = QCheckBox()
        self._fallback_llm_check.setChecked(self.settings.get("fallback_to_llm", True) if self.settings else True)
        parser_layout.addRow("LLM fallback aktif:", self._fallback_llm_check)

        layout.addWidget(parser_group)

        layout.addStretch()
        return tab

    def _create_security_settings_tab(self):
        """Create security and permissions settings tab"""
        from PyQt6.QtWidgets import (
            QWidget, QVBoxLayout, QFormLayout, QGroupBox, QListWidget,
            QListWidgetItem, QHBoxLayout, QPushButton
        )

        tab = QWidget()
        layout = QVBoxLayout(tab)

        # User Access
        access_group = QGroupBox("Kullanıcı Erişimi")
        access_layout = QFormLayout(access_group)

        self._allowed_users_input = QTextEdit()
        self._allowed_users_input.setMaximumHeight(80)
        allowed_users = self.settings.get("allowed_user_ids", []) if self.settings else []
        self._allowed_users_input.setPlainText("\n".join(map(str, allowed_users)))
        access_layout.addRow("İzinli Kullanıcı ID'leri:", self._allowed_users_input)

        self._public_access_check = QCheckBox()
        self._public_access_check.setChecked(self.settings.get("public_access", False) if self.settings else False)
        access_layout.addRow("Herkese açık erişim:", self._public_access_check)

        layout.addWidget(access_group)

        # File Permissions
        file_group = QGroupBox("Dosya İzinleri")
        file_layout = QVBoxLayout(file_group)

        # Allowed directories
        file_layout.addWidget(QLabel("İzinli Klasörler:"))
        self._allowed_dirs_list = QListWidget()
        default_dirs = [
            "~/Desktop", "~/Documents", "~/Downloads",
            "~/Pictures", "~/Music", "~/Movies", "~/Projects"
        ]
        allowed_dirs = self.settings.get("allowed_directories", default_dirs) if self.settings else default_dirs
        for dir_path in allowed_dirs:
            item = QListWidgetItem(dir_path)
            self._allowed_dirs_list.addItem(item)

        file_layout.addWidget(self._allowed_dirs_list)

        # Directory buttons
        dir_btn_layout = QHBoxLayout()
        add_dir_btn = QPushButton("➕ Ekle")
        add_dir_btn.clicked.connect(self._add_directory)
        dir_btn_layout.addWidget(add_dir_btn)

        remove_dir_btn = QPushButton("➖ Sil")
        remove_dir_btn.clicked.connect(self._remove_directory)
        dir_btn_layout.addWidget(remove_dir_btn)

        file_layout.addLayout(dir_btn_layout)
        layout.addWidget(file_group)

        # Command Restrictions
        cmd_group = QGroupBox("Komut Kısıtlamaları")
        cmd_layout = QFormLayout(cmd_group)

        self._safe_commands_only_check = QCheckBox()
        self._safe_commands_only_check.setChecked(self.settings.get("safe_commands_only", True) if self.settings else True)
        cmd_layout.addRow("Sadece güvenli komutlar:", self._safe_commands_only_check)

        self._max_file_size_spin = QSpinBox()
        self._max_file_size_spin.setRange(1, 100)
        self._max_file_size_spin.setValue(self.settings.get("max_file_size_mb", 10) if self.settings else 10)
        self._max_file_size_spin.setSuffix(" MB")
        cmd_layout.addRow("Max dosya boyutu:", self._max_file_size_spin)

        layout.addWidget(cmd_group)

        layout.addStretch()
        return tab

    def _create_performance_settings_tab(self):
        """Create performance and system settings tab"""
        from PyQt6.QtWidgets import (
            QWidget, QVBoxLayout, QFormLayout, QGroupBox
        )

        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Caching
        cache_group = QGroupBox("Önbellekleme")
        cache_layout = QFormLayout(cache_group)

        self._cache_enabled_check = QCheckBox()
        self._cache_enabled_check.setChecked(self.settings.get("cache_enabled", True) if self.settings else True)
        cache_layout.addRow("Önbellek aktif:", self._cache_enabled_check)

        self._cache_ttl_spin = QSpinBox()
        self._cache_ttl_spin.setRange(60, 3600)
        self._cache_ttl_spin.setValue(self.settings.get("cache_ttl", 300) if self.settings else 300)
        self._cache_ttl_spin.setSuffix(" saniye")
        cache_layout.addRow("Önbellek süresi:", self._cache_ttl_spin)

        layout.addWidget(cache_group)

        # Task Management
        task_group = QGroupBox("Görev Yönetimi")
        task_layout = QFormLayout(task_group)

        self._task_timeout_spin = QSpinBox()
        self._task_timeout_spin.setRange(10, 300)
        self._task_timeout_spin.setValue(self.settings.get("task_timeout", 60) if self.settings else 60)
        self._task_timeout_spin.setSuffix(" saniye")
        task_layout.addRow("Görev zaman aşımı:", self._task_timeout_spin)

        self._max_concurrent_tasks_spin = QSpinBox()
        self._max_concurrent_tasks_spin.setRange(1, 10)
        self._max_concurrent_tasks_spin.setValue(self.settings.get("max_concurrent_tasks", 3) if self.settings else 3)
        task_layout.addRow("Max eş zamanlı görev:", self._max_concurrent_tasks_spin)

        layout.addWidget(task_group)

        # Circuit Breaker
        cb_group = QGroupBox("Circuit Breaker")
        cb_layout = QFormLayout(cb_group)

        self._cb_threshold_spin = QSpinBox()
        self._cb_threshold_spin.setRange(1, 20)
        self._cb_threshold_spin.setValue(self.settings.get("circuit_breaker_threshold", 5) if self.settings else 5)
        cb_layout.addRow("Hata eşiği:", self._cb_threshold_spin)

        self._cb_recovery_spin = QSpinBox()
        self._cb_recovery_spin.setRange(10, 300)
        self._cb_recovery_spin.setValue(self.settings.get("circuit_breaker_recovery", 30) if self.settings else 30)
        self._cb_recovery_spin.setSuffix(" saniye")
        cb_layout.addRow("Kurtarma süresi:", self._cb_recovery_spin)

        layout.addWidget(cb_group)

        layout.addStretch()
        return tab

    def _create_ui_settings_tab(self):
        """Create UI and appearance settings tab"""
        from PyQt6.QtWidgets import (
            QWidget, QVBoxLayout, QFormLayout, QGroupBox
        )

        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Appearance
        appearance_group = QGroupBox("Görünüm")
        appearance_layout = QFormLayout(appearance_group)

        self._ui_language_combo = QComboBox()
        self._ui_language_combo.addItems(["Türkçe", "English"])
        self._ui_language_combo.setCurrentText(self.settings.get("ui_language", "Türkçe") if self.settings else "Türkçe")
        appearance_layout.addRow("Arayüz Dili:", self._ui_language_combo)

        self._ui_theme_combo = QComboBox()
        self._ui_theme_combo.addItems(["Sistem", "Açık", "Koyu"])
        self._ui_theme_combo.setCurrentText(self.settings.get("ui_theme", "Sistem") if self.settings else "Sistem")
        appearance_layout.addRow("Tema:", self._ui_theme_combo)

        self._ui_font_size_spin = QSpinBox()
        self._ui_font_size_spin.setRange(8, 24)
        self._ui_font_size_spin.setValue(self.settings.get("ui_font_size", 12) if self.settings else 12)
        appearance_layout.addRow("Yazı Boyutu:", self._ui_font_size_spin)

        layout.addWidget(appearance_group)

        # Window Settings
        window_group = QGroupBox("Pencere Ayarları")
        window_layout = QFormLayout(window_group)

        self._window_always_on_top_check = QCheckBox()
        self._window_always_on_top_check.setChecked(self.settings.get("window_always_on_top", False) if self.settings else False)
        window_layout.addRow("Her zaman üstte:", self._window_always_on_top_check)

        self._window_minimize_to_tray_check = QCheckBox()
        self._window_minimize_to_tray_check.setChecked(self.settings.get("minimize_to_tray", True) if self.settings else True)
        window_layout.addRow("Simge durumuna küçült:", self._window_minimize_to_tray_check)

        layout.addWidget(window_group)

        # Notification Settings
        notify_group = QGroupBox("Bildirim Ayarları")
        notify_layout = QFormLayout(notify_group)

        self._notify_on_connect_check = QCheckBox()
        self._notify_on_connect_check.setChecked(self.settings.get("notify_on_connect", True) if self.settings else True)
        notify_layout.addRow("Bağlantıda bildir:", self._notify_on_connect_check)

        self._notify_on_error_check = QCheckBox()
        self._notify_on_error_check.setChecked(self.settings.get("notify_on_error", True) if self.settings else True)
        notify_layout.addRow("Hatalarda bildir:", self._notify_on_error_check)

        self._notify_on_task_check = QCheckBox()
        self._notify_on_task_check.setChecked(self.settings.get("notify_on_task", False) if self.settings else False)
        notify_layout.addRow("Görevlerde bildir:", self._notify_on_task_check)

        layout.addWidget(notify_group)

        layout.addStretch()
        return tab

    # ===== SETTINGS ACTION METHODS =====

    def _save_all_settings(self):
        """Save all settings from all tabs"""
        if not self.settings:
            return

        # Bot settings
        self.settings.set("bot_name", self._bot_name_input.text())
        self.settings.set("bot_username", self._bot_username_input.text())
        self.settings.set("bot_description", self._bot_description_input.toPlainText())

        self.settings.set("auto_start", self._auto_start_check.isChecked())
        self.settings.set("menubar_enabled", self._menubar_check.isChecked())
        self.settings.set("notifications_enabled", self._notifications_check.isChecked())

        # AI settings
        self.settings.set("llm_model", self._llm_model_combo.currentText())
        self.settings.set("llm_temperature", self._llm_temp_spin.value())
        self.settings.set("llm_max_tokens", self._llm_max_tokens_spin.value())
        self.settings.set("intent_parser_enabled", self._intent_parser_check.isChecked())
        self.settings.set("fallback_to_llm", self._fallback_llm_check.isChecked())

        # Security settings
        allowed_users_text = self._allowed_users_input.toPlainText().strip()
        allowed_users = [int(uid.strip()) for uid in allowed_users_text.split('\n') if uid.strip().isdigit()]
        self.settings.set("allowed_user_ids", allowed_users)
        self.settings.set("public_access", self._public_access_check.isChecked())

        # Get allowed directories from list
        allowed_dirs = []
        for i in range(self._allowed_dirs_list.count()):
            allowed_dirs.append(self._allowed_dirs_list.item(i).text())
        self.settings.set("allowed_directories", allowed_dirs)

        self.settings.set("safe_commands_only", self._safe_commands_only_check.isChecked())
        self.settings.set("max_file_size_mb", self._max_file_size_spin.value())

        # Performance settings
        self.settings.set("cache_enabled", self._cache_enabled_check.isChecked())
        self.settings.set("cache_ttl", self._cache_ttl_spin.value())
        self.settings.set("task_timeout", self._task_timeout_spin.value())
        self.settings.set("max_concurrent_tasks", self._max_concurrent_tasks_spin.value())
        self.settings.set("circuit_breaker_threshold", self._cb_threshold_spin.value())
        self.settings.set("circuit_breaker_recovery", self._cb_recovery_spin.value())

        # UI settings
        self.settings.set("ui_language", self._ui_language_combo.currentText())
        self.settings.set("ui_theme", self._ui_theme_combo.currentText())
        self.settings.set("ui_font_size", self._ui_font_size_spin.value())
        self.settings.set("window_always_on_top", self._window_always_on_top_check.isChecked())
        self.settings.set("minimize_to_tray", self._window_minimize_to_tray_check.isChecked())
        self.settings.set("notify_on_connect", self._notify_on_connect_check.isChecked())
        self.settings.set("notify_on_error", self._notify_on_error_check.isChecked())
        self.settings.set("notify_on_task", self._notify_on_task_check.isChecked())

        # Save to file
        self.settings.save()

        # Show success message
        from PyQt6.QtWidgets import QMessageBox
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Icon.Information)
        msg.setWindowTitle("Ayarlar Kaydedildi")
        msg.setText("Tüm ayarlar başarıyla kaydedildi!")
        msg.exec()

    def _reset_settings(self):
        """Reset all settings to defaults"""
        from PyQt6.QtWidgets import QMessageBox
        reply = QMessageBox.question(
            self._window, "Ayarları Sıfırla",
            "Tüm ayarları varsayılan değerlere döndürmek istediğinizden emin misiniz?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            if self.settings:
                self.settings.reset_to_defaults()
                self._load_settings_into_ui()
                self.settings.save()

            msg = QMessageBox()
            msg.setIcon(QMessageBox.Icon.Information)
            msg.setWindowTitle("Ayarlar Sıfırlandı")
            msg.setText("Ayarlar varsayılan değerlere döndürüldü.")
            msg.exec()

    def _export_settings(self):
        """Export settings to file"""
        from PyQt6.QtWidgets import QFileDialog
        filename, _ = QFileDialog.getSaveFileName(
            self._window, "Ayarları Dışa Aktar", "", "JSON Files (*.json)"
        )
        if filename and self.settings:
            self.settings.export_to_file(filename)

    def _import_settings(self):
        """Import settings from file"""
        from PyQt6.QtWidgets import QFileDialog
        filename, _ = QFileDialog.getOpenFileName(
            self._window, "Ayarları İçe Aktar", "", "JSON Files (*.json)"
        )
        if filename and self.settings:
            self.settings.import_from_file(filename)
            self._load_settings_into_ui()

    def _add_directory(self):
        """Add a new allowed directory"""
        from PyQt6.QtWidgets import QFileDialog
        directory = QFileDialog.getExistingDirectory(self._window, "Klasör Seç")
        if directory:
            from PyQt6.QtWidgets import QListWidgetItem
            item = QListWidgetItem(directory)
            self._allowed_dirs_list.addItem(item)

    def _remove_directory(self):
        """Remove selected directory"""
        current_row = self._allowed_dirs_list.currentRow()
        if current_row >= 0:
            self._allowed_dirs_list.takeItem(current_row)

    def _load_settings_into_ui(self):
        """Load current settings into UI elements"""
        if not self.settings:
            return

        # This method would load all settings back into the UI
        # Implementation would mirror _save_all_settings but in reverse
        pass

    def add_to_history(self, user_message: str, bot_response: str):
        """Add a message exchange to chat history"""
        if self._history_display:
            self._history_display.append(f" Kullanıcı: {user_message}")
            self._history_display.append(f" Bot: {bot_response}")
            self._history_display.append("─" * 40)

    def run(self):
        """Run the application"""
        if self._window is None:
            self.create_window()
        self._window.show()
        return self._app.exec()
