"""Themes Module - Modern theme system with customization support"""

from dataclasses import dataclass
from typing import Dict, Any
import json
from pathlib import Path


@dataclass
class ThemeColors:
    """Theme color palette"""
    # Primary colors
    primary: str = "#6366f1"
    primary_hover: str = "#4f46e5"
    primary_light: str = "#818cf8"

    # Background colors
    bg_primary: str = "#0f0f0f"
    bg_secondary: str = "#1a1a1a"
    bg_tertiary: str = "#252525"
    bg_card: str = "#1e1e1e"
    bg_hover: str = "#2a2a2a"

    # Text colors
    text_primary: str = "#ffffff"
    text_secondary: str = "#a1a1aa"
    text_muted: str = "#71717a"
    text_accent: str = "#6366f1"

    # Border colors
    border: str = "#27272a"
    border_light: str = "#3f3f46"
    border_focus: str = "#6366f1"

    # Status colors
    success: str = "#22c55e"
    success_bg: str = "#052e16"
    warning: str = "#f59e0b"
    warning_bg: str = "#422006"
    error: str = "#ef4444"
    error_bg: str = "#450a0a"
    info: str = "#3b82f6"
    info_bg: str = "#172554"

    # Accent colors
    accent_purple: str = "#a855f7"
    accent_pink: str = "#ec4899"
    accent_cyan: str = "#06b6d4"
    accent_green: str = "#10b981"
    accent_orange: str = "#f97316"

    # Shadows
    shadow_sm: str = "0 1px 2px rgba(0,0,0,0.3)"
    shadow_md: str = "0 4px 6px rgba(0,0,0,0.4)"
    shadow_lg: str = "0 10px 15px rgba(0,0,0,0.5)"


# Elyan Professional Palette (Apple-Style)
elyan_TURQUOISE = "#ADDBE3"
elyan_STEEL = "#7196A2"
elyan_SLATE = "#517079"
elyan_CHARCOAL = "#252F33"
elyan_BLACK = "#090E0F"
elyan_PURE_WHITE = "#FFFFFF"
elyan_OFF_WHITE = "#F5F5F7" # Apple style off-white


# Predefined themes
DARK_THEME = ThemeColors()

LIGHT_THEME = ThemeColors(
    primary="#4f46e5",
    primary_hover="#4338ca",
    primary_light="#6366f1",
    bg_primary="#ffffff",
    bg_secondary="#f4f4f5",
    bg_tertiary="#e4e4e7",
    bg_card="#ffffff",
    bg_hover="#f4f4f5",
    text_primary="#18181b",
    text_secondary="#52525b",
    text_muted="#a1a1aa",
    text_accent="#4f46e5",
    border="#e4e4e7",
    border_light="#d4d4d8",
    border_focus="#4f46e5",
    success="#16a34a",
    success_bg="#dcfce7",
    warning="#d97706",
    warning_bg="#fef3c7",
    error="#dc2626",
    error_bg="#fee2e2",
    info="#2563eb",
    info_bg="#dbeafe",
    shadow_sm="0 1px 2px rgba(0,0,0,0.05)",
    shadow_md="0 4px 6px rgba(0,0,0,0.1)",
    shadow_lg="0 10px 15px rgba(0,0,0,0.1)"
)

MIDNIGHT_THEME = ThemeColors(
    primary="#8b5cf6",
    primary_hover="#7c3aed",
    primary_light="#a78bfa",
    bg_primary="#020617",
    bg_secondary="#0f172a",
    bg_tertiary="#1e293b",
    bg_card="#0f172a",
    bg_hover="#1e293b",
    text_primary="#f8fafc",
    text_secondary="#94a3b8",
    text_muted="#64748b",
    text_accent="#8b5cf6",
    border="#1e293b",
    border_light="#334155",
    border_focus="#8b5cf6"
)

OCEAN_THEME = ThemeColors(
    primary="#0ea5e9",
    primary_hover="#0284c7",
    primary_light="#38bdf8",
    bg_primary="#0c1929",
    bg_secondary="#0f2744",
    bg_tertiary="#163c5e",
    bg_card="#0f2744",
    bg_hover="#163c5e",
    text_primary="#f0f9ff",
    text_secondary="#7dd3fc",
    text_muted="#38bdf8",
    text_accent="#0ea5e9",
    border="#1e3a5f",
    border_light="#2d5a87",
    border_focus="#0ea5e9"
)

