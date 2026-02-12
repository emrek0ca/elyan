"""UI Components - Reusable modern UI components for CDACS Bot"""

import sys
import os
from typing import Optional, Callable, List, Any
from pathlib import Path
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from PyQt6.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
        QFrame, QSizePolicy, QGraphicsDropShadowEffect, QLineEdit,
        QTextEdit, QScrollArea, QStackedWidget, QProgressBar,
        QGraphicsOpacityEffect
    )
    from PyQt6.QtCore import Qt, pyqtSignal, QPropertyAnimation, QEasingCurve, QTimer, QSize, pyqtProperty
    from PyQt6.QtGui import QFont, QColor, QIcon, QPixmap, QPainter, QPainterPath
    PYQT_AVAILABLE = True
except ImportError:
    PYQT_AVAILABLE = False


def check_pyqt6():
    return PYQT_AVAILABLE

class WiqoTheme:
    """Standardized glassmorphic styling tokens for Wiqo v4.0"""
    GLASS_BASE = "rgba(255, 255, 255, 0.05)"
    GLASS_BASE_SELECTED = "rgba(255, 255, 255, 0.1)"
    BORDER_OVERLAY = "1px solid rgba(255, 255, 255, 0.1)"
    ACCENT_BLUE = "#3b82f6"
    NEUTRAL_BLUE = "#64748b"
    TEXT_PRIMARY = "#000000"
    TEXT_SECONDARY = "#8E8E93"
    CARD_BG = "#FFFFFF"
    BG_SECONDARY = "#F2F2F7"
    BORDER_LIGHT = "#E5E5EA"
    
    # Fonts
    FONT_UI = ".AppleSystemUIFont"
    FONT_DISPLAY = "SF Pro Display"


