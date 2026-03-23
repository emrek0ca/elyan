"""
core/vision — Visual Intelligence Module
Screen understanding, OCR, UI element detection, accessibility analysis.
"""

from __future__ import annotations

from .engine import VisionEngine, VisionResult
from .session import get_vision_session, list_vision_sessions, save_vision_session
from .formatter import format_text, format_json, format_md

_vision_engine: VisionEngine | None = None


def get_vision_engine() -> VisionEngine:
    """Singleton: get or create VisionEngine."""
    global _vision_engine
    if _vision_engine is None:
        _vision_engine = VisionEngine()
    return _vision_engine


__all__ = [
    "VisionEngine",
    "VisionResult",
    "get_vision_engine",
    "get_vision_session",
    "list_vision_sessions",
    "save_vision_session",
    "format_text",
    "format_json",
    "format_md",
]
