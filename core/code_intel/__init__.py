"""
core/code_intel — Code Intelligence Module
Static analysis, security scanning, test generation, execution.
"""

from __future__ import annotations

from .engine import CodeEngine, CodeAnalysisResult
from .formatter import format_text, format_json, format_md

_code_engine: CodeEngine | None = None


def get_code_engine() -> CodeEngine:
    """Singleton: get or create CodeEngine."""
    global _code_engine
    if _code_engine is None:
        _code_engine = CodeEngine()
    return _code_engine


__all__ = [
    "CodeEngine",
    "CodeAnalysisResult",
    "get_code_engine",
    "format_text",
    "format_json",
    "format_md",
]