# New futuristic classes
if PYQT_AVAILABLE:
    class StandardCard(QFrame):
        """Clean professional card with subtle borders and soft shadows"""
        def __init__(self, parent=None):
            super().__init__(parent)
            self.setObjectName("standard_card")
            self._setup_card()

        def _setup_card(self):
            # Using colors from the professional palette
            # ADDBE3 (Turquoise), 7196A2 (Steel), 517079 (Slate), 252F33 (Charcoal), 090E0F (Black)
            self.setStyleSheet("""
                #standard_card {
                    background-color: #FFFFFF;
                    border: 1px solid #E5E5EA;
                    border-radius: 12px;
                }
            """)
            
            # Very subtle shadow
            shadow = QGraphicsDropShadowEffect(self)
            shadow.setBlurRadius(16)
            shadow.setXOffset(0)
            shadow.setYOffset(4)
            shadow.setColor(QColor(0, 0, 0, 10))
            self.setGraphicsEffect(shadow)

    # Alias for compatibility
    GlassFrame = StandardCard

    class AnimatedButton(QPushButton):
        """Premium button with clean Apple-style and professional palette"""
        def __init__(self, text: str, primary: bool = True, parent=None):
            super().__init__(text, parent)
            self._primary = primary
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setMinimumHeight(40)
            self.update_style()
            
        def set_primary(self, primary: bool):
            self._primary = primary
            self.update_style()

        def update_style(self):
            if self._primary:
                self.setStyleSheet("""
                    QPushButton {
                        background-color: #7196A2; /* WIQO_STEEL */
                        color: white;
                        border: none;
                        border-radius: 8px;
                        font-weight: 600;
                        font-family: "SF Pro Text";
                        font-size: 13px;
                    }
                    QPushButton:hover {
                        background-color: #517079; /* WIQO_SLATE */
                    }
                    QPushButton:pressed {
                        background-color: #252F33; /* WIQO_CHARCOAL */
                    }
                """)
            else:
                self.setStyleSheet("""
                    QPushButton {
                        background-color: #F5F5F7;
                        color: #252F33;
                        border: 1px solid #D1D1D6;
                        border-radius: 8px;
                        font-weight: 500;
                        font-family: "SF Pro Text";
                        font-size: 13px;
                    }
                    QPushButton:hover {
                        background-color: #E5E5EA;
                    }
                    QPushButton:pressed {
                        background-color: #D1D1D6;
                    }
                """)

    class SidebarButton(QPushButton):
        """Minimal sidebar button without icons/emojis"""
        def __init__(self, icon: str, text: str, parent=None):
            super().__init__(parent)
            self._text = text
            self._active = False
            self.setText(self._text)
            self.setFixedHeight(40)
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setCheckable(True)
            self.update_style()

        def update_style(self):
            if self._active:
                self.setStyleSheet("""
                    QPushButton {
                        background-color: #F2F2F7;
                        color: #7196A2; /* WIQO_STEEL */
                        border: none;
                        border-radius: 8px;
                        text-align: left;
                        padding-left: 20px;
                        font-family: "SF Pro Text";
                        font-weight: 600;
                        font-size: 13px;
                    }
                """)
            else:
                self.setStyleSheet("""
                    QPushButton {
                        background-color: transparent;
                        color: #8E8E93;
                        border: none;
                        border-radius: 8px;
                        text-align: left;
                        padding-left: 20px;
                        font-family: "SF Pro Text";
                        font-weight: 500;
                        font-size: 13px;
                    }
                    QPushButton:hover {
                        background-color: #F5F5F7;
                        color: #252F33;
                    }
                """)

        def set_active(self, active: bool):
            self._active = active
            self.setChecked(active)
            self.update_style()


    class StatCard(QFrame):
        """Professional metrics card with text labels only"""

        def __init__(self, icon: str, value: str, label: str, color: str = "#7196A2", parent=None):
            super().__init__(parent)
            self._icon = icon # Kept for compatibility, but hidden
            self._value = value
            self._label = label
            self._color = color
            self._setup_ui()

        def _setup_ui(self):
            self.setObjectName("stat_card")
            self.setStyleSheet(f"""
                #stat_card {{
                    background-color: #FFFFFF;
                    border: 1px solid #E5E5EA;
                    border-radius: 12px;
                }}
            """)

            layout = QVBoxLayout(self)
            layout.setContentsMargins(16, 16, 16, 16)
            layout.setSpacing(4)

            # Label (moved to top for clean look)
            label = QLabel(self._label.upper())
            label.setStyleSheet("color: #8E8E93; font-size: 11px; font-weight: 700; letter-spacing: 0.5px;")
            layout.addWidget(label)

            # Value
            self._value_label = QLabel(self._value)
            self._value_label.setStyleSheet(f"""
                font-size: 24px;
                font-weight: 700;
                color: #252F33;
                font-family: "SF Pro Display";
            """)
            layout.addWidget(self._value_label)

        def set_value(self, value: str):
            self._value = value
            self._value_label.setText(value)


    class ChatBubble(QFrame):
        """Professional chat bubble with Apple aesthetics"""

        def __init__(self, message: str, is_user: bool = True, timestamp: str = None, parent=None):
            super().__init__(parent)
            self._message = message
            self._is_user = is_user
            self._timestamp = timestamp or datetime.now().strftime("%H:%M")
            self._setup_ui()

        def _setup_ui(self):
            layout = QVBoxLayout(self)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(4)

            # Message container
            bubble_container = QHBoxLayout()
            bubble_container.setSpacing(0)

            if not self._is_user:
                bubble_container.addStretch()

            bubble = QFrame()
            bubble.setMaximumWidth(550)

            if self._is_user:
                bubble.setStyleSheet("""
                    QFrame {
                        background-color: #ADDBE3; /* WIQO_TURQUOISE */
                        color: #090E0F;
                        border-radius: 14px;
                        border-bottom-right-radius: 2px;
                        padding: 10px 14px;
                    }
                """)
            else:
                bubble.setStyleSheet("""
                    QFrame {
                        background-color: #F2F2F7;
                        color: #252F33;
                        border-radius: 14px;
                        border-bottom-left-radius: 2px;
                        padding: 10px 14px;
                    }
                """)

            bubble_layout = QVBoxLayout(bubble)
            bubble_layout.setContentsMargins(0, 0, 0, 0)
            bubble_layout.setSpacing(4)

            # Message text
            msg_label = QLabel(self._message)
            msg_label.setWordWrap(True)
            msg_label.setTextFormat(Qt.TextFormat.RichText)
            msg_label.setStyleSheet(f"color: #252F33; font-size: 13px; font-family: 'SF Pro Text';")
            bubble_layout.addWidget(msg_label)

            # Timestamp
            time_label = QLabel(self._timestamp)
            time_label.setStyleSheet(f"color: #8E8E93; font-size: 10px;")
            time_label.setAlignment(Qt.AlignmentFlag.AlignRight if self._is_user else Qt.AlignmentFlag.AlignLeft)
            bubble_layout.addWidget(time_label)

            bubble_container.addWidget(bubble)

            if self._is_user:
                bubble_container.addStretch()

            layout.addLayout(bubble_container)


    class FileItem(QFrame):
        """File list item with icon and actions"""

        clicked = pyqtSignal(str)
        action_clicked = pyqtSignal(str, str)  # path, action

        def __init__(self, name: str, path: str, is_dir: bool = False, size: str = "", modified: str = "", parent=None):
            super().__init__(parent)
            self._name = name
            self._path = path
            self._is_dir = is_dir
            self._size = size
            self._modified = modified
            self._setup_ui()

        def _setup_ui(self):
            self.setStyleSheet("""
                QFrame {
                    background-color: #FFFFFF;
                    border: 1px solid #E5E5EA;
                    border-radius: 10px;
                }
                QFrame:hover {
                    background-color: #F2F2F7;
                    border-color: #D1D1D6;
                }
            """)
            self.setCursor(Qt.CursorShape.PointingHandCursor)

            layout = QHBoxLayout(self)
            layout.setContentsMargins(16, 10, 16, 10)
            layout.setSpacing(12)

            # Info
            info_layout = QVBoxLayout()
            info_layout.setSpacing(2)

            name_label = QLabel(self._name)
            name_label.setStyleSheet("color: #252F33; font-weight: 500; font-size: 13px; border: none;")
            info_layout.addWidget(name_label)

            if self._size or self._modified:
                meta_parts = []
                if self._size:
                    meta_parts.append(self._size)
                if self._modified:
                    meta_parts.append(self._modified)
                meta_label = QLabel(" • ".join(meta_parts))
                meta_label.setStyleSheet("color: #71717a; font-size: 12px;")
                info_layout.addWidget(meta_label)

            layout.addLayout(info_layout, 1)

            # Actions
            if not self._is_dir:
                open_btn = QPushButton("")
                open_btn.setFixedSize(32, 32)
                open_btn.setStyleSheet("""
                    QPushButton {
                        background-color: transparent;
                        border: none;
                        border-radius: 6px;
                        font-size: 16px;
                    }
                    QPushButton:hover {
                        background-color: #27272a;
                    }
                """)
                open_btn.clicked.connect(lambda: self.action_clicked.emit(self._path, "open"))
                layout.addWidget(open_btn)

        def _get_file_icon(self) -> str:
            ext = Path(self._name).suffix.lower()
            icons = {
                '.pdf': '📕', '.doc': '📘', '.docx': '📘',
                '.xls': '📗', '.xlsx': '📗',
                '.ppt': '📙', '.pptx': '📙',
                '.jpg': '️', '.jpeg': '️', '.png': '️', '.gif': '️',
                '.mp3': '🎵', '.wav': '🎵', '.flac': '🎵',
                '.mp4': '🎬', '.mov': '🎬', '.avi': '🎬',
                '.zip': '📦', '.rar': '📦', '.7z': '📦',
                '.py': '', '.js': '', '.html': '',
                '.txt': '', '.md': '',
            }
            return icons.get(ext, '📄')

        def mousePressEvent(self, event):
            self.clicked.emit(self._path)
            super().mousePressEvent(event)


    class SearchBar(QFrame):
        """Modern search bar with professional palette"""

        search_changed = pyqtSignal(str)
        search_submitted = pyqtSignal(str)

        def __init__(self, placeholder: str = "Ara...", parent=None):
            super().__init__(parent)
            self._placeholder = placeholder
            self._setup_ui()

        def _setup_ui(self):
            self.setStyleSheet("""
                QFrame {
                    background-color: #F5F5F7;
                    border: 1px solid #D1D1D6;
                    border-radius: 8px;
                }
                QFrame:focus-within {
                    border-color: #7196A2; /* WIQO_STEEL */
                    background-color: #FFFFFF;
                }
            """)

            layout = QHBoxLayout(self)
            layout.setContentsMargins(12, 6, 12, 6)
            layout.setSpacing(8)

            # Input
            self._input = QLineEdit()
            self._input.setPlaceholderText(self._placeholder)
            self._input.setStyleSheet("""
                QLineEdit {
                    background-color: transparent;
                    border: none;
                    color: #252F33;
                    font-size: 13px;
                }
            """)
            self._input.textChanged.connect(self.search_changed.emit)
            self._input.returnPressed.connect(lambda: self.search_submitted.emit(self._input.text()))
            layout.addWidget(self._input)

            self._input.textChanged.connect(self._on_text_changed)

        def _on_text_changed(self, text: str):
            pass

        def text(self) -> str:
            return self._input.text()

        def set_text(self, text: str):
            self._input.setText(text)


    class LoadingSpinner(QWidget):
        """Animated loading spinner"""

        def __init__(self, size: int = 40, parent=None):
            super().__init__(parent)
            self._size = size
            self._angle = 0
            self._timer = QTimer(self)
            self._timer.timeout.connect(self._rotate)
            self._setup_ui()

        def _setup_ui(self):
            self.setFixedSize(self._size, self._size)

        def paintEvent(self, event):
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)

            # Draw arc
            pen = painter.pen()
            pen.setWidth(3)
            pen.setColor(QColor("#7196A2")) # WIQO_STEEL
            painter.setPen(pen)

            rect = self.rect().adjusted(4, 4, -4, -4)
            painter.drawArc(rect, int(self._angle * 16), 270 * 16)

        def _rotate(self):
            self._angle = (self._angle + 10) % 360
            self.update()

        def start(self):
            self._timer.start(30)

        def stop(self):
            self._timer.stop()


    class Toast(QFrame):
        """Toast notification with Apple-style colors"""

        def __init__(self, message: str, type_: str = "info", duration: int = 3000, parent=None):
            super().__init__(parent)
            self._message = message
            self._type = type_
            self._duration = duration
            self._setup_ui()

            QTimer.singleShot(duration, self._hide)

        def _setup_ui(self):
            colors = {
                "info": ("#7196A2", "#F2F2F7"),   # Steel
                "success": ("#34C759", "#EBF9EE"), # Apple Green
                "warning": ("#FF9500", "#FFF4E5"), # Apple Orange
                "error": ("#FF3B30", "#FFEBEA")    # Apple Red
            }

            fg, bg = colors.get(self._type, colors["info"])

            self.setStyleSheet(f"""
                QFrame {{
                    background-color: {bg};
                    border: 1px solid {fg}40;
                    border-radius: 8px;
                    padding: 10px 14px;
                }}
            """)

            layout = QHBoxLayout(self)
            layout.setContentsMargins(14, 10, 14, 10)
            layout.setSpacing(10)

            msg_label = QLabel(self._message)
            msg_label.setStyleSheet(f"color: #252F33; font-size: 13px; font-weight: 500;")
            layout.addWidget(msg_label, 1)

            close_btn = QPushButton("x")
            close_btn.setFixedSize(20, 20)
            close_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: transparent;
                    color: #8E8E93;
                    border: none;
                }}
                QPushButton:hover {{
                    color: #252F33;
                }}
            """)
            close_btn.clicked.connect(self._hide)
            layout.addWidget(close_btn)

        def _hide(self):
            self.hide()
            self.deleteLater()


    class Badge(QLabel):
        """Small discrete badge component"""

        def __init__(self, text: str, color: str = "#7196A2", parent=None):
            super().__init__(text.upper(), parent)
            self.setStyleSheet(f"""
                QLabel {{
                    background-color: {color}15;
                    color: {color};
                    padding: 2px 8px;
                    border: 1px solid {color}30;
                    border-radius: 4px;
                    font-size: 10px;
                    font-weight: 700;
                    letter-spacing: 0.5px;
                }}
            """)


    class Switch(QFrame):
        """Toggle switch component"""

        toggled = pyqtSignal(bool)

        def __init__(self, checked: bool = False, parent=None):
            super().__init__(parent)
            self._checked = checked
            self._setup_ui()

        def _setup_ui(self):
            self.setFixedSize(50, 26)
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self._update_style()

        def _update_style(self):
            if self._checked:
                self.setStyleSheet("""
                    QFrame {
                        background-color: #7196A2; /* WIQO_STEEL */
                        border-radius: 13px;
                    }
                """)
            else:
                self.setStyleSheet("""
                    QFrame {
                        background-color: #D1D1D6;
                        border-radius: 13px;
                    }
                """)

        def paintEvent(self, event):
            super().paintEvent(event)
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)

            # Draw circle
            painter.setBrush(QColor("#ffffff"))
            painter.setPen(Qt.PenStyle.NoPen)

            x = 27 if self._checked else 3
            painter.drawEllipse(x, 3, 20, 20)

        def mousePressEvent(self, event):
            self._checked = not self._checked
            self._update_style()
            self.update()
            self.toggled.emit(self._checked)
            super().mousePressEvent(event)

        def is_checked(self) -> bool:
            return self._checked

        def set_checked(self, checked: bool):
            self._checked = checked
            self._update_style()
            self.update()


    class SectionHeader(QWidget):
        """Section header with title and optional action"""

        def __init__(self, title: str, action_text: str = None, parent=None):
            super().__init__(parent)
            self._title = title
            self._action_text = action_text
            self._setup_ui()

        def _setup_ui(self):
            layout = QHBoxLayout(self)
            layout.setContentsMargins(0, 0, 0, 0)

            title_label = QLabel(self._title)
            title_label.setStyleSheet("""
                font-size: 16px;
                font-weight: 700;
                color: #252F33;
                font-family: "SF Pro Display";
            """)
            layout.addWidget(title_label)

            layout.addStretch()

            if self._action_text:
                action_btn = QPushButton(self._action_text)
                action_btn.setStyleSheet("""
                    QPushButton {
                        background-color: transparent;
                        color: #7196A2;
                        border: none;
                        font-size: 13px;
                        font-weight: 600;
                    }
                    QPushButton:hover {
                        color: #517079;
                    }
                """)
                layout.addWidget(action_btn)
                self._action_btn = action_btn


    class Divider(QFrame):
        """Horizontal divider line"""

        def __init__(self, parent=None):
            super().__init__(parent)
            self.setFixedHeight(1)
            self.setStyleSheet("background-color: #E5E5EA; border: none;")


    class EmptyState(QWidget):
        """Empty state placeholder without emojis"""

        def __init__(self, icon: str, title: str, description: str = "", action_text: str = None, parent=None):
            super().__init__(parent)
            self._icon = icon # Kept for compatibility but hidden or simplified
            self._title = title
            self._description = description
            self._action_text = action_text
            self._setup_ui()

        def _setup_ui(self):
            layout = QVBoxLayout(self)
            layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.setSpacing(12)

            title_label = QLabel(self._title)
            title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            title_label.setStyleSheet("font-size: 18px; font-weight: 700; color: #252F33; font-family: 'SF Pro Display';")
            layout.addWidget(title_label)

            if self._description:
                desc_label = QLabel(self._description)
                desc_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                desc_label.setStyleSheet("font-size: 13px; color: #8E8E93;")
                desc_label.setWordWrap(True)
                layout.addWidget(desc_label)

            if self._action_text:
                from ui.components import AnimatedButton
                action_btn = AnimatedButton(self._action_text, primary=True)
                layout.addWidget(action_btn, alignment=Qt.AlignmentFlag.AlignCenter)
                self._action_btn = action_btn


    from PyQt6.QtGui import QPainter, QPen, QPainterPath, QLinearGradient

    class LatencyGraph(QFrame):
        """Minimalistic line chart for visualizing real-time metrics (v8.0)"""

        def __init__(self, parent=None):
            super().__init__(parent)
            self.setMinimumHeight(150)
            self._values = [0] * 20
            self._max_value = 5000 # Default max 5s
            
            self.setStyleSheet("""
                QFrame {
                    background: rgba(255, 255, 255, 0.03);
                    border: 1px solid rgba(255, 255, 255, 0.05);
                    border-radius: 12px;
                }
            """)

        def add_value(self, value: float):
            """Add a new data point and update the graph"""
            self._values.pop(0)
            self._values.append(value)
            self._max_value = max(max(self._values) * 1.2, 1000) # Dynamic scaling
            self.update()

        def paintEvent(self, event):
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            
            w = self.width()
            h = self.height()
            padding = 20
            
            draw_w = w - 2 * padding
            draw_h = h - 2 * padding
            
            # Draw grid lines (horizontal)
            painter.setPen(QPen(QColor(255, 255, 255, 20), 1))
            for i in range(4):
                y = padding + (draw_h * i / 3)
                painter.drawLine(int(padding), int(y), int(w - padding), int(y))

            # Draw the line path
            if self._values:
                path = QPainterPath()
                step = draw_w / (len(self._values) - 1)
                
                points = []
                for i, val in enumerate(self._values):
                    x = padding + (i * step)
                    y = padding + draw_h - (val / self._max_value * draw_h)
                    y = min(padding + draw_h, max(padding, y)) # Clamping
                    points.append((x, y))
                    
                    if i == 0:
                        path.moveTo(x, y)
                    else:
                        # Smooth curves (Bézier-ish)
                        prev_x, prev_y = points[i-1]
                        cp1_x = prev_x + step / 2
                        cp2_x = x - step / 2
                        path.cubicTo(cp1_x, prev_y, cp2_x, y, x, y)
                
                # Draw gradient fill
                fill_path = QPainterPath(path)
                fill_path.lineTo(w - padding, h - padding)
                fill_path.lineTo(padding, h - padding)
                fill_path.closeSubpath()
                
                gradient = QLinearGradient(0, padding, 0, h - padding)
                gradient.setColorAt(0, QColor(113, 150, 162, 80)) # WIQO_STEEL
                gradient.setColorAt(1, QColor(113, 150, 162, 0))
                painter.fillPath(fill_path, gradient)
                
                # Draw the stroke
                painter.setPen(QPen(QColor(113, 150, 162), 2))
                painter.drawPath(path)
                
                # Draw current point dot
                last_x, last_y = points[-1]
                painter.setBrush(QColor(113, 150, 162))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(int(last_x - 4), int(last_y - 4), 8, 8)


    class SectionHeader(QLabel):
        """Clean header for UI sections"""
        def __init__(self, text: str, parent=None):
            super().__init__(text, parent)
            self.setFont(QFont("SF Pro Display", 16, QFont.Weight.Bold))
            self.setStyleSheet("color: #252F33; border: none; margin-bottom: 8px;")


    class PulseLabel(QLabel):
        """Label with breathing/pulse opacity animation"""
        def __init__(self, text: str, parent=None):
            super().__init__(text, parent)
            self.setStyleSheet("color: #8E8E93; font-size: 13px; border: none;")
            self._effect = QGraphicsOpacityEffect(self)
            self.setGraphicsEffect(self._effect)
            
            self._anim = QPropertyAnimation(self._effect, b"opacity")
            self._anim.setDuration(1500)
            self._anim.setStartValue(0.3)
            self._anim.setEndValue(1.0)
            self._anim.setLoopCount(-1)
            self._anim.setEasingCurve(QEasingCurve.Type.InOutSine)

        def start(self):
            self._anim.start()

        def stop(self):
            self._anim.stop()
            self._effect.setOpacity(1.0)


    class Switch(QWidget):
        """Modern toggle switch component"""
        toggled = pyqtSignal(bool)

        def __init__(self, checked: bool = False, parent=None):
            if isinstance(checked, QWidget):
                parent = checked
                checked = False
            super().__init__(parent)
            self.setFixedSize(44, 24)
            self._checked = checked
            self._thumb_pos = 22 if self._checked else 2
            self._anim = QPropertyAnimation(self, b"thumb_pos")
            self._anim.setDuration(200)

        @pyqtProperty(int)
        def thumb_pos(self): return self._thumb_pos
        @thumb_pos.setter
        def thumb_pos(self, pos):
            self._thumb_pos = pos
            self.update()

        def mousePressEvent(self, event):
            self._checked = not self._checked
            self._anim.setEndValue(22 if self._checked else 2)
            self._anim.start()
            self.toggled.emit(self._checked)
            super().mousePressEvent(event)

        def is_checked(self) -> bool:
            return bool(self._checked)

        def set_checked(self, checked: bool):
            self._checked = bool(checked)
            self.thumb_pos = 22 if self._checked else 2
            self.toggled.emit(self._checked)
            self.update()

        def paintEvent(self, event):
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            
            # Background
            bg_color = QColor("#7196A2") if self._checked else QColor("#D1D1D6")
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(bg_color)
            p.drawRoundedRect(0, 0, self.width(), self.height(), 12, 12)
            
            # Thumb
            p.setBrush(QColor("white"))
            p.drawEllipse(int(self._thumb_pos), 2, 20, 20)
