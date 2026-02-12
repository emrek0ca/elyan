"""
Modern Chat Widget - Professional chat interface with message bubbles
"""

import asyncio
from datetime import datetime
from typing import Optional, List, Dict, Any, Callable
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QLabel,
    QPushButton, QLineEdit, QTextEdit, QFrame, QSizePolicy,
    QApplication, QFileDialog, QMenu
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QThread, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QFont, QPixmap, QColor, QPalette, QAction

from utils.logger import get_logger

logger = get_logger("chat_widget")


class MessageBubble(QFrame):
    """Single chat message bubble"""

    def __init__(self, message: str, is_user: bool, timestamp: str = None, parent=None):
        super().__init__(parent)
        self.is_user = is_user
        self.message = message
        self.timestamp = timestamp or datetime.now().strftime("%H:%M")

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(2)

        # Message container
        container = QHBoxLayout()
        container.setSpacing(8)

        # Avatar
        avatar = QLabel()
        avatar.setFixedSize(36, 36)
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)

        if self.is_user:
            avatar.setText("")
            avatar.setStyleSheet("""
                QLabel {
                    background-color: #6366f1;
                    border-radius: 18px;
                    font-size: 18px;
                }
            """)
        else:
            avatar.setText("")
            avatar.setStyleSheet("""
                QLabel {
                    background-color: #10b981;
                    border-radius: 18px;
                    font-size: 18px;
                }
            """)

        # Message bubble
        bubble = QFrame()
        bubble.setMaximumWidth(500)
        bubble_layout = QVBoxLayout(bubble)
        bubble_layout.setContentsMargins(12, 8, 12, 8)
        bubble_layout.setSpacing(4)

        # Message text
        text_label = QLabel(self.message)
        text_label.setWordWrap(True)
        text_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        text_label.setStyleSheet(f"""
            QLabel {{
                color: {'#ffffff' if self.is_user else '#e4e4e7'};
                font-size: 14px;
                line-height: 1.5;
            }}
        """)
        bubble_layout.addWidget(text_label)

        # Timestamp
        time_label = QLabel(self.timestamp)
        time_label.setStyleSheet(f"""
            QLabel {{
                color: {'rgba(255,255,255,0.7)' if self.is_user else '#71717a'};
                font-size: 11px;
            }}
        """)
        time_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        bubble_layout.addWidget(time_label)

        # Style bubble
        if self.is_user:
            bubble.setStyleSheet("""
                QFrame {
                    background-color: #6366f1;
                    border-radius: 16px;
                    border-top-right-radius: 4px;
                }
            """)
            container.addStretch()
            container.addWidget(bubble)
            container.addWidget(avatar)
        else:
            bubble.setStyleSheet("""
                QFrame {
                    background-color: #27272a;
                    border-radius: 16px;
                    border-top-left-radius: 4px;
                }
            """)
            container.addWidget(avatar)
            container.addWidget(bubble)
            container.addStretch()

        layout.addLayout(container)


