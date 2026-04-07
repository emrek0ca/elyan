"""
Clean Chat Widget - Professional chat interface without emojis
Minimal, clean and modern design
"""

import asyncio
import inspect
import json
import os
import signal
import subprocess
import tempfile
from datetime import datetime
from typing import Optional, List, Dict, Any, Callable
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QLabel,
    QPushButton, QLineEdit, QTextEdit, QFrame, QSizePolicy,
    QApplication, QFileDialog, QMenu, QToolButton
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QThread, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QFont, QPixmap, QColor, QPalette, QAction, QIcon

from utils.logger import get_logger
from core.operator_status import get_operator_status_sync

logger = get_logger("clean_chat_widget")


class CleanMessageBubble(QFrame):
    """Clean message bubble without emojis"""

    def __init__(self, message: str, is_user: bool, timestamp: str = None, parent=None):
        super().__init__(parent)
        self.is_user = is_user
        self.message = message
        self.timestamp = timestamp or datetime.now().strftime("%H:%M")

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(4)

        # Message container
        container = QHBoxLayout()
        container.setSpacing(12)

        # Avatar - simple circle with initial
        avatar = QLabel("S" if not self.is_user else "K")  # S=Sistem, K=Kullanıcı
        avatar.setFixedSize(32, 32)
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar.setFont(QFont(".AppleSystemUIFont", 12, QFont.Weight.Medium))

        if self.is_user:
            avatar.setStyleSheet("""
                QLabel {
                    background-color: #4C82FF;
                    color: white;
                    border-radius: 16px;
                }
            """)
        else:
            avatar.setStyleSheet("""
                QLabel {
                    background-color: #E5E5EA;
                    color: #252F33;
                    border-radius: 16px;
                    border: none;
                }
            """)

        # Message bubble
        bubble = QFrame()
        bubble.setMaximumWidth(600)
        bubble.setMinimumWidth(50)
        bubble.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        bubble_layout = QVBoxLayout(bubble)
        bubble_layout.setContentsMargins(14, 10, 14, 10)
        bubble_layout.setSpacing(6)

        # Sender label
        sender = QLabel("YOU" if self.is_user else "ELYAN")
        sender.setFont(QFont(".AppleSystemUIFont", 10, QFont.Weight.Bold))
        sender.setStyleSheet(f"color: {'#4C82FF' if self.is_user else '#8A93A3'}; border: none; letter-spacing: 0.5px;")
        bubble_layout.addWidget(sender)

        # Message text
        text_label = QLabel(self.message)
        text_label.setWordWrap(True)
        text_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        text_label.setFont(QFont(".AppleSystemUIFont", 13))
        text_label.setTextFormat(Qt.TextFormat.MarkdownText)
        text_label.setStyleSheet(f"""
            color: {'#FFFFFF' if self.is_user else '#111318'};
            line-height: 1.4;
            padding: 2px;
            border: none;
        """)
        bubble_layout.addWidget(text_label)

        # Timestamp
        time_label = QLabel(self.timestamp)
        time_label.setFont(QFont(".AppleSystemUIFont", 9))
        time_label.setStyleSheet(f"color: {'rgba(255,255,255,0.72)' if self.is_user else '#8A93A3'};")
        time_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        bubble_layout.addWidget(time_label)

        # Style bubble
        if self.is_user:
            bubble.setStyleSheet("""
                QFrame {
                    background-color: rgba(76, 130, 255, 0.94);
                    border-radius: 18px;
                    border-bottom-right-radius: 4px;
                    border: none;
                }
            """)
            container.addStretch()
            container.addWidget(bubble)
        else:
            bubble.setStyleSheet("""
                QFrame {
                    background-color: rgba(255, 255, 255, 0.76);
                    border: 1px solid rgba(255, 255, 255, 0.58);
                    border-radius: 18px;
                    border-bottom-left-radius: 4px;
                }
            """)
            container.addWidget(bubble)
            container.addStretch()

        layout.addLayout(container)
        self.setStyleSheet("background: transparent;")


