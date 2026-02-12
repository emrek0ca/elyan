"""Shared branding helpers for Wiqo image assets."""

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon, QPixmap


def get_brand_image_path() -> Path:
    """Return the best available brand image path."""
    root = Path(__file__).resolve().parent.parent
    candidates = [
        root / "assets" / "image.png",
        root / "resources" / "images" / "bot_avatar_3d.png",
        root / "resources" / "images" / "future_bg.png",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def load_brand_pixmap(size: int = 0) -> QPixmap:
    """Load brand pixmap with optional square scaling."""
    pixmap = QPixmap(str(get_brand_image_path()))
    if pixmap.isNull():
        return QPixmap()
    if size > 0:
        return pixmap.scaled(
            size,
            size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    return pixmap


def load_brand_icon(size: int = 64) -> QIcon:
    """Load brand icon from the brand image."""
    pixmap = load_brand_pixmap(size=size)
    if pixmap.isNull():
        return QIcon()
    return QIcon(pixmap)