FOREST_THEME = ThemeColors(
    primary="#10b981",
    primary_hover="#059669",
    primary_light="#34d399",
    bg_primary="#0a1612",
    bg_secondary="#0f2318",
    bg_tertiary="#15372a",
    bg_card="#0f2318",
    bg_hover="#15372a",
    text_primary="#ecfdf5",
    text_secondary="#6ee7b7",
    text_muted="#34d399",
    text_accent="#10b981",
    border="#1a3d2e",
    border_light="#2a5a46",
    border_focus="#10b981"
)

ROSE_THEME = ThemeColors(
    primary="#f43f5e",
    primary_hover="#e11d48",
    primary_light="#fb7185",
    bg_primary="#1a0a0e",
    bg_secondary="#2d1219",
    bg_tertiary="#4c1d25",
    bg_card="#2d1219",
    bg_hover="#4c1d25",
    text_primary="#fff1f2",
    text_secondary="#fda4af",
    text_muted="#fb7185",
    text_accent="#f43f5e",
    border="#4c1d25",
    border_light="#6b2532",
    border_focus="#f43f5e"
)

elyan_WHITE = ThemeColors(
    primary=elyan_STEEL,
    primary_hover=elyan_SLATE,
    primary_light=elyan_TURQUOISE,
    bg_primary=elyan_PURE_WHITE,
    bg_secondary=elyan_OFF_WHITE,
    bg_tertiary="#E5E5EA",
    bg_card=elyan_PURE_WHITE,
    bg_hover=elyan_OFF_WHITE,
    text_primary=elyan_BLACK,
    text_secondary=elyan_CHARCOAL,
    text_muted="#8E8E93",
    text_accent=elyan_STEEL,
    border="#D1D1D6",
    border_light="#E5E5EA",
    border_focus=elyan_TURQUOISE,
    success="#34C759", # Apple Green
    success_bg="#EBF9EE",
    warning="#FF9500", # Apple Orange
    warning_bg="#FFF4E5",
    error="#FF3B30", # Apple Red
    error_bg="#FFEBEA",
    info="#007AFF", # Apple Blue
    info_bg="#E5F1FF",
    shadow_sm="0 2px 8px rgba(0,0,0,0.04)",
    shadow_md="0 4px 16px rgba(0,0,0,0.08)",
    shadow_lg="0 8px 32px rgba(0,0,0,0.12)"
)

FUTURE_LIGHT = ThemeColors(
    primary="#0ea5e9",
    primary_hover="#0284c7",
    primary_light="#38bdf8",
    bg_primary="rgba(255, 255, 255, 0.7)",
    bg_secondary="rgba(240, 249, 255, 0.4)",
    bg_tertiary="rgba(224, 242, 254, 0.5)",
    bg_card="rgba(255, 255, 255, 0.8)",
    bg_hover="rgba(224, 242, 254, 0.8)",
    text_primary="#0f172a",
    text_secondary="#475569",
    text_muted="#94a3b8",
    text_accent="#0ea5e9",
    border="rgba(226, 232, 240, 0.5)",
    border_light="rgba(203, 213, 225, 0.5)",
    border_focus="#0ea5e9",
    shadow_sm="0 4px 6px rgba(0,0,0,0.02)",
    shadow_md="0 10px 15px rgba(0,0,0,0.04)",
    shadow_lg="0 20px 25px rgba(0,0,0,0.06)"
)


THEMES: Dict[str, ThemeColors] = {
    "elyan": elyan_WHITE,
    "dark": DARK_THEME,
    "light": LIGHT_THEME,
    "midnight": MIDNIGHT_THEME,
    "ocean": OCEAN_THEME,
    "forest": FOREST_THEME,
    "rose": ROSE_THEME,
    "future": FUTURE_LIGHT
}

