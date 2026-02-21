import sys
import os
from typing import Optional, Callable, List, Any
from pathlib import Path
from datetime import datetime

try:
    from PyQt6.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
        QFrame, QSizePolicy, QLineEdit, QTextEdit, QScrollArea,
        QStackedWidget, QProgressBar
    )
    from PyQt6.QtCore import Qt, pyqtSignal, QPropertyAnimation, QTimer, QSize, pyqtProperty
    from PyQt6.QtGui import QFont, QColor, QIcon, QPixmap, QPainter, QPainterPath, QPen, QLinearGradient
    PYQT_AVAILABLE = True
except ImportError:
    PYQT_AVAILABLE = False

class ElyanTheme:
    """Standardized styling tokens for Elyan UI."""
    ACCENT_BLUE = "#0F9AFE"
    NEUTRAL_BLUE = "#8E8E93"
    TEXT_PRIMARY = "#1C1C1E"
    TEXT_SECONDARY = "#8E8E93"
    BG_LIGHT = "#F8FBFF"
    BG_SECONDARY = "#F2F2F7"
    CARD_BG = "#FFFFFF"
    BORDER_LIGHT = "#E5E5EA"
    FONT_UI = ".AppleSystemUIFont"
    FONT_DISPLAY = ".AppleSystemUIFont"
    FONT_MONO = "SF Mono"

if PYQT_AVAILABLE:
    class Switch(QWidget):
        toggled = pyqtSignal(bool)
        def __init__(self, checked: bool = False, parent=None):
            super().__init__(parent)
            self.setFixedSize(44, 24)
            self._checked = checked
            self._thumb_pos = 22 if self._checked else 2
            self._anim = QPropertyAnimation(self, b"thumb_pos")
            self._anim.setDuration(200)
        @pyqtProperty(int)
        def thumb_pos(self): return self._thumb_pos
        @thumb_pos.setter
        def thumb_pos(self, pos): self._thumb_pos = pos; self.update()
        def set_checked(self, checked: bool):
            self._checked = bool(checked)
            self._thumb_pos = 22 if self._checked else 2
            self.update()
        def is_checked(self) -> bool:
            return self._checked
        def mousePressEvent(self, event):
            self._checked = not self._checked
            self._anim.setEndValue(22 if self._checked else 2)
            self._anim.start()
            self.toggled.emit(self._checked)
        def paintEvent(self, event):
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            bg_color = QColor("#0F9AFE") if self._checked else QColor("#D1D1D6")
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(bg_color)
            p.drawRoundedRect(0, 0, self.width(), self.height(), 12, 12)
            p.setBrush(QColor("white")); p.drawEllipse(int(self._thumb_pos), 2, 20, 20)

    class SidebarButton(QPushButton):
        def __init__(self, icon: str, text: str, parent=None):
            super().__init__(parent)
            self._text = text; self._active = False
            self.setText(self._text); self.setFixedHeight(42)
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.update_style()
        def update_style(self):
            if self._active:
                self.setStyleSheet("QPushButton { background-color: #EBF5FF; color: #0F9AFE; border: none; border-left: 3px solid #0F9AFE; text-align: left; padding-left: 17px; font-weight: 600; font-size: 13px; }")
            else:
                self.setStyleSheet("QPushButton { background-color: transparent; color: #8E8E93; border: none; text-align: left; padding-left: 17px; font-weight: 500; font-size: 13px; }")
        def set_active(self, active: bool): self._active = active; self.update_style()

    class StatCard(QFrame):
        def __init__(self, icon: str, value: str, label: str, color: str = "#0F9AFE", parent=None):
            super().__init__(parent)
            self.setObjectName("stat_card")
            self.setStyleSheet("#stat_card { background-color: white; border: 1px solid #E5E5EA; border-radius: 14px; }")
            l = QVBoxLayout(self); l.setContentsMargins(18, 14, 18, 16)
            self._v = QLabel(value); self._v.setStyleSheet("font-size: 24px; font-weight: 700; color: #1C1C1E;")
            lbl = QLabel(label.upper()); lbl.setStyleSheet("color: #8E8E93; font-size: 10px; font-weight: 700;")
            l.addWidget(lbl); l.addWidget(self._v)
        def set_value(self, v): self._v.setText(v)

    class GlassFrame(QFrame):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.setStyleSheet("background-color: white; border: 1px solid #E5E5EA; border-radius: 12px;")

    class SectionHeader(QLabel):
        def __init__(self, text: str, parent=None):
            super().__init__(text, parent)
            self.setStyleSheet("font-size: 16px; font-weight: 700; color: #252F33; margin-bottom: 8px;")

    class Divider(QFrame):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.setFixedHeight(1); self.setStyleSheet("background-color: #E5E5EA;")

    class LatencyGraph(QFrame):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.setMinimumHeight(150); self._vals = [0]*20
            self.setStyleSheet("background: #FFFFFF; border: 1px solid #E5E5EA; border-radius: 12px;")
        def add_value(self, v): self._vals.pop(0); self._vals.append(v); self.update()
        def paintEvent(self, e):
            p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
            if not self._vals: return
            path = QPainterPath(); step = self.width() / 19
            path.moveTo(0, self.height() - (self._vals[0]/5000 * self.height()))
            for i, v in enumerate(self._vals[1:], 1):
                path.lineTo(i*step, self.height() - (v/5000 * self.height()))
            p.setPen(QPen(QColor("#0F9AFE"), 2)); p.drawPath(path)

    class AnimatedButton(QPushButton):
        def __init__(self, text: str, primary: bool = True, parent=None):
            super().__init__(text, parent)
            if primary: self.setStyleSheet("QPushButton { background-color: #0F9AFE; color: white; border-radius: 8px; font-weight: 600; padding: 10px; }")
            else: self.setStyleSheet("QPushButton { background-color: #F5F5F7; color: #252F33; border: 1px solid #D1D1D6; border-radius: 8px; padding: 10px; }")

    class PulseLabel(QLabel):
        def __init__(self, text: str, parent=None):
            super().__init__(text, parent)
            self._timer = QTimer(self); self._timer.timeout.connect(self._tick)
            self._on = True
        def _tick(self): self._on = not self._on; self.setStyleSheet(f"color: {'#0F9AFE' if self._on else '#8E8E93'}")
        def start(self): self._timer.start(500)
        def stop(self): self._timer.stop()

    class FileItem(QFrame):
        def __init__(self, text: str, time_str: str, parent=None):
            super().__init__(parent)
            l = QHBoxLayout(self); l.addWidget(QLabel(text)); l.addStretch(); l.addWidget(QLabel(time_str))
