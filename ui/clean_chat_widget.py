"""
Clean Chat Widget - Professional chat interface without emojis
Minimal, clean and modern design
"""

import asyncio
import inspect
import json
from datetime import datetime
from typing import Optional, List, Dict, Any, Callable
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QLabel,
    QPushButton, QLineEdit, QTextEdit, QFrame, QSizePolicy,
    QApplication, QFileDialog, QMenu
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QThread, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QFont, QPixmap, QColor, QPalette, QAction, QIcon

from utils.logger import get_logger

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
                    background-color: #7196A2; /* WIQO_STEEL */
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
        sender = QLabel("YOU" if self.is_user else "WIQO")
        sender.setFont(QFont(".AppleSystemUIFont", 10, QFont.Weight.Bold))
        sender.setStyleSheet(f"color: {'#7196A2' if self.is_user else '#8E8E93'}; border: none; letter-spacing: 0.5px;")
        bubble_layout.addWidget(sender)

        # Message text
        text_label = QLabel(self.message)
        text_label.setWordWrap(True)
        text_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        text_label.setFont(QFont(".AppleSystemUIFont", 13))
        text_label.setTextFormat(Qt.TextFormat.MarkdownText)
        text_label.setStyleSheet(f"""
            color: {'#FFFFFF' if self.is_user else '#252F33'};
            line-height: 1.4;
            padding: 2px;
            border: none;
        """)
        bubble_layout.addWidget(text_label)

        # Timestamp
        time_label = QLabel(self.timestamp)
        time_label.setFont(QFont(".AppleSystemUIFont", 9))
        time_label.setStyleSheet(f"color: {'rgba(255,255,255,0.7)' if self.is_user else '#8E8E93'};")
        time_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        bubble_layout.addWidget(time_label)

        # Style bubble
        if self.is_user:
            bubble.setStyleSheet("""
                QFrame {
                    background-color: #7196A2;
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
                    background-color: #F5F5F7;
                    border: 1px solid #E5E5EA;
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
        avatar = QLabel("W")
        avatar.setFixedSize(32, 32)
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar.setFont(QFont(".AppleSystemUIFont", 12, QFont.Weight.Bold))
        avatar.setStyleSheet("""
            QLabel {
                background-color: #E5E5EA;
                color: #7196A2;
                border-radius: 16px;
            }
        """)
        layout.addWidget(avatar)

        # Typing indicator
        indicator_frame = QFrame()
        indicator_frame.setStyleSheet("""
            QFrame {
                background-color: #E5E5EA;
                border: none;
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
            dot.setStyleSheet("color: #475569;")
            indicator_layout.addWidget(dot)
            self._dots.append(dot)

        layout.addWidget(indicator_frame)
        layout.addStretch()

        self.setStyleSheet("background: transparent;")

    def _animate(self):
        for i, dot in enumerate(self._dots):
            if i == self._animation_index:
                dot.setStyleSheet("color: #94a3b8;")
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


class CleanChatWidget(QWidget):
    """Clean, professional chat interface"""

    message_sent = pyqtSignal(str)
    message_received = pyqtSignal(str)

    def __init__(self, process_callback: Callable = None, parent=None):
        super().__init__(parent)
        self.process_callback = process_callback
        self._messages: List[Dict[str, Any]] = []
        self._worker = None

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header = self._create_header()
        layout.addWidget(header)

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
        self._messages_layout.setContentsMargins(20, 20, 20, 20)
        self._messages_layout.setSpacing(12)
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
            "Merhaba, ben Wiqo - kişisel bilgisayar asistanınız.\n\n"
            "Size dosya yönetimi, araştırma, belge oluşturma ve "
            "sistem kontrolü konularında yardımcı olabilirim.\n\n"
            "Nasıl yardımcı olabilirim?"
        )

    def _create_header(self) -> QFrame:
        """Create clean header"""
        header = QFrame()
        header.setFixedHeight(64)
        header.setStyleSheet("""
            QFrame {
                background-color: #FFFFFF;
                border-bottom: 1px solid #E5E5EA;
            }
        """)

        layout = QHBoxLayout(header)
        layout.setContentsMargins(20, 0, 20, 0)

        # Bot info
        info_layout = QHBoxLayout()
        info_layout.setSpacing(12)

        # Avatar
        avatar = QLabel("W")
        avatar.setFixedSize(40, 40)
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar.setFont(QFont(".AppleSystemUIFont", 16, QFont.Weight.Bold))
        avatar.setStyleSheet("""
            QLabel {
                background-color: #22c55e;
                color: #ffffff;
                border-radius: 20px;
            }
        """)
        info_layout.addWidget(avatar)

        # Name and status
        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)

        name_label = QLabel("WIQO")
        name_label.setFont(QFont(".AppleSystemUIFont", 18, QFont.Weight.Bold))
        name_label.setStyleSheet("color: #252F33; border: none; letter-spacing: 0.5px;")
        text_layout.addWidget(name_label)

        self._status_label = QLabel("AKTİF")
        self._status_label.setFont(QFont(".AppleSystemUIFont", 10, QFont.Weight.Bold))
        self._status_label.setStyleSheet("color: #34C759; border: none; text-transform: uppercase;")
        text_layout.addWidget(self._status_label)

        info_layout.addLayout(text_layout)
        layout.addLayout(info_layout)

        layout.addStretch()

        # Action buttons
        clear_btn = QPushButton("Temizle")
        clear_btn.setFont(QFont(".AppleSystemUIFont", 12))
        clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #94a3b8;
                border: none;
                padding: 8px 12px;
            }
            QPushButton:hover {
                color: #252F33;
            }
        """)
        clear_btn.clicked.connect(self.clear_chat)
        layout.addWidget(clear_btn)

        export_btn = QPushButton("Dışa Aktar")
        export_btn.setFont(QFont(".AppleSystemUIFont", 12))
        export_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        export_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #94a3b8;
                border: none;
                padding: 8px 12px;
            }
            QPushButton:hover {
                color: #252F33;
            }
        """)
        export_btn.clicked.connect(self.export_chat)
        layout.addWidget(export_btn)

        return header

    def _create_input_area(self) -> QFrame:
        """Create clean input area"""
        input_frame = QFrame()
        input_frame.setStyleSheet("""
            QFrame {
                background-color: #FDFDFD;
                border-top: 1px solid #E5E5EA;
            }
        """)

        layout = QHBoxLayout(input_frame)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        # Attachment button
        attach_btn = QPushButton("+")
        attach_btn.setFixedSize(40, 40)
        attach_btn.setFont(QFont(".AppleSystemUIFont", 18))
        attach_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        attach_btn.setToolTip("Dosya ekle")
        attach_btn.setStyleSheet("""
            QPushButton {
                background-color: #F2F2F7;
                color: #7196A2;
                border: none;
                border-radius: 20px;
            }
            QPushButton:hover {
                background-color: #E5E5EA;
            }
        """)
        attach_btn.clicked.connect(self._attach_file)
        layout.addWidget(attach_btn)

        # Text input
        self._input_field = QLineEdit()
        self._input_field.setPlaceholderText("Mesajınızı yazın...")
        self._input_field.setMinimumHeight(44)
        self._input_field.setFont(QFont(".AppleSystemUIFont", 14))
        self._input_field.setStyleSheet("""
            QLineEdit {
                background-color: #F2F2F7;
                border: 1px solid transparent;
                border-radius: 20px;
                padding: 10px 18px;
                color: #252F33;
            }
            QLineEdit:focus {
                background-color: #FFFFFF;
                border: 1px solid #D1D1D6;
            }
            QLineEdit::placeholder { color: #8E8E93; }
        """)
        self._input_field.returnPressed.connect(self._send_message)
        layout.addWidget(self._input_field, 1)

        # Send button
        self._send_btn = QPushButton("Gönder")
        self._send_btn.setMinimumHeight(44)
        self._send_btn.setMinimumWidth(80)
        self._send_btn.setFont(QFont(".AppleSystemUIFont", 13, QFont.Weight.Medium))
        self._send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._send_btn.setStyleSheet("""
            QPushButton {
                background-color: #252F33;
                color: #FFFFFF;
                border: none;
                border-radius: 22px;
                padding: 0 24px;
                font-weight: 700;
                letter-spacing: 0.5px;
            }
            QPushButton:hover {
                background-color: #090E0F;
            }
            QPushButton:disabled {
                background-color: #E5E5EA;
                color: #8E8E93;
            }
        """)
        self._send_btn.clicked.connect(self._send_message)
        layout.addWidget(self._send_btn)

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
            str(Path.home() / "Desktop" / "wiqo_chat.txt"),
            "Text Files (*.txt);;Markdown (*.md)"
        )

        if file_path:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write("Wiqo Sohbet Gecmisi\n")
                f.write(f"Tarih: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n")
                f.write("-" * 50 + "\n\n")

                for msg in self._messages:
                    role = "Kullanici" if msg["role"] == "user" else "Wiqo"
                    f.write(f"{role}:\n{msg['content']}\n\n")

            self._add_bot_message(f"Sohbet kaydedildi: {Path(file_path).name}")

    def set_status(self, online: bool, status_text: str = None):
        """Set bot status"""
        if online:
            self._status_label.setText(status_text or "AKTİF")
            self._status_label.setStyleSheet("color: #34C759; font-size: 10px; font-weight: 700;")
        else:
            self._status_label.setText(status_text or "PASİF")
            self._status_label.setStyleSheet("color: #FF3B30; font-size: 10px; font-weight: 700;")

    def add_message(self, text: str, is_user: bool = False):
        """Add a message externally"""
        if is_user:
            self._add_user_message(text)
        else:
            self._add_bot_message(text)