THEME_NAMES = {
    "elyan": "Elyan Beyaz (Professional)",
    "dark": "Koyu (Dark)",
    "light": "Açık (Light)",
    "midnight": "Gece Yarısı (Midnight)",
    "ocean": "Okyanus (Ocean)",
    "forest": "Orman (Forest)",
    "rose": "Gül (Rose)",
    "future": "Gelecek (Future Mode)"
}


def get_theme(name: str) -> ThemeColors:
    """Get theme by name"""
    return THEMES.get(name, DARK_THEME)


def generate_stylesheet(theme: ThemeColors, font_size: int = 13, font_family: str = "SF Pro Display") -> str:
    """Generate complete PyQt6 stylesheet from theme"""
    return f'''
/* ============================================
   CDACS BOT - MODERN UI STYLESHEET
   Theme-aware, fully customizable
   ============================================ */

/* Global Styles */
* {{
    font-family: "{font_family}", "Segoe UI", "Helvetica Neue", sans-serif;
    font-size: {font_size}px;
}}

QMainWindow {{
    background-color: {theme.bg_primary};
}}

QWidget {{
    background-color: transparent;
    color: {theme.text_primary};
}}

/* Scroll Areas */
QScrollArea {{
    border: none;
    background-color: transparent;
}}

QScrollBar:vertical {{
    background-color: {theme.bg_secondary};
    width: 10px;
    border-radius: 5px;
    margin: 2px;
}}

QScrollBar::handle:vertical {{
    background-color: {theme.border_light};
    border-radius: 4px;
    min-height: 30px;
}}

QScrollBar::handle:vertical:hover {{
    background-color: {theme.primary};
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}

QScrollBar:horizontal {{
    background-color: {theme.bg_secondary};
    height: 10px;
    border-radius: 5px;
    margin: 2px;
}}

QScrollBar::handle:horizontal {{
    background-color: {theme.border_light};
    border-radius: 4px;
    min-width: 30px;
}}

QScrollBar::handle:horizontal:hover {{
    background-color: {theme.primary};
}}

/* Labels */
QLabel {{
    color: {theme.text_primary};
    background: transparent;
}}

QLabel[class="title"] {{
    font-size: {font_size + 8}px;
    font-weight: bold;
    color: {theme.text_primary};
}}

QLabel[class="subtitle"] {{
    font-size: {font_size + 2}px;
    color: {theme.text_secondary};
}}

QLabel[class="muted"] {{
    color: {theme.text_muted};
    font-size: {font_size - 1}px;
}}

/* Buttons */
QPushButton {{
    background-color: {theme.primary};
    color: white;
    border: none;
    border-radius: 8px;
    padding: 10px 20px;
    font-weight: 500;
    min-height: 36px;
}}

QPushButton:hover {{
    background-color: {theme.primary_hover};
}}

QPushButton:pressed {{
    background-color: {theme.primary_light};
}}

QPushButton:disabled {{
    background-color: {theme.border};
    color: {theme.text_muted};
}}

QPushButton[class="secondary"] {{
    background-color: {theme.bg_tertiary};
    color: {theme.text_primary};
    border: 1px solid {theme.border};
}}

QPushButton[class="secondary"]:hover {{
    background-color: {theme.bg_hover};
    border-color: {theme.border_light};
}}

QPushButton[class="ghost"] {{
    background-color: transparent;
    color: {theme.text_secondary};
    border: none;
}}

QPushButton[class="ghost"]:hover {{
    background-color: {theme.bg_hover};
    color: {theme.text_primary};
}}

QPushButton[class="danger"] {{
    background-color: {theme.error};
}}

QPushButton[class="danger"]:hover {{
    background-color: #dc2626;
}}

QPushButton[class="success"] {{
    background-color: {theme.success};
}}

QPushButton[class="success"]:hover {{
    background-color: #16a34a;
}}

QPushButton[class="icon"] {{
    background-color: transparent;
    border-radius: 6px;
    padding: 8px;
    min-height: 32px;
    min-width: 32px;
}}

QPushButton[class="icon"]:hover {{
    background-color: {theme.bg_hover};
}}

/* Input Fields */
QLineEdit {{
    background-color: {theme.bg_secondary};
    border: 1px solid {theme.border};
    border-radius: 8px;
    padding: 10px 14px;
    color: {theme.text_primary};
    selection-background-color: {theme.primary};
}}

QLineEdit:focus {{
    border-color: {theme.border_focus};
    background-color: {theme.bg_tertiary};
}}

QLineEdit:disabled {{
    background-color: {theme.bg_primary};
    color: {theme.text_muted};
}}

QLineEdit::placeholder {{
    color: {theme.text_muted};
}}

/* Text Areas */
QTextEdit, QPlainTextEdit {{
    background-color: {theme.bg_secondary};
    border: 1px solid {theme.border};
    border-radius: 8px;
    padding: 12px;
    color: {theme.text_primary};
    selection-background-color: {theme.primary};
}}

QTextEdit:focus, QPlainTextEdit:focus {{
    border-color: {theme.border_focus};
}}

/* Combo Boxes */
QComboBox {{
    background-color: {theme.bg_secondary};
    border: 1px solid {theme.border};
    border-radius: 8px;
    padding: 10px 14px;
    color: {theme.text_primary};
    min-height: 36px;
}}

QComboBox:hover {{
    border-color: {theme.border_light};
}}

QComboBox:focus {{
    border-color: {theme.border_focus};
}}

QComboBox::drop-down {{
    border: none;
    padding-right: 10px;
}}

QComboBox::down-arrow {{
    image: none;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 6px solid {theme.text_secondary};
    margin-right: 10px;
}}

QComboBox QAbstractItemView {{
    background-color: {theme.bg_card};
    border: 1px solid {theme.border};
    border-radius: 8px;
    padding: 4px;
    selection-background-color: {theme.primary};
}}

/* Spin Boxes */
QSpinBox, QDoubleSpinBox {{
    background-color: {theme.bg_secondary};
    border: 1px solid {theme.border};
    border-radius: 8px;
    padding: 10px 14px;
    color: {theme.text_primary};
    min-height: 36px;
}}

QSpinBox:focus, QDoubleSpinBox:focus {{
    border-color: {theme.border_focus};
}}

QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    background-color: {theme.bg_tertiary};
    border: none;
    border-radius: 4px;
    width: 20px;
    margin: 2px;
}}

QSpinBox::up-button:hover, QSpinBox::down-button:hover,
QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {{
    background-color: {theme.bg_hover};
}}

/* Check Boxes */
QCheckBox {{
    spacing: 10px;
    color: {theme.text_primary};
}}

QCheckBox::indicator {{
    width: 20px;
    height: 20px;
    border-radius: 4px;
    border: 2px solid {theme.border};
    background-color: {theme.bg_secondary};
}}

QCheckBox::indicator:hover {{
    border-color: {theme.border_light};
}}

QCheckBox::indicator:checked {{
    background-color: {theme.primary};
    border-color: {theme.primary};
}}

QCheckBox::indicator:checked:hover {{
    background-color: {theme.primary_hover};
    border-color: {theme.primary_hover};
}}

/* Radio Buttons */
QRadioButton {{
    spacing: 10px;
    color: {theme.text_primary};
}}

QRadioButton::indicator {{
    width: 20px;
    height: 20px;
    border-radius: 10px;
    border: 2px solid {theme.border};
    background-color: {theme.bg_secondary};
}}

QRadioButton::indicator:checked {{
    background-color: {theme.primary};
    border-color: {theme.primary};
}}

/* Sliders */
QSlider::groove:horizontal {{
    background-color: {theme.bg_tertiary};
    height: 6px;
    border-radius: 3px;
}}

QSlider::handle:horizontal {{
    background-color: {theme.primary};
    width: 18px;
    height: 18px;
    margin: -6px 0;
    border-radius: 9px;
}}

QSlider::handle:horizontal:hover {{
    background-color: {theme.primary_hover};
}}

QSlider::sub-page:horizontal {{
    background-color: {theme.primary};
    border-radius: 3px;
}}

/* Progress Bars */
QProgressBar {{
    background-color: {theme.bg_tertiary};
    border: none;
    border-radius: 4px;
    height: 8px;
    text-align: center;
}}

QProgressBar::chunk {{
    background-color: {theme.primary};
    border-radius: 4px;
}}

/* Tab Widget */
QTabWidget::pane {{
    border: none;
    background-color: {theme.bg_primary};
}}

QTabBar::tab {{
    background-color: transparent;
    color: {theme.text_secondary};
    padding: 12px 20px;
    margin-right: 4px;
    border-bottom: 2px solid transparent;
}}

QTabBar::tab:hover {{
    color: {theme.text_primary};
    background-color: {theme.bg_hover};
}}

QTabBar::tab:selected {{
    color: {theme.primary};
    border-bottom-color: {theme.primary};
}}

/* Group Boxes */
QGroupBox {{
    background-color: {theme.bg_card};
    border: 1px solid {theme.border};
    border-radius: 12px;
    margin-top: 16px;
    padding: 20px;
    padding-top: 35px;
    font-weight: 500;
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 16px;
    top: 8px;
    color: {theme.text_primary};
    font-weight: 600;
}}

/* List Views */
QListWidget {{
    background-color: {theme.bg_secondary};
    border: 1px solid {theme.border};
    border-radius: 8px;
    padding: 4px;
    outline: none;
}}

QListWidget::item {{
    padding: 10px 14px;
    border-radius: 6px;
    margin: 2px;
}}

QListWidget::item:hover {{
    background-color: {theme.bg_hover};
}}

QListWidget::item:selected {{
    background-color: {theme.primary};
    color: white;
}}

/* Tree Views */
QTreeView {{
    background-color: {theme.bg_secondary};
    border: 1px solid {theme.border};
    border-radius: 8px;
    padding: 4px;
    outline: none;
}}

QTreeView::item {{
    padding: 8px;
    border-radius: 4px;
}}

QTreeView::item:hover {{
    background-color: {theme.bg_hover};
}}

QTreeView::item:selected {{
    background-color: {theme.primary};
}}

QTreeView::branch {{
    background-color: transparent;
}}

/* Table Views */
QTableWidget, QTableView {{
    background-color: {theme.bg_secondary};
    border: 1px solid {theme.border};
    border-radius: 8px;
    gridline-color: {theme.border};
}}

QTableWidget::item, QTableView::item {{
    padding: 10px;
}}

QTableWidget::item:selected, QTableView::item:selected {{
    background-color: {theme.primary};
}}

QHeaderView::section {{
    background-color: {theme.bg_tertiary};
    color: {theme.text_secondary};
    padding: 12px;
    border: none;
    font-weight: 600;
}}

/* Splitters */
QSplitter::handle {{
    background-color: {theme.border};
}}

QSplitter::handle:horizontal {{
    width: 1px;
}}

QSplitter::handle:vertical {{
    height: 1px;
}}

/* Menu */
QMenu {{
    background-color: {theme.bg_card};
    border: 1px solid {theme.border};
    border-radius: 8px;
    padding: 8px;
}}

QMenu::item {{
    padding: 10px 20px;
    border-radius: 4px;
}}

QMenu::item:selected {{
    background-color: {theme.bg_hover};
}}

QMenu::separator {{
    height: 1px;
    background-color: {theme.border};
    margin: 6px 10px;
}}

/* Tooltips */
QToolTip {{
    background-color: {theme.bg_card};
    color: {theme.text_primary};
    border: 1px solid {theme.border};
    border-radius: 6px;
    padding: 8px 12px;
}}

/* Status Bar */
QStatusBar {{
    background-color: {theme.bg_secondary};
    border-top: 1px solid {theme.border};
    color: {theme.text_secondary};
}}

/* Frame */
QFrame[class="card"] {{
    background-color: {theme.bg_card};
    border: 1px solid {theme.border};
    border-radius: 12px;
}}

QFrame[class="separator"] {{
    background-color: {theme.border};
}}

/* Dialog */
QDialog {{
    background-color: {theme.bg_primary};
}}

QDialogButtonBox QPushButton {{
    min-width: 80px;
}}

/* Message Box */
QMessageBox {{
    background-color: {theme.bg_primary};
}}

/* Calendar Widget */
QCalendarWidget {{
    background-color: {theme.bg_card};
}}

QCalendarWidget QWidget {{
    alternate-background-color: {theme.bg_secondary};
}}

QCalendarWidget QAbstractItemView:enabled {{
    background-color: {theme.bg_secondary};
    color: {theme.text_primary};
    selection-background-color: {theme.primary};
}}

/* Custom Classes */
.sidebar {{
    background-color: {theme.bg_secondary};
    border-right: 1px solid {theme.border};
}}

.sidebar-item {{
    padding: 12px 16px;
    border-radius: 8px;
    margin: 2px 8px;
}}

.sidebar-item:hover {{
    background-color: {theme.bg_hover};
}}

.sidebar-item.active {{
    background-color: {theme.primary};
    color: white;
}}

.chat-bubble-user {{
    background-color: {theme.primary};
    color: white;
    border-radius: 16px 16px 4px 16px;
    padding: 12px 16px;
    max-width: 70%;
}}

.chat-bubble-bot {{
    background-color: {theme.bg_tertiary};
    color: {theme.text_primary};
    border-radius: 16px 16px 16px 4px;
    padding: 12px 16px;
    max-width: 70%;
}}

.stat-card {{
    background-color: {theme.bg_card};
    border: 1px solid {theme.border};
    border-radius: 12px;
    padding: 20px;
}}

.file-item {{
    background-color: {theme.bg_secondary};
    border: 1px solid {theme.border};
    border-radius: 8px;
    padding: 12px;
    margin: 4px 0;
}}

.file-item:hover {{
    background-color: {theme.bg_hover};
    border-color: {theme.border_light};
}}

.badge {{
    background-color: {theme.primary};
    color: white;
    padding: 4px 10px;
    border-radius: 12px;
    font-size: {font_size - 2}px;
    font-weight: 600;
}}

.badge-success {{
    background-color: {theme.success};
}}

.badge-warning {{
    background-color: {theme.warning};
}}

.badge-error {{
    background-color: {theme.error};
}}
'''