class TypingIndicator(QFrame):
    """Animated typing indicator"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
        self._animation_index = 0

        # Animation timer
        self._timer = QTimer()
        self._timer.timeout.connect(self._animate)

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)

        # Avatar
        avatar = QLabel("")
        avatar.setFixedSize(36, 36)
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar.setStyleSheet("""
            QLabel {
                background-color: #10b981;
                border-radius: 18px;
                font-size: 18px;
            }
        """)
        layout.addWidget(avatar)

        # Typing dots container
        dots_frame = QFrame()
        dots_frame.setStyleSheet("""
            QFrame {
                background-color: #27272a;
                border-radius: 16px;
                padding: 8px 16px;
            }
        """)
        dots_layout = QHBoxLayout(dots_frame)
        dots_layout.setContentsMargins(12, 8, 12, 8)
        dots_layout.setSpacing(6)

        self._dots = []
        for _ in range(3):
            dot = QLabel("●")
            dot.setStyleSheet("color: #52525b; font-size: 12px;")
            dots_layout.addWidget(dot)
            self._dots.append(dot)

        layout.addWidget(dots_frame)
        layout.addStretch()

        self.setStyleSheet("background: transparent;")

    def _animate(self):
        for i, dot in enumerate(self._dots):
            if i == self._animation_index:
                dot.setStyleSheet("color: #a1a1aa; font-size: 12px;")
            else:
                dot.setStyleSheet("color: #52525b; font-size: 12px;")

        self._animation_index = (self._animation_index + 1) % 3

    def start(self):
        self._timer.start(300)
        self.show()

    def stop(self):
        self._timer.stop()
        self.hide()


class ProcessingWorker(QThread):
    """Background worker for processing messages"""

    finished = pyqtSignal(str)
    error = pyqtSignal(str)
    progress = pyqtSignal(int, str)

    def __init__(self, process_func: Callable, message: str):
        super().__init__()
        self.process_func = process_func
        self.message = message

    def run(self):
        try:
            # Create event loop for async function
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            result = loop.run_until_complete(self.process_func(self.message))
            self.finished.emit(result)

        except Exception as e:
            logger.error(f"Processing error: {e}")
            self.error.emit(str(e))
        finally:
            loop.close()


class ChatWidget(QWidget):
    """Professional chat interface widget"""

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
                background-color: #0f0f0f;
            }
            QScrollBar:vertical {
                background-color: #1a1a1a;
                width: 8px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background-color: #3f3f46;
                border-radius: 4px;
                min-height: 30px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #6366f1;
            }
        """)

        # Messages container
        self._messages_container = QWidget()
        self._messages_layout = QVBoxLayout(self._messages_container)
        self._messages_layout.setContentsMargins(16, 16, 16, 16)
        self._messages_layout.setSpacing(8)
        self._messages_layout.addStretch()

        self._scroll_area.setWidget(self._messages_container)
        layout.addWidget(self._scroll_area, 1)

        # Typing indicator
        self._typing_indicator = TypingIndicator()
        self._typing_indicator.hide()
        self._messages_layout.addWidget(self._typing_indicator)

        # Input area
        input_area = self._create_input_area()
        layout.addWidget(input_area)

        # Welcome message
        self._add_bot_message(
            "Merhaba! Ben Wiqo, kişisel bilgisayar asistanınız. \n\n"
            "Size şu konularda yardımcı olabilirim:\n"
            "• 📁 Dosya ve klasör yönetimi\n"
            "•  Araştırma ve bilgi toplama\n"
            "• 📄 Belge oluşturma\n"
            "•  Sistem kontrolü\n"
            "•  Veri görselleştirme\n\n"
            "Nasıl yardımcı olabilirim?"
        )

    def _create_header(self) -> QFrame:
        """Create chat header"""
        header = QFrame()
        header.setFixedHeight(60)
        header.setStyleSheet("""
            QFrame {
                background-color: #1a1a1a;
                border-bottom: 1px solid #27272a;
            }
        """)

        layout = QHBoxLayout(header)
        layout.setContentsMargins(16, 8, 16, 8)

        # Bot avatar and name
        avatar_layout = QHBoxLayout()
        avatar_layout.setSpacing(12)

        avatar = QLabel("")
        avatar.setFixedSize(40, 40)
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar.setStyleSheet("""
            QLabel {
                background-color: #10b981;
                border-radius: 20px;
                font-size: 20px;
            }
        """)
        avatar_layout.addWidget(avatar)

        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)

        name_label = QLabel("Wiqo")
        name_label.setStyleSheet("""
            QLabel {
                color: #ffffff;
                font-size: 16px;
                font-weight: bold;
            }
        """)
        info_layout.addWidget(name_label)

        self._status_label = QLabel("● Çevrimiçi")
        self._status_label.setStyleSheet("""
            QLabel {
                color: #10b981;
                font-size: 12px;
            }
        """)
        info_layout.addWidget(self._status_label)

        avatar_layout.addLayout(info_layout)
        layout.addLayout(avatar_layout)

        layout.addStretch()

        # Action buttons
        clear_btn = QPushButton("🗑️")
        clear_btn.setToolTip("Sohbeti temizle")
        clear_btn.setFixedSize(36, 36)
        clear_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: none;
                border-radius: 18px;
                font-size: 18px;
            }
            QPushButton:hover {
                background-color: #27272a;
            }
        """)
        clear_btn.clicked.connect(self.clear_chat)
        layout.addWidget(clear_btn)

        export_btn = QPushButton("📤")
        export_btn.setToolTip("Sohbeti dışa aktar")
        export_btn.setFixedSize(36, 36)
        export_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: none;
                border-radius: 18px;
                font-size: 18px;
            }
            QPushButton:hover {
                background-color: #27272a;
            }
        """)
        export_btn.clicked.connect(self.export_chat)
        layout.addWidget(export_btn)

        return header

    def _create_input_area(self) -> QFrame:
        """Create message input area"""
        input_frame = QFrame()
        input_frame.setStyleSheet("""
            QFrame {
                background-color: #1a1a1a;
                border-top: 1px solid #27272a;
            }
        """)

        layout = QHBoxLayout(input_frame)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(12)

        # Attachment button
        attach_btn = QPushButton("📎")
        attach_btn.setFixedSize(40, 40)
        attach_btn.setToolTip("Dosya ekle")
        attach_btn.setStyleSheet("""
            QPushButton {
                background-color: #27272a;
                border: none;
                border-radius: 20px;
                font-size: 18px;
            }
            QPushButton:hover {
                background-color: #3f3f46;
            }
        """)
        attach_btn.clicked.connect(self._attach_file)
        layout.addWidget(attach_btn)

        # Text input
        self._input_field = QLineEdit()
        self._input_field.setPlaceholderText("Mesajınızı yazın...")
        self._input_field.setMinimumHeight(44)
        self._input_field.setStyleSheet("""
            QLineEdit {
                background-color: #27272a;
                border: 1px solid #3f3f46;
                border-radius: 22px;
                padding: 10px 20px;
                color: #ffffff;
                font-size: 14px;
            }
            QLineEdit:focus {
                border-color: #6366f1;
            }
            QLineEdit::placeholder {
                color: #71717a;
            }
        """)
        self._input_field.returnPressed.connect(self._send_message)
        layout.addWidget(self._input_field, 1)

        # Voice button (placeholder)
        voice_btn = QPushButton("🎤")
        voice_btn.setFixedSize(40, 40)
        voice_btn.setToolTip("Sesli mesaj")
        voice_btn.setStyleSheet("""
            QPushButton {
                background-color: #27272a;
                border: none;
                border-radius: 20px;
                font-size: 18px;
            }
            QPushButton:hover {
                background-color: #3f3f46;
            }
        """)
        layout.addWidget(voice_btn)

        # Send button
        self._send_btn = QPushButton("➤")
        self._send_btn.setFixedSize(44, 44)
        self._send_btn.setStyleSheet("""
            QPushButton {
                background-color: #6366f1;
                border: none;
                border-radius: 22px;
                font-size: 20px;
                color: white;
            }
            QPushButton:hover {
                background-color: #4f46e5;
            }
            QPushButton:disabled {
                background-color: #3f3f46;
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

        # Add user message
        self._add_user_message(text)
        self._input_field.clear()

        # Show typing indicator
        self._typing_indicator.start()
        self._send_btn.setEnabled(False)

        # Process message
        if self.process_callback:
            self._worker = ProcessingWorker(self.process_callback, text)
            self._worker.finished.connect(self._on_response)
            self._worker.error.connect(self._on_error)
            self._worker.start()
        else:
            # Demo response
            QTimer.singleShot(1000, lambda: self._on_response("Bu bir demo yanıttır. İşlem callback'i bağlanmamış."))

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
        self._add_bot_message(f" Hata oluştu: {error}")

    def _add_user_message(self, text: str):
        """Add user message bubble"""
        bubble = MessageBubble(text, is_user=True)

        # Insert before stretch
        self._messages_layout.insertWidget(
            self._messages_layout.count() - 2,  # Before typing indicator and stretch
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
        bubble = MessageBubble(text, is_user=False)

        # Insert before typing indicator and stretch
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
        # Remove all message bubbles
        while self._messages_layout.count() > 2:  # Keep stretch and typing indicator
            item = self._messages_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self._messages.clear()

        # Add welcome message again
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
                f.write("# Wiqo Sohbet Geçmişi\n")
                f.write(f"# Tarih: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n")

                for msg in self._messages:
                    role = " Kullanıcı" if msg["role"] == "user" else " Wiqo"
                    f.write(f"{role}:\n{msg['content']}\n\n")

            self._add_bot_message(f" Sohbet kaydedildi: {Path(file_path).name}")

    def set_status(self, online: bool, status_text: str = None):
        """Set bot status"""
        if online:
            self._status_label.setText(f"● {status_text or 'Çevrimiçi'}")
            self._status_label.setStyleSheet("color: #10b981; font-size: 12px;")
        else:
            self._status_label.setText(f"○ {status_text or 'Çevrimdışı'}")
            self._status_label.setStyleSheet("color: #ef4444; font-size: 12px;")

    def add_message(self, text: str, is_user: bool = False):
        """Add a message externally"""
        if is_user:
            self._add_user_message(text)
        else:
            self._add_bot_message(text)