class CleanTypingIndicator(QFrame):
    """Clean typing indicator"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
        self._animation_index = 0

        self._timer = QTimer()
        self._timer.timeout.connect(self._animate)

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(12)

        # Avatar
        avatar = QLabel("E")
        avatar.setFixedSize(32, 32)
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar.setFont(QFont(".AppleSystemUIFont", 12, QFont.Weight.Bold))
        avatar.setStyleSheet("""
            QLabel {
                background-color: #EAF2FF;
                color: #4C82FF;
                border-radius: 16px;
            }
        """)
        layout.addWidget(avatar)

        # Typing indicator
        indicator_frame = QFrame()
        indicator_frame.setStyleSheet("""
            QFrame {
                background-color: rgba(255, 255, 255, 0.74);
                border: 1px solid rgba(255,255,255,0.54);
                border-radius: 18px;
                padding: 8px 16px;
            }
        """)
        indicator_layout = QHBoxLayout(indicator_frame)
        indicator_layout.setContentsMargins(14, 10, 14, 10)
        indicator_layout.setSpacing(4)

        self._dots = []
        for _ in range(3):
            dot = QLabel("•")
            dot.setFont(QFont(".AppleSystemUIFont", 16))
            dot.setStyleSheet("color: #64748B;")
            indicator_layout.addWidget(dot)
            self._dots.append(dot)

        layout.addWidget(indicator_frame)
        layout.addStretch()

        self.setStyleSheet("background: transparent;")

    def _animate(self):
        for i, dot in enumerate(self._dots):
            if i == self._animation_index:
                dot.setStyleSheet("color: #8E8E93;")
            else:
                dot.setStyleSheet("color: #475569;")

        self._animation_index = (self._animation_index + 1) % 3

    def start(self):
        self._timer.start(300)
        self.show()

    def stop(self):
        self._timer.stop()
        self.hide()


class CleanProcessingWorker(QThread):
    finished = pyqtSignal(str)
    error = pyqtSignal(str)
    status = pyqtSignal(str)

    def __init__(self, process_func: Callable, message: str):
        super().__init__()
        self.process_func = process_func
        self.message = message

    def run(self):
        loop = None
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            async def notify_bridger(data):
                # Emit status if it's a string or specific type
                if isinstance(data, str):
                    self.status.emit(data)
                elif isinstance(data, dict):
                    msg = data.get("message") or data.get("status")
                    if msg: self.status.emit(msg)

            # Call process with optional notify support for callback compatibility.
            signature = inspect.signature(self.process_func)
            if "notify" in signature.parameters:
                coroutine = self.process_func(self.message, notify=notify_bridger)
            else:
                coroutine = self.process_func(self.message)

            result = loop.run_until_complete(coroutine)
            if not isinstance(result, str):
                result = json.dumps(result, ensure_ascii=False, indent=2, default=str)
            self.finished.emit(result)
        except Exception as e:
            logger.error(f"Processing error: {e}")
            self.error.emit(str(e))
        finally:
            if loop is not None:
                loop.close()


class VoiceTranscriptionWorker(QThread):
    """Background worker for local speech-to-text transcription."""
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, audio_file: str, language: str = "tr"):
        super().__init__()
        self.audio_file = audio_file
        self.language = language

    def run(self):
        loop = None
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            from tools.multimodal_tools import transcribe_audio_file
            result = loop.run_until_complete(
                transcribe_audio_file(self.audio_file, language=self.language)
            )
            if isinstance(result, dict):
                self.finished.emit(result)
            else:
                self.error.emit("Geçersiz ses dönüştürme sonucu.")
        except Exception as e:
            logger.error(f"Voice transcription worker error: {e}")
            self.error.emit(str(e))
        finally:
            if loop is not None:
                loop.close()


class CleanChatWidget(QWidget):
    """Clean, professional chat interface"""

    message_sent = pyqtSignal(str)
    message_received = pyqtSignal(str)

    def __init__(self, process_callback: Callable = None, parent=None):
        super().__init__(parent)
        self.process_callback = process_callback
        self._messages: List[Dict[str, Any]] = []
        self._worker = None
        self._voice_worker = None
        self._speak_worker = None
        self._recording_process: Optional[subprocess.Popen] = None
        self._recording_file: Optional[str] = None
        self._is_recording = False
        self._last_assistant_message = ""
        self._suggestions: List[str] = [
            "Bugün neye odaklanalım?",
            "Bu dosyayı özetle",
            "Web'de araştır",
            "Telefon bağlantısını kontrol et",
        ]
        self._operator_labels: Dict[str, QLabel] = {}

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header = self._create_header()
        layout.addWidget(header)

        self._operator_strip = self._create_operator_strip()
        layout.addWidget(self._operator_strip)

        # Chat area
        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll_area.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: transparent;
            }
            QScrollBar:vertical {
                background-color: transparent;
                width: 6px;
                border-radius: 3px;
            }
            QScrollBar::handle:vertical {
                background-color: rgba(0, 0, 0, 0.2);
                border-radius: 3px;
                min-height: 30px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: rgba(0, 0, 0, 0.3);
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)

        # Messages container
        self._messages_container = QWidget()
        self._messages_container.setStyleSheet("background-color: transparent;")
        self._messages_layout = QVBoxLayout(self._messages_container)
        self._messages_layout.setContentsMargins(16, 16, 16, 16)
        self._messages_layout.setSpacing(10)
        self._messages_layout.addStretch()

        self._scroll_area.setWidget(self._messages_container)
        layout.addWidget(self._scroll_area, 1)

        # Typing indicator
        self._typing_indicator = CleanTypingIndicator()
        self._typing_indicator.hide()
        self._messages_layout.addWidget(self._typing_indicator)

        # Input area
        input_area = self._create_input_area()
        layout.addWidget(input_area)

        # Welcome message
        self._add_bot_message(
            "Buradayım. Dosya, web, vision, telefon bağlantısı ve operator görevlerini aynı akışta yürütebilirim.\n\n"
            "İstersen direkt bir iş ver ya da alttaki hızlı kartlardan başla."
        )
        self._refresh_operator_strip()
        self._operator_timer = QTimer(self)
        self._operator_timer.timeout.connect(self._refresh_operator_strip)
        self._operator_timer.start(8000)

    def _create_header(self) -> QFrame:
        """Create clean header"""
        header = QFrame()
        header.setFixedHeight(56)
        header.setStyleSheet("""
            QFrame {
                background-color: rgba(255, 255, 255, 0.66);
                border-bottom: 1px solid rgba(255,255,255,0.44);
            }
        """)

        layout = QHBoxLayout(header)
        layout.setContentsMargins(16, 0, 16, 0)

        info_layout = QHBoxLayout()
        info_layout.setSpacing(10)

        avatar = QLabel("E")
        avatar.setFixedSize(32, 32)
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar.setFont(QFont(".AppleSystemUIFont", 13, QFont.Weight.Bold))
        avatar.setStyleSheet("""
            QLabel {
                background-color: #4C82FF;
                color: #ffffff;
                border-radius: 16px;
            }
        """)
        info_layout.addWidget(avatar)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(0)

        name_label = QLabel("Chat")
        name_label.setFont(QFont(".AppleSystemUIFont", 15, QFont.Weight.DemiBold))
        name_label.setStyleSheet("color: #111318; border: none; letter-spacing: -0.2px;")
        text_layout.addWidget(name_label)

        self._status_label = QLabel("BOT HAZIR")
        self._status_label.setFont(QFont(".AppleSystemUIFont", 9, QFont.Weight.Bold))
        self._status_label.setStyleSheet("color: #16A34A; border: none; text-transform: uppercase; letter-spacing: 0.8px;")
        text_layout.addWidget(self._status_label)

        info_layout.addLayout(text_layout)
        layout.addLayout(info_layout)

        layout.addStretch()

        more_btn = QToolButton()
        more_btn.setText("More ▾")
        more_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        more_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        more_btn.setFixedHeight(28)
        more_btn.setStyleSheet("""
            QToolButton {
                background: #FFFFFF;
                color: #5D6675;
                border: 1px solid #E8ECF2;
                border-radius: 14px;
                padding: 0 12px;
                font-size: 11px;
                font-weight: 600;
            }
            QToolButton:hover { background: #F7F8FA; color: #111318; }
        """)
        menu = QMenu(more_btn)
        clear_action = menu.addAction("Clear chat")
        clear_action.triggered.connect(lambda checked=False: self.clear_chat())
        export_action = menu.addAction("Export chat")
        export_action.triggered.connect(lambda checked=False: self.export_chat())
        more_btn.setMenu(menu)
        layout.addWidget(more_btn)

        return header

    def _create_operator_strip(self) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet("""
            QFrame {
                background: rgba(255, 255, 255, 0.48);
                border-bottom: 1px solid rgba(255,255,255,0.40);
            }
        """)
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(8)
        title = QLabel("Operator")
        title.setFont(QFont(".AppleSystemUIFont", 11, QFont.Weight.Bold))
        title.setStyleSheet("color: #46556A; letter-spacing: 0.7px;")
        layout.addWidget(title)
        for key, label in (
            ("mobile_dispatch", "Mobile"),
            ("computer_use", "Computer"),
            ("internet_reach", "Internet"),
            ("document_ingest", "Docs"),
            ("speed_runtime", "Speed"),
        ):
            pill = QLabel(f"{label} ...")
            pill.setStyleSheet(self._pill_style("neutral"))
            pill.setMinimumHeight(28)
            pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
            pill.setMargin(6)
            layout.addWidget(pill)
            self._operator_labels[key] = pill
        self._operator_meta = QLabel("Lane unknown")
        self._operator_meta.setStyleSheet("color: #64748B; font-size: 11px; border: none; padding-left: 8px;")
        layout.addWidget(self._operator_meta)
        layout.addStretch()
        return frame

    def _create_input_area(self) -> QFrame:
        """Create clean input area"""
        input_frame = QFrame()
        input_frame.setStyleSheet("""
            QFrame {
                background-color: rgba(255, 255, 255, 0.58);
                border-top: 1px solid rgba(255,255,255,0.42);
            }
        """)

        outer = QVBoxLayout(input_frame)
        outer.setContentsMargins(16, 10, 16, 12)
        outer.setSpacing(10)

        suggestions = QHBoxLayout()
        suggestions.setContentsMargins(0, 0, 0, 0)
        suggestions.setSpacing(8)
        self._suggestion_buttons: list[QPushButton] = []
        for text in self._suggestions[:4]:
            btn = QPushButton(text)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedHeight(30)
            btn.setStyleSheet("""
                QPushButton {
                    background: rgba(255, 255, 255, 0.78);
                    color: #334155;
                    border: 1px solid rgba(255,255,255,0.62);
                    border-radius: 15px;
                    padding: 0 12px;
                    font-size: 11px;
                    font-weight: 600;
                }
                QPushButton:hover {
                    background: rgba(255, 255, 255, 0.96);
                    color: #162033;
                }
            """)
            btn.clicked.connect(lambda checked=False, value=text: self.set_draft(value, auto_send=False))
            suggestions.addWidget(btn)
            self._suggestion_buttons.append(btn)
        suggestions.addStretch()
        outer.addLayout(suggestions)

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # Attachment button
        attach_btn = QPushButton("ADD")
        attach_btn.setFixedSize(42, 38)
        attach_btn.setFont(QFont(".AppleSystemUIFont", 10, QFont.Weight.Bold))
        attach_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        attach_btn.setToolTip("Dosya ekle")
        attach_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(255, 255, 255, 0.72);
                color: #4C82FF;
                border: 1px solid rgba(255,255,255,0.58);
                border-radius: 8px;
            }
            QPushButton:hover {
                background-color: rgba(255,255,255,0.94);
            }
        """)
        attach_btn.clicked.connect(self._attach_file)
        layout.addWidget(attach_btn)

        # Push-to-talk button
        self._voice_btn = QPushButton("VOICE")
        self._voice_btn.setFixedSize(52, 38)
        self._voice_btn.setFont(QFont(".AppleSystemUIFont", 10, QFont.Weight.Bold))
        self._voice_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._voice_btn.setToolTip("Basılı tut: kaydet, bırak: otomatik yazıya çevir")
        self._voice_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(255, 255, 255, 0.72);
                color: #111318;
                border: 1px solid rgba(255,255,255,0.58);
                border-radius: 8px;
            }
            QPushButton:hover {
                background-color: rgba(255,255,255,0.94);
            }
        """)
        self._voice_btn.pressed.connect(self._start_voice_recording)
        self._voice_btn.released.connect(self._stop_voice_recording)
        layout.addWidget(self._voice_btn)

        # Text input
        self._input_field = QLineEdit()
        self._input_field.setPlaceholderText("Mesajınızı buraya yazın...")
        self._input_field.setMinimumHeight(42)
        self._input_field.setFont(QFont(".AppleSystemUIFont", 12))
        self._input_field.setStyleSheet("""
            QLineEdit {
                background-color: rgba(255, 255, 255, 0.84);
                border: 1px solid rgba(255,255,255,0.64);
                border-radius: 13px;
                padding: 9px 14px;
                color: #111318;
            }
            QLineEdit:focus {
                border: 1.5px solid #4C82FF;
            }
            QLineEdit::placeholder { color: #8A93A3; }
        """)
        self._input_field.returnPressed.connect(self._send_message)
        layout.addWidget(self._input_field, 1)

        # Send button
        self._send_btn = QPushButton("SEND")
        self._send_btn.setMinimumHeight(42)
        self._send_btn.setMinimumWidth(76)
        self._send_btn.setFont(QFont(".AppleSystemUIFont", 10, QFont.Weight.Bold))
        self._send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._send_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(76, 130, 255, 0.94);
                color: #FFFFFF;
                border: none;
                border-radius: 13px;
                padding: 0 18px;
                letter-spacing: 0.5px;
            }
            QPushButton:hover {
                background-color: #3C73F2;
            }
            QPushButton:disabled {
                background-color: #F7F8FA;
                color: #C7D0DD;
            }
        """)
        self._send_btn.clicked.connect(self._send_message)
        layout.addWidget(self._send_btn)

        # Speak latest response
        self._speak_btn = QPushButton("🔊")
        self._speak_btn.setFixedSize(38, 38)
        self._speak_btn.setFont(QFont(".AppleSystemUIFont", 13))
        self._speak_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._speak_btn.setToolTip("Son ELYAN yanıtını seslendir")
        self._speak_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(255, 255, 255, 0.72);
                color: #111318;
                border: 1px solid rgba(255,255,255,0.58);
                border-radius: 19px;
            }
            QPushButton:hover {
                background-color: rgba(255,255,255,0.94);
            }
        """)
        self._speak_btn.clicked.connect(self._speak_latest_response)
        layout.addWidget(self._speak_btn)

        outer.addLayout(layout)
        return input_frame

    def _send_message(self):
        """Send user message"""
        text = self._input_field.text().strip()
        if not text:
            return

        self._add_user_message(text)
        self._input_field.clear()

        self._typing_indicator.start()
        self._send_btn.setEnabled(False)

        if self.process_callback:
            self._worker = CleanProcessingWorker(self.process_callback, text)
            self._worker.finished.connect(self._on_response)
            self._worker.error.connect(self._on_error)
            self._worker.status.connect(self._on_status)
            self._worker.start()
        else:
            QTimer.singleShot(1000, lambda: self._on_response("Demo yanıtı. İşlem bağlantısı yapılmamış."))

    def _on_status(self, status: str):
        """Update UI with intermediate status"""
        self.set_status(True, status)

    def _on_response(self, response: str):
        """Handle bot response"""
        self._typing_indicator.stop()
        self._send_btn.setEnabled(True)
        self._add_bot_message(response)
        self._refresh_suggestions_from_response(response)
        self.set_status(True, "Hazır")
        self.message_received.emit(response)

    def _on_error(self, error: str):
        """Handle processing error"""
        self._typing_indicator.stop()
        self._send_btn.setEnabled(True)
        self._add_bot_message(f"Hata oluştu: {error}")

    def _add_user_message(self, text: str):
        """Add user message bubble"""
        bubble = CleanMessageBubble(text, is_user=True)

        self._messages_layout.insertWidget(
            self._messages_layout.count() - 2,
            bubble
        )

        self._messages.append({
            "role": "user",
            "content": text,
            "timestamp": datetime.now().isoformat()
        })

        self.message_sent.emit(text)
        self._scroll_to_bottom()

    def _add_bot_message(self, text: str):
        """Add bot message bubble"""
        bubble = CleanMessageBubble(text, is_user=False)

        self._messages_layout.insertWidget(
            self._messages_layout.count() - 2,
            bubble
        )

        self._messages.append({
            "role": "assistant",
            "content": text,
            "timestamp": datetime.now().isoformat()
        })
        self._last_assistant_message = text

        self._scroll_to_bottom()

    def _scroll_to_bottom(self):
        """Scroll to bottom of chat"""
        QTimer.singleShot(100, lambda:
            self._scroll_area.verticalScrollBar().setValue(
                self._scroll_area.verticalScrollBar().maximum()
            )
        )

    def _attach_file(self):
        """Open file attachment dialog"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Dosya Seç",
            str(Path.home()),
            "Tüm Dosyalar (*)"
        )
        if file_path:
            filename = Path(file_path).name
            self._input_field.setText(f"[Dosya: {filename}] ")
            self._input_field.setFocus()

    def clear_chat(self):
        """Clear chat history"""
        while self._messages_layout.count() > 2:
            item = self._messages_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self._messages.clear()
        self._add_bot_message("Sohbet temizlendi. Size nasıl yardımcı olabilirim?")

    def export_chat(self):
        """Export chat history"""
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Sohbeti Kaydet",
            str(Path.home() / "Desktop" / "elyan_chat.txt"),
            "Text Files (*.txt);;Markdown (*.md)"
        )

        if file_path:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write("Elyan Sohbet Gecmisi\n")
                f.write(f"Tarih: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n")
                f.write("-" * 50 + "\n\n")

                for msg in self._messages:
                    role = "Kullanici" if msg["role"] == "user" else "Elyan"
                    f.write(f"{role}:\n{msg['content']}\n\n")

            self._add_bot_message(f"Sohbet kaydedildi: {Path(file_path).name}")

    def set_status(self, online: bool, status_text: str = None):
        """Set bot status"""
        if online:
            self._status_label.setText(status_text or "AKTİF")
            self._status_label.setStyleSheet("color: #14803E; font-size: 10px; font-weight: 700;")
        else:
            self._status_label.setText(status_text or "PASİF")
            self._status_label.setStyleSheet("color: #FF3B30; font-size: 10px; font-weight: 700;")

    def add_message(self, text: str, is_user: bool = False):
        """Add a message externally"""
        if is_user:
            self._add_user_message(text)
        else:
            self._add_bot_message(text)

    def set_draft(self, text: str, auto_send: bool = False):
        """Programmatically set chat input draft and optionally send."""
        self._input_field.setText(str(text or ""))
        self._input_field.setFocus()
        if auto_send and self._input_field.text().strip():
            self._send_message()

    def _build_ffmpeg_record_cmd(self, out_file: str) -> list[str]:
        # macOS avfoundation input, first audio device.
        return [
            "ffmpeg",
            "-y",
            "-f",
            "avfoundation",
            "-i",
            ":0",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            out_file,
        ]

    def _start_voice_recording(self):
        """Start press-to-talk recording using ffmpeg."""
        if self._is_recording:
            return
        try:
            fd, path = tempfile.mkstemp(prefix="elyan_ptt_", suffix=".wav")
            os.close(fd)
            cmd = self._build_ffmpeg_record_cmd(path)
            self._recording_process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                preexec_fn=os.setsid if hasattr(os, "setsid") else None,
            )
            self._recording_file = path
            self._is_recording = True
            self.set_status(True, "Dinleniyor...")
            self._voice_btn.setStyleSheet("""
                QPushButton {
                    background-color: #ef4444;
                    color: #ffffff;
                    border: none;
                    border-radius: 20px;
                }
            """)
        except FileNotFoundError:
            self._add_bot_message("Ses kaydı için `ffmpeg` bulunamadı. Kurulum: `brew install ffmpeg`")
        except Exception as e:
            logger.error(f"start voice recording failed: {e}")
            self._add_bot_message(f"Ses kaydı başlatılamadı: {e}")

    def _stop_voice_recording(self):
        """Stop recording and transcribe."""
        if not self._is_recording:
            return
        self._is_recording = False
        self.set_status(True, "Ses işleniyor...")
        self._voice_btn.setStyleSheet("""
            QPushButton {
                background-color: #F2F2F7;
                color: #0f172a;
                border: none;
                border-radius: 20px;
            }
        """)

        proc = self._recording_process
        audio_file = self._recording_file
        self._recording_process = None
        self._recording_file = None

        try:
            if proc and proc.poll() is None:
                if hasattr(os, "killpg") and hasattr(os, "getpgid"):
                    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                else:
                    proc.terminate()
                try:
                    proc.wait(timeout=3)
                except Exception:
                    proc.kill()
        except Exception as e:
            logger.debug(f"stop recording process warning: {e}")

        if not audio_file or not Path(audio_file).exists():
            self._add_bot_message("Ses kaydı alınamadı.")
            return

        self._voice_worker = VoiceTranscriptionWorker(audio_file=audio_file, language="tr")
        self._voice_worker.finished.connect(lambda res, p=audio_file: self._on_voice_transcription_done(res, p))
        self._voice_worker.error.connect(lambda err, p=audio_file: self._on_voice_transcription_error(err, p))
        self._voice_worker.start()

    def _on_voice_transcription_done(self, result: dict, audio_file: str):
        try:
            if result.get("success"):
                text = str(result.get("text", "")).strip()
                if text:
                    self._input_field.setText(text)
                    self._send_message()
                else:
                    self._add_bot_message("Ses çözümlendi fakat metin boş döndü.")
            else:
                self._add_bot_message(f"Ses çözümlenemedi: {result.get('error', 'bilinmeyen hata')}")
        finally:
            self._cleanup_audio_file(audio_file)
            self.set_status(True, "AKTİF")

    def _on_voice_transcription_error(self, error: str, audio_file: str):
        self._cleanup_audio_file(audio_file)
        self._add_bot_message(f"Ses dönüştürme hatası: {error}")
        self.set_status(True, "AKTİF")

    def _cleanup_audio_file(self, path: str):
        try:
            if path and Path(path).exists():
                Path(path).unlink(missing_ok=True)
        except Exception:
            pass

    def _speak_latest_response(self):
        """Speak latest assistant response via local TTS."""
        if not self._last_assistant_message.strip():
            self._add_bot_message("Seslendirme için önce bir ELYAN yanıtı olmalı.")
            return

        class _SpeakWorker(QThread):
            finished = pyqtSignal(dict)
            error = pyqtSignal(str)

            def __init__(self, text: str):
                super().__init__()
                self.text = text

            def run(self):
                loop = None
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    from tools.multimodal_tools import speak_text_local
                    result = loop.run_until_complete(
                        speak_text_local(self.text[:800])
                    )
                    self.finished.emit(result if isinstance(result, dict) else {"success": False, "error": "invalid_result"})
                except Exception as exc:
                    self.error.emit(str(exc))
                finally:
                    if loop is not None:
                        loop.close()

        worker = _SpeakWorker(self._last_assistant_message)
        worker.finished.connect(self._on_speak_done)
        worker.error.connect(lambda e: self._add_bot_message(f"Seslendirme hatası: {e}"))
        worker.start()
        self._speak_btn.setEnabled(False)
        self._speak_worker = worker

    def _on_speak_done(self, result: dict):
        self._speak_btn.setEnabled(True)
        if not result.get("success"):
            self._add_bot_message(f"Seslendirme başarısız: {result.get('error', 'bilinmeyen hata')}")

    @staticmethod
    def _pill_style(tone: str) -> str:
        styles = {
            "healthy": "QLabel { background: rgba(226, 247, 234, 0.92); color: #166534; border: 1px solid rgba(187, 240, 204, 0.92); border-radius: 14px; padding: 4px 10px; font-size: 11px; font-weight: 700; }",
            "degraded": "QLabel { background: rgba(255, 243, 205, 0.92); color: #8A5A00; border: 1px solid rgba(245, 223, 156, 0.92); border-radius: 14px; padding: 4px 10px; font-size: 11px; font-weight: 700; }",
            "neutral": "QLabel { background: rgba(255, 255, 255, 0.88); color: #475569; border: 1px solid rgba(255,255,255,0.62); border-radius: 14px; padding: 4px 10px; font-size: 11px; font-weight: 700; }",
            "failed": "QLabel { background: rgba(255, 228, 228, 0.92); color: #991B1B; border: 1px solid rgba(248, 187, 187, 0.92); border-radius: 14px; padding: 4px 10px; font-size: 11px; font-weight: 700; }",
            "verified": "QLabel { background: rgba(227, 242, 255, 0.92); color: #1D4ED8; border: 1px solid rgba(179, 217, 255, 0.92); border-radius: 14px; padding: 4px 10px; font-size: 11px; font-weight: 700; }",
            "turbo": "QLabel { background: rgba(240, 233, 255, 0.92); color: #6D28D9; border: 1px solid rgba(219, 202, 255, 0.92); border-radius: 14px; padding: 4px 10px; font-size: 11px; font-weight: 700; }",
            "blocked": "QLabel { background: rgba(255, 232, 232, 0.92); color: #B91C1C; border: 1px solid rgba(252, 190, 190, 0.92); border-radius: 14px; padding: 4px 10px; font-size: 11px; font-weight: 700; }",
        }
        return styles.get(str(tone or "neutral").lower(), styles["neutral"])

    @staticmethod
    def _operator_tone(row: Dict[str, Any]) -> str:
        status = str(row.get("status") or "unknown").lower()
        if status in {"failed", "unavailable"}:
            return "failed"
        if status in {"blocked"}:
            return "blocked"
        if bool(row.get("fallback_active")):
            return "degraded"
        verification = str(row.get("verification_state") or "").lower()
        lane = str(row.get("current_lane") or "").lower()
        if verification in {"verified", "strong"}:
            return "verified"
        if "turbo" in lane:
            return "turbo"
        if status == "healthy":
            return "healthy"
        if status in {"degraded", "unknown"}:
            return "degraded"
        return "neutral"

    @staticmethod
    def _operator_caption(label: str, row: Dict[str, Any]) -> str:
        status = str(row.get("status") or "unknown").lower()
        if bool(row.get("fallback_active")):
            return f"{label} fallback"
        verification = str(row.get("verification_state") or "").lower()
        lane = str(row.get("current_lane") or "").replace("_", " ").strip()
        if verification in {"verified", "strong"}:
            return f"{label} verified"
        if lane:
            return f"{label} {lane.split()[0]}"
        return f"{label} {status}"

    def _refresh_operator_strip(self) -> None:
        try:
            payload = get_operator_status_sync()
        except Exception as exc:
            logger.debug(f"operator strip refresh failed: {exc}")
            return
        summary = dict(payload.get("summary") or {})
        labels = {
            "mobile_dispatch": "Mobile",
            "computer_use": "Computer",
            "internet_reach": "Internet",
            "document_ingest": "Docs",
            "speed_runtime": "Speed",
        }
        for key, label in labels.items():
            pill = self._operator_labels.get(key)
            if pill is None:
                continue
            row = dict(summary.get(key) or {})
            tone = self._operator_tone(row)
            pill.setText(self._operator_caption(label, row))
            pill.setStyleSheet(self._pill_style(tone))
            tooltip_bits = [
                f"status={row.get('status', 'unknown')}",
                f"lane={row.get('current_lane', '-')}",
                f"verify={row.get('verification_state', '-')}",
                f"fallback={bool(row.get('fallback_active'))}",
            ]
            pill.setToolTip(" · ".join(tooltip_bits))
        speed = dict(summary.get("speed_runtime") or {})
        lane = str(speed.get("current_lane") or "unknown").replace("_", " ")
        verify = str(speed.get("verification_state") or "standard")
        latency = str(speed.get("average_latency_bucket") or "unknown")
        self._operator_meta.setText(f"Lane {lane} · {verify} · {latency}")
        overall = str(payload.get("status") or "unknown").upper()
        self._status_label.setText(f"OPERATOR {overall}")

    def _refresh_suggestions_from_response(self, response: str) -> None:
        low = str(response or "").lower()
        suggestions = ["Bunu biraz daha aç", "Kısa özet çıkar", "Bir sonraki adımı öner", "Bunu kaynağıyla doğrula"]
        if "telefon" in low or "mobile" in low:
            suggestions = ["Telefon bağlantısını tekrar kontrol et", "Pairing kodu üret", "Mobil oturumları göster", "Bu işi telefona gönder"]
        elif "dosya" in low or "pdf" in low or "belge" in low:
            suggestions = ["Belgeyi özetle", "Ana maddeleri çıkar", "Tabloları bul", "Bunu projeye dönüştür"]
        elif "araştır" in low or "github" in low or "web" in low:
            suggestions = ["Daha derin araştır", "Kaynakları sırala", "Bunu özetle", "Aksiyon planı çıkar"]
        self._suggestions = suggestions
        for button, text in zip(self._suggestion_buttons, suggestions):
            button.setText(text)
