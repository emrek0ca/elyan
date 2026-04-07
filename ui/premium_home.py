from __future__ import annotations

import time
from typing import Any

from PyQt6.QtCore import Qt, QTimer, QRectF, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QLinearGradient
from PyQt6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QToolButton,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ui.branding import load_brand_pixmap
from ui.home_data import LiveHomeDataService
from ui.home_models import ActivityEntry, HomeSnapshot, MetricTile


def _shadow(blur: int = 28, y: int = 8, alpha: int = 22) -> QGraphicsDropShadowEffect:
    effect = QGraphicsDropShadowEffect()
    effect.setBlurRadius(blur)
    effect.setOffset(0, y)
    effect.setColor(QColor(17, 19, 24, alpha))
    return effect


class PillButton(QPushButton):
    def __init__(self, text: str, *, active: bool = False, parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(30)
        self.setStyleSheet(self._style(active))

    @staticmethod
    def _style(active: bool) -> str:
        if active:
            return """
                QPushButton {
                    background: #FFFFFF;
                    color: #111318;
                    border: 1px solid #DDE5F0;
                    border-radius: 15px;
                    padding: 0 12px;
                    font-size: 11px;
                    font-weight: 600;
                }
            """
        return """
            QPushButton {
                background: #F7F8FA;
                color: #5D6675;
                border: 1px solid #E8ECF2;
                border-radius: 15px;
                padding: 0 12px;
                font-size: 11px;
                font-weight: 500;
            }
            QPushButton:hover {
                background: #FFFFFF;
                color: #111318;
            }
        """


class MetricCard(QFrame):
    def __init__(self, metric: MetricTile, parent=None):
        super().__init__(parent)
        self.setObjectName("metric_card")
        self.setStyleSheet(
            """
            QFrame#metric_card {
                background: #FFFFFF;
                border: 1px solid #E8ECF2;
                border-radius: 18px;
            }
            """
        )
        self.setMinimumHeight(102)
        self.setGraphicsEffect(_shadow(8, 2, 5))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(8)
        self._icon = QLabel(metric.icon[:1].upper() if metric.icon else "•")
        self._icon.setFixedSize(26, 26)
        self._icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon.setStyleSheet(
            "QLabel { background: #EAF2FF; color: #4C82FF; border-radius: 13px; font-size: 12px; font-weight: 700; }"
        )
        top.addWidget(self._icon)
        top.addStretch()
        self._delta = QLabel(metric.delta)
        self._delta.setStyleSheet("color: #8B95A7; font-size: 10px;")
        self._delta.setVisible(bool(metric.delta))
        top.addWidget(self._delta)
        layout.addLayout(top)

        self._value = QLabel(metric.value)
        self._value.setFont(QFont(".AppleSystemUIFont", 20, QFont.Weight.DemiBold))
        self._value.setStyleSheet("color: #111318; border: none; letter-spacing: -0.5px;")
        layout.addWidget(self._value)

        self._label = QLabel(metric.label)
        self._label.setFont(QFont(".AppleSystemUIFont", 9, QFont.Weight.Medium))
        self._label.setStyleSheet("color: #5D6675; border: none; text-transform: uppercase; letter-spacing: 0.8px;")
        layout.addWidget(self._label)

        self._hint = QLabel(metric.hint)
        self._hint.setWordWrap(True)
        self._hint.setStyleSheet("color: #8B95A7; border: none; font-size: 10px;")
        layout.addWidget(self._hint)

    def update_metric(self, metric: MetricTile) -> None:
        self._icon.setText(metric.icon[:1].upper() if metric.icon else "•")
        self._value.setText(metric.value)
        self._label.setText(metric.label)
        self._hint.setText(metric.hint)
        self._delta.setText(metric.delta)
        self._delta.setVisible(bool(metric.delta))


class LiquidGlassCard(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            """
            QFrame {
                background: rgba(255, 255, 255, 0.72);
                border: 1px solid rgba(255, 255, 255, 0.55);
                border-radius: 24px;
            }
            """
        )
        self.setGraphicsEffect(_shadow(20, 6, 14))


class OperatorStatusCard(LiquidGlassCard):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(108)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        self._eyebrow = QLabel(title.upper())
        self._eyebrow.setStyleSheet("color: rgba(61, 73, 89, 0.74); font-size: 10px; font-weight: 700; letter-spacing: 0.9px;")
        layout.addWidget(self._eyebrow)

        self._status = QLabel("Healthy")
        self._status.setFont(QFont(".AppleSystemUIFont", 18, QFont.Weight.DemiBold))
        self._status.setStyleSheet("color: #162033;")
        layout.addWidget(self._status)

        self._detail = QLabel("")
        self._detail.setWordWrap(True)
        self._detail.setStyleSheet("color: rgba(52, 62, 78, 0.72); font-size: 11px;")
        layout.addWidget(self._detail)

    def update_state(self, status: str, detail: str) -> None:
        low = str(status or "unknown").lower()
        palette = {
            "healthy": ("#162033", "rgba(67, 135, 97, 0.18)", "rgba(75, 145, 105, 0.35)"),
            "degraded": ("#6D4E00", "rgba(255, 206, 99, 0.24)", "rgba(231, 174, 42, 0.4)"),
            "unavailable": ("#6E2222", "rgba(255, 160, 160, 0.24)", "rgba(224, 106, 106, 0.4)"),
            "failed": ("#6E2222", "rgba(255, 160, 160, 0.24)", "rgba(224, 106, 106, 0.4)"),
        }.get(low, ("#23324A", "rgba(194, 207, 228, 0.24)", "rgba(162, 180, 206, 0.4)"))
        fg, glow, border = palette
        self.setStyleSheet(
            f"""
            QFrame {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(255,255,255,0.78),
                    stop:1 {glow});
                border: 1px solid {border};
                border-radius: 24px;
            }}
            """
        )
        self._status.setText(str(status or "Unknown").title())
        self._status.setStyleSheet(f"color: {fg};")
        self._detail.setText(detail)


class HeroRobotFrame(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(274)
        self.setStyleSheet(
            """
            QFrame {
                background: #FCFCFD;
                border: 1px solid #EEF2F7;
                border-radius: 28px;
            }
            """
        )
        self.setGraphicsEffect(_shadow(16, 4, 6))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(0)
        layout.addStretch()
        robot = QLabel()
        pix = load_brand_pixmap(size=220)
        if not pix.isNull():
            robot.setPixmap(pix)
            robot.setAlignment(Qt.AlignmentFlag.AlignCenter)
            robot.setMinimumHeight(220)
        layout.addWidget(robot, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch()


class InsightChart(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(166)
        self.setStyleSheet(
            """
            QFrame {
                background: #FFFFFF;
                border: 1px solid #E8ECF2;
                border-radius: 24px;
            }
            """
        )
        self.setGraphicsEffect(_shadow(11, 3, 7))
        self._points: list[float] = [220, 248, 230, 278, 260, 240]
        self._success: list[float] = [94, 95, 96, 96, 97, 98]
        self._actions: list[float] = [42, 44, 50, 48, 54, 58]
        self._title = "Performance trend"

    def set_series(self, points: list[float], success: list[float], actions: list[float]) -> None:
        if points:
            self._points = list(points)[-24:]
        if success:
            self._success = list(success)[-24:]
        if actions:
            self._actions = list(actions)[-24:]
        self.update()

    def paintEvent(self, event):  # noqa: N802
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(12, 14, -12, -14)
        header_h = 34
        chart_rect = QRectF(rect.x(), rect.y() + header_h, rect.width(), rect.height() - header_h)

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#FFFFFF"))
        p.drawRoundedRect(rect, 22, 22)

        p.setPen(QColor("#111318"))
        p.setFont(QFont(".AppleSystemUIFont", 13, QFont.Weight.DemiBold))
        p.drawText(rect.x(), rect.y() + 17, "Performance trend")
        p.setPen(QColor("#8B95A7"))
        p.setFont(QFont(".AppleSystemUIFont", 9))
        p.drawText(rect.right() - 92, rect.y() + 17, "Live signal")

        if not self._points:
            return

        series = [
            (self._points, QColor("#4C82FF"), 1.9),
            (self._success, QColor("#16A34A"), 1.4),
        ]

        max_val = max(max(s) for s, _, _ in series)
        min_val = min(min(s) for s, _, _ in series)
        span = max(max_val - min_val, 1.0)
        pad = 16
        draw_rect = chart_rect.adjusted(pad, 6, -pad, -10)
        width = draw_rect.width()
        height = draw_rect.height()

        for values, color, stroke in series:
            if len(values) < 2:
                continue
            path = QPainterPath()
            for i, value in enumerate(values):
                x = draw_rect.left() + (width * i / (len(values) - 1))
                normalized = (value - min_val) / span
                y = draw_rect.bottom() - (normalized * height)
                if i == 0:
                    path.moveTo(x, y)
                else:
                    path.lineTo(x, y)
            p.setPen(QPen(color, stroke))
            p.drawPath(path)

        p.setPen(QColor("#E8ECF2"))
        p.drawRoundedRect(draw_rect, 16, 16)


class ActivityRow(QFrame):
    def __init__(self, entry: ActivityEntry, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            """
            QFrame {
                background: #FFFFFF;
                border: 1px solid #EEF1F6;
                border-radius: 16px;
            }
            """
        )
        self.setMinimumHeight(66)
        self.setGraphicsEffect(_shadow(6, 1, 4))
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(10)

        badge = QLabel(entry.title[:1].upper())
        badge.setFixedSize(28, 28)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tone_bg = {
            "success": "#E8F8EE",
            "warning": "#FFF4DD",
            "error": "#FEE4E2",
            "info": "#EAF2FF",
        }.get(entry.status, "#EAF2FF")
        tone_tx = {
            "success": "#16A34A",
            "warning": "#C47C00",
            "error": "#EF4444",
            "info": "#4C82FF",
        }.get(entry.status, "#4C82FF")
        badge.setStyleSheet(
            f"QLabel {{ background: {tone_bg}; color: {tone_tx}; border-radius: 14px; font-size: 11px; font-weight: 700; }}"
        )
        layout.addWidget(badge)

        content = QVBoxLayout()
        content.setSpacing(2)
        title = QLabel(entry.title)
        title.setStyleSheet("color: #111318; font-size: 12px; font-weight: 600; border: none;")
        subtitle = QLabel(entry.subtitle)
        subtitle.setStyleSheet("color: #8B95A7; font-size: 10px; border: none;")
        content.addWidget(title)
        content.addWidget(subtitle)
        layout.addLayout(content, 1)

        meta = QLabel(entry.timestamp)
        meta.setStyleSheet("color: #A7B0BE; font-size: 9px; border: none;")
        layout.addWidget(meta)


class PremiumHomeView(QWidget):
    quick_mode_requested = pyqtSignal(str, str)
    settings_requested = pyqtSignal()

    def __init__(self, data_service: Any | None = None, parent=None):
        super().__init__(parent)
        self._data_service = data_service or LiveHomeDataService()
        self._snapshot = HomeSnapshot.empty()
        self._activity_filter = "all"
        self._setup_ui()
        self._set_status_style("success")
        self.set_loading()
        self.refresh()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(5000)

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(10)

        shell = LiquidGlassCard()
        shell.setObjectName("premium_home_shell")
        shell.setStyleSheet(
            """
            QFrame#premium_home_shell {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(255,255,255,0.78),
                    stop:0.45 rgba(245,249,255,0.68),
                    stop:1 rgba(236,244,255,0.60));
                border: 1px solid rgba(255, 255, 255, 0.58);
                border-radius: 32px;
            }
            """
        )
        shell.setGraphicsEffect(_shadow(14, 4, 6))
        shell_layout = QHBoxLayout(shell)
        shell_layout.setContentsMargins(16, 16, 16, 16)
        shell_layout.setSpacing(14)

        center = QVBoxLayout()
        center.setSpacing(12)
        center.setContentsMargins(0, 0, 0, 0)

        topbar = QHBoxLayout()
        topbar.setContentsMargins(0, 0, 0, 0)
        topbar.setSpacing(6)
        title = QLabel("Home")
        title.setFont(QFont(".AppleSystemUIFont", 17, QFont.Weight.DemiBold))
        title.setStyleSheet("color: #2B3441; border: none;")
        topbar.addWidget(title)
        topbar.addStretch()
        menu_button = QToolButton()
        menu_button.setText("⋯")
        menu_button.setCursor(Qt.CursorShape.PointingHandCursor)
        menu_button.setFixedSize(28, 28)
        menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu_button.setStyleSheet(
            """
            QToolButton {
                background: #FFFFFF;
                color: #5D6675;
                border: 1px solid #E8ECF2;
                border-radius: 14px;
                font-size: 16px;
                font-weight: 600;
                padding-bottom: 1px;
            }
            QToolButton:hover { background: #F7F8FA; color: #111318; }
            """
        )
        menu = QMenu(menu_button)
        refresh_action = menu.addAction("Refresh now")
        refresh_action.triggered.connect(lambda checked=False: self.refresh())
        settings_action = menu.addAction("Open settings")
        settings_action.triggered.connect(lambda checked=False: self.settings_requested.emit())
        menu_button.setMenu(menu)
        topbar.addWidget(menu_button)
        center.addLayout(topbar)

        hero = QFrame()
        hero.setStyleSheet("QFrame { background: transparent; border: none; }")
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(0, 0, 0, 0)
        hero_layout.setSpacing(0)
        hero_layout.addWidget(HeroRobotFrame(), 0, Qt.AlignmentFlag.AlignHCenter)
        center.addWidget(hero)

        card = LiquidGlassCard()
        card.setStyleSheet(
            """
            QFrame {
                background: rgba(255, 255, 255, 0.62);
                border: 1px solid rgba(255, 255, 255, 0.52);
                border-radius: 28px;
            }
            """
        )
        card.setGraphicsEffect(_shadow(11, 3, 5))
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(18, 16, 18, 16)
        card_layout.setSpacing(12)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        title_block = QVBoxLayout()
        title_block.setSpacing(1)
        title_block.setContentsMargins(0, 0, 0, 0)
        brand_title = QLabel("Command")
        brand_title.setFont(QFont(".AppleSystemUIFont", 18, QFont.Weight.DemiBold))
        brand_title.setStyleSheet("color: #2B3441; border: none;")
        brand_subtitle = QLabel("Use natural language or a quick action.")
        brand_subtitle.setStyleSheet("color: #8B95A7; border: none; font-size: 10px;")
        title_block.addWidget(brand_title)
        title_block.addWidget(brand_subtitle)
        header.addLayout(title_block)
        header.addStretch()
        actions_button = QToolButton()
        actions_button.setText("Actions ▾")
        actions_button.setCursor(Qt.CursorShape.PointingHandCursor)
        actions_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        actions_button.setFixedHeight(28)
        actions_button.setStyleSheet(
            """
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
            """
        )
        actions_menu = QMenu(actions_button)
        for label in ("Report", "Summarize", "Search docs", "Generate image"):
            action = actions_menu.addAction(label)
            action.triggered.connect(lambda checked=False, text=label: self.quick_mode_requested.emit("custom", text))
        open_settings = actions_menu.addAction("Open settings")
        open_settings.triggered.connect(lambda checked=False: self.settings_requested.emit())
        actions_button.setMenu(actions_menu)
        header.addWidget(actions_button)
        card_layout.addLayout(header)

        self._command = QLineEdit()
        self._command.setPlaceholderText("Ask a question or type a command...")
        self._command.setMinimumHeight(54)
        self._command.setFont(QFont(".AppleSystemUIFont", 13))
        self._command.setStyleSheet(
            """
            QLineEdit {
                background: #FFFFFF;
                border: 1px solid #E8ECF2;
                border-radius: 26px;
                padding: 0 16px;
                color: #111318;
            }
            QLineEdit:focus {
                border: 1px solid #C9D6F5;
            }
            QLineEdit::placeholder { color: #A7B0BE; }
            """
        )
        self._command.returnPressed.connect(self._submit_command)
        card_layout.addWidget(self._command)

        chips = QHBoxLayout()
        chips.setSpacing(8)
        for label in ("Report", "Summarize", "Search"):
            btn = PillButton(label, active=False)
            btn.clicked.connect(lambda checked=False, text=label: self.quick_mode_requested.emit("custom", text))
            chips.addWidget(btn)
        chips.addStretch()
        card_layout.addLayout(chips)
        center.addWidget(card)

        insight_row = QGridLayout()
        insight_row.setHorizontalSpacing(14)
        insight_row.setVerticalSpacing(14)
        self._metric_cards: list[MetricCard] = []
        for i, metric in enumerate((self._snapshot.system_metrics + self._snapshot.ai_metrics)[:4]):
            widget = MetricCard(metric)
            self._metric_cards.append(widget)
            insight_row.addWidget(widget, i // 2, i % 2)
        self._insight_grid = insight_row
        center.addLayout(insight_row)

        self._chart = InsightChart()
        center.addWidget(self._chart)

        shell_layout.addLayout(center, 1)

        right = QWidget()
        right.setFixedWidth(324)
        right_layout = QVBoxLayout(right)
        right_layout.setSpacing(10)
        right_layout.setContentsMargins(0, 0, 0, 0)
        activity_header = QHBoxLayout()
        activity_header.setContentsMargins(0, 0, 0, 0)
        activity_header.setSpacing(8)
        title = QLabel("Activity")
        title.setFont(QFont(".AppleSystemUIFont", 18, QFont.Weight.DemiBold))
        title.setStyleSheet("color: #2B3441; border: none;")
        activity_header.addWidget(title)
        activity_header.addStretch()
        self._activity_filter_button = QToolButton()
        self._activity_filter_button.setText("All ▾")
        self._activity_filter_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._activity_filter_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._activity_filter_button.setFixedHeight(28)
        self._activity_filter_button.setStyleSheet(
            """
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
            """
        )
        activity_menu = QMenu(self._activity_filter_button)
        for label, key in (("All", "all"), ("Tasks", "run"), ("System", "system"), ("Tools", "tool")):
            action = activity_menu.addAction(label)
            action.triggered.connect(lambda checked=False, value=key, button_label=label: self._set_activity_filter(value, button_label))
        self._activity_filter_button.setMenu(activity_menu)
        activity_header.addWidget(self._activity_filter_button)
        right_layout.addLayout(activity_header)

        self._status_shell = LiquidGlassCard()
        status_layout = QVBoxLayout(self._status_shell)
        status_layout.setContentsMargins(10, 10, 10, 10)
        status_layout.setSpacing(8)
        status_title = QLabel("Operator Surface")
        status_title.setFont(QFont(".AppleSystemUIFont", 16, QFont.Weight.DemiBold))
        status_title.setStyleSheet("color: #23324A; border: none;")
        status_layout.addWidget(status_title)
        self._operator_cards = {
            "mobile_dispatch": OperatorStatusCard("Mobile dispatch"),
            "computer_use": OperatorStatusCard("Computer use"),
            "internet_reach": OperatorStatusCard("Internet reach"),
            "document_ingest": OperatorStatusCard("Document ingest"),
            "speed_runtime": OperatorStatusCard("Speed runtime"),
        }
        for widget in self._operator_cards.values():
            status_layout.addWidget(widget)
        right_layout.addWidget(self._status_shell)

        self._activity_shell = LiquidGlassCard()
        self._activity_shell.setStyleSheet(
            """
            QFrame {
                background: rgba(255, 255, 255, 0.66);
                border: 1px solid rgba(255, 255, 255, 0.52);
                border-radius: 24px;
            }
            """
        )
        self._activity_shell.setGraphicsEffect(_shadow(12, 3, 5))
        activity_layout = QVBoxLayout(self._activity_shell)
        activity_layout.setContentsMargins(10, 10, 10, 10)
        activity_layout.setSpacing(8)
        self._activity_list = QListWidget()
        self._activity_list.setStyleSheet(
            """
            QListWidget {
                background: transparent;
                border: none;
                padding: 0;
            }
            QListWidget::item {
                border: none;
                margin-bottom: 5px;
            }
            """
        )
        activity_layout.addWidget(self._activity_list)
        right_layout.addWidget(self._activity_shell, 1)

        shell_layout.addWidget(right)
        root.addWidget(shell, 1)

        footer = QHBoxLayout()
        footer.setContentsMargins(6, 0, 6, 0)
        footer.setSpacing(8)
        self._status_chip = QLabel("Bot hazır")
        self._status_chip.setStyleSheet(
            "QLabel { background: #EAF2FF; color: #4C82FF; border-radius: 14px; padding: 6px 12px; font-size: 12px; font-weight: 600; }"
        )
        footer.addWidget(self._status_chip, 0, Qt.AlignmentFlag.AlignLeft)
        self._backend_chip = QLabel("Python core")
        self._backend_chip.setStyleSheet(
            "QLabel { background: #FFFFFF; color: #5D6675; border: 1px solid #E8ECF2; border-radius: 14px; padding: 6px 12px; font-size: 12px; font-weight: 500; }"
        )
        footer.addWidget(self._backend_chip, 0, Qt.AlignmentFlag.AlignLeft)
        self._workspace_chip = QLabel("Auto-managed")
        self._workspace_chip.setStyleSheet(
            "QLabel { background: #FFFFFF; color: #5D6675; border: 1px solid #E8ECF2; border-radius: 14px; padding: 6px 12px; font-size: 12px; }"
        )
        footer.addWidget(self._workspace_chip, 0, Qt.AlignmentFlag.AlignLeft)
        self._operator_chip = QLabel("Operator ready")
        self._operator_chip.setStyleSheet(
            "QLabel { background: rgba(255,255,255,0.78); color: #23324A; border: 1px solid rgba(255,255,255,0.56); border-radius: 14px; padding: 6px 12px; font-size: 12px; font-weight: 600; }"
        )
        footer.addWidget(self._operator_chip, 0, Qt.AlignmentFlag.AlignLeft)
        self._lane_chip = QLabel("Lane unknown")
        self._lane_chip.setStyleSheet(
            "QLabel { background: rgba(234,242,255,0.88); color: #1D4ED8; border: 1px solid rgba(191,219,254,0.9); border-radius: 14px; padding: 6px 12px; font-size: 12px; font-weight: 600; }"
        )
        footer.addWidget(self._lane_chip, 0, Qt.AlignmentFlag.AlignLeft)
        footer.addStretch()
        self._updated_chip = QLabel("")
        self._updated_chip.setStyleSheet("QLabel { color: #A7B0BE; font-size: 12px; }")
        footer.addWidget(self._updated_chip, 0, Qt.AlignmentFlag.AlignRight)
        root.addLayout(footer)

    def _submit_command(self) -> None:
        text = str(self._command.text() or "").strip()
        if not text:
            return
        self.quick_mode_requested.emit("custom", text)
        self._command.clear()

    def refresh(self) -> None:
        try:
            snapshot = self._data_service.fetch_snapshot()
            if snapshot:
                self.update_snapshot(snapshot)
        except Exception as exc:
            self.set_error(str(exc))

    def set_error(self, message: str) -> None:
        self._set_status_style("error")
        self._status_chip.setText("Degraded")
        self._set_backend_style("warning")
        self._backend_chip.setText("Python fallback")
        self._updated_chip.setText(str(message or "Failed to load live data"))

    def set_loading(self) -> None:
        self._set_status_style("neutral")
        self._status_chip.setText("Loading")
        self._set_backend_style("neutral")
        self._backend_chip.setText("Runtime check")
        self._updated_chip.setText("")

    def update_snapshot(self, snapshot: HomeSnapshot) -> None:
        self._snapshot = snapshot
        self._set_status_style("success" if not snapshot.error else "error")
        self._status_chip.setText(snapshot.connection_label)
        self._status_chip.setToolTip(snapshot.agent_state or snapshot.connection_label)
        self._set_backend_style(snapshot.backend_tone)
        self._backend_chip.setText(snapshot.backend_label)
        self._backend_chip.setToolTip(
            "\n".join(
                f"{state.label}: {state.detail or ('Active' if state.active else 'Standby')}"
                for state in snapshot.backend_states
            )
        )
        self._workspace_chip.setText(snapshot.workspace_label)
        operator_status = dict(snapshot.operator_status or {})
        operator_summary = dict(operator_status.get("summary") or {})
        self._operator_chip.setText(f"Operator {str(operator_status.get('status') or 'unknown').title()}")
        self._operator_chip.setToolTip("\n".join(f"{key}: {dict(value or {}).get('status', 'unknown')}" for key, value in operator_summary.items()))
        speed = dict(operator_summary.get("speed_runtime") or {})
        lane = str(speed.get("current_lane") or "unknown").replace("_", " ")
        verification = str(speed.get("verification_state") or "standard")
        self._lane_chip.setText(f"{lane.title()} · {verification}")
        self._lane_chip.setToolTip(
            f"fallback={bool(speed.get('fallback_active'))}\nlatency={speed.get('average_latency_bucket', 'unknown')}"
        )
        self._updated_chip.setText(f"Updated {time.strftime('%H:%M', time.localtime(snapshot.updated_at or time.time()))}")

        self._sync_metrics(snapshot.system_metrics + snapshot.ai_metrics)
        self._rebuild_activity(snapshot.activity)
        self._chart.set_series(snapshot.trend, snapshot.success_trend, snapshot.action_trend)
        self._sync_operator_cards(operator_summary)

    def _sync_metrics(self, metrics: list[MetricTile]) -> None:
        metrics = list(metrics[:4])
        while len(self._metric_cards) < len(metrics):
            metric = metrics[len(self._metric_cards)]
            widget = MetricCard(metric)
            self._metric_cards.append(widget)
            position = len(self._metric_cards) - 1
            row = position // 2
            col = position % 2
            self._insight_grid.addWidget(widget, row, col)
        for index, metric in enumerate(metrics):
            self._metric_cards[index].update_metric(metric)
            self._metric_cards[index].setVisible(True)
        for index in range(len(metrics), len(self._metric_cards)):
            self._metric_cards[index].setVisible(False)

    def _rebuild_activity(self, activity: list[ActivityEntry]) -> None:
        activity = self._filter_activity(activity)
        self._activity_list.clear()
        for entry in activity[:10]:
            item = QListWidgetItem()
            widget = ActivityRow(entry)
            item.setSizeHint(widget.sizeHint())
            self._activity_list.addItem(item)
            self._activity_list.setItemWidget(item, widget)

        if not activity:
            item = QListWidgetItem()
            widget = QLabel("No activity for this filter.")
            widget.setStyleSheet("color: #8B95A7; font-size: 11px; padding: 10px 6px; border: none;")
            item.setSizeHint(widget.sizeHint())
            self._activity_list.addItem(item)
            self._activity_list.setItemWidget(item, widget)

    def _add_activity(self, text: str, time_str: str) -> None:
        entry = ActivityEntry(text, text, time_str, status="info", source="system")
        item = QListWidgetItem()
        widget = ActivityRow(entry)
        item.setSizeHint(widget.sizeHint())
        self._activity_list.insertItem(0, item)
        self._activity_list.setItemWidget(item, widget)

    def _set_status_style(self, tone: str) -> None:
        styles = {
            "success": "QLabel { background: #EAF2FF; color: #4C82FF; border-radius: 14px; padding: 6px 12px; font-size: 12px; font-weight: 600; }",
            "neutral": "QLabel { background: #F7F8FA; color: #5D6675; border: 1px solid #E8ECF2; border-radius: 14px; padding: 6px 12px; font-size: 12px; font-weight: 600; }",
            "error": "QLabel { background: #FEE4E2; color: #EF4444; border-radius: 14px; padding: 6px 12px; font-size: 12px; font-weight: 600; }",
        }
        self._status_chip.setStyleSheet(styles.get(tone, styles["success"]))

    def _set_backend_style(self, tone: str) -> None:
        styles = {
            "success": "QLabel { background: #EEF7F1; color: #14803E; border: 1px solid #D8EFE0; border-radius: 14px; padding: 6px 12px; font-size: 12px; font-weight: 500; }",
            "warning": "QLabel { background: #FFF7E7; color: #B7791F; border: 1px solid #F5E4B8; border-radius: 14px; padding: 6px 12px; font-size: 12px; font-weight: 500; }",
            "error": "QLabel { background: #FEEDEC; color: #C94237; border: 1px solid #F4CFCB; border-radius: 14px; padding: 6px 12px; font-size: 12px; font-weight: 500; }",
            "neutral": "QLabel { background: #FFFFFF; color: #5D6675; border: 1px solid #E8ECF2; border-radius: 14px; padding: 6px 12px; font-size: 12px; font-weight: 500; }",
        }
        self._backend_chip.setStyleSheet(styles.get(tone, styles["neutral"]))

    def _set_activity_filter(self, value: str, label: str) -> None:
        self._activity_filter = value
        self._activity_filter_button.setText(f"{label} ▾")
        self._rebuild_activity(self._snapshot.activity)

    def _filter_activity(self, activity: list[ActivityEntry]) -> list[ActivityEntry]:
        if self._activity_filter == "all":
            return list(activity)
        source_map = {
            "run": {"run", "workflow", "agent"},
            "system": {"system"},
            "tool": {"tool"},
        }
        allowed = source_map.get(self._activity_filter, {self._activity_filter})
        return [entry for entry in activity if str(entry.source).lower() in allowed]

    def _sync_operator_cards(self, summary: dict[str, Any]) -> None:
        details = {
            "mobile_dispatch": lambda row: f"{int(row.get('count', 0) or 0)} sessions · approvals {int(row.get('pending_approvals', 0) or 0)}",
            "computer_use": lambda row: f"lane {row.get('current_lane', 'vision_lane')} · verify {row.get('verification_state', 'strong')} · fallback={bool(row.get('fallback_active'))}",
            "internet_reach": lambda row: f"lane {row.get('current_lane', 'verified_lane')} · {row.get('average_latency_bucket', 'steady')} · fallback={bool(row.get('fallback_active'))}",
            "document_ingest": lambda row: f"liteparse={bool(row.get('liteparse_enabled'))} · verify {row.get('verification_state', 'verified')} · ocr {row.get('vision_ocr_backend', 'auto')}",
            "speed_runtime": lambda row: f"lane {row.get('current_lane', 'unknown')} · verify {row.get('verification_state', 'standard')} · {row.get('average_latency_bucket', 'unknown')}",
        }
        for key, card in self._operator_cards.items():
            row = dict(summary.get(key) or {})
            status = str(row.get("status") or "unknown")
            detail = details.get(key, lambda value: "")(row)
            card.update_state(status, detail)

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        gradient = QLinearGradient(0, 0, self.width(), self.height())
        gradient.setColorAt(0.0, QColor(244, 247, 255))
        gradient.setColorAt(0.35, QColor(235, 244, 255))
        gradient.setColorAt(0.68, QColor(245, 251, 248))
        gradient.setColorAt(1.0, QColor(249, 244, 255))
        painter.fillRect(self.rect(), gradient)
        orb_specs = [
            (QColor(116, 171, 255, 54), QRectF(26, 18, 220, 220)),
            (QColor(123, 230, 202, 42), QRectF(self.width() - 240, 62, 180, 180)),
            (QColor(255, 203, 143, 38), QRectF(self.width() - 320, self.height() - 240, 260, 220)),
        ]
        painter.setPen(Qt.PenStyle.NoPen)
        for color, rect in orb_specs:
            painter.setBrush(color)
            painter.drawEllipse(rect)
        super().paintEvent(event)