class ThemeManager:
    """Manages theme loading, saving, and customization"""

    def __init__(self, config_dir: Path = None):
        self.config_dir = config_dir or Path.home() / ".config" / "cdacs-bot"
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.custom_themes_file = self.config_dir / "custom_themes.json"
        self._custom_themes: Dict[str, Dict] = {}
        self._load_custom_themes()

    def _load_custom_themes(self):
        """Load custom themes from file"""
        if self.custom_themes_file.exists():
            try:
                with open(self.custom_themes_file, 'r') as f:
                    self._custom_themes = json.load(f)
            except:
                self._custom_themes = {}

    def _save_custom_themes(self):
        """Save custom themes to file"""
        with open(self.custom_themes_file, 'w') as f:
            json.dump(self._custom_themes, f, indent=2)

    def get_all_themes(self) -> Dict[str, str]:
        """Get all available themes (built-in + custom)"""
        themes = THEME_NAMES.copy()
        for name in self._custom_themes:
            themes[name] = f"✨ {name}"
        return themes

    def get_theme(self, name: str) -> ThemeColors:
        """Get a theme by name"""
        if name in THEMES:
            return THEMES[name]
        elif name in self._custom_themes:
            return ThemeColors(**self._custom_themes[name])
        return DARK_THEME

    def create_custom_theme(self, name: str, colors: Dict[str, str]) -> bool:
        """Create a new custom theme"""
        self._custom_themes[name] = colors
        self._save_custom_themes()
        return True

    def delete_custom_theme(self, name: str) -> bool:
        """Delete a custom theme"""
        if name in self._custom_themes:
            del self._custom_themes[name]
            self._save_custom_themes()
            return True
        return False

    def export_theme(self, name: str, filepath: str) -> bool:
        """Export a theme to file"""
        theme = self.get_theme(name)
        data = {
            "name": name,
            "colors": {
                k: v for k, v in theme.__dict__.items()
                if not k.startswith('_')
            }
        }
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)
        return True

    def import_theme(self, filepath: str) -> str:
        """Import a theme from file, returns theme name"""
        with open(filepath, 'r') as f:
            data = json.load(f)
        name = data.get("name", "imported_theme")
        colors = data.get("colors", {})
        self.create_custom_theme(name, colors)
        return name
