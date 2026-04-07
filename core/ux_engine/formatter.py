"""
Premium UX Output Formatters — Text, JSON, Markdown.
"""

from __future__ import annotations

import json
from .engine import UXResult


def format_text(result: UXResult) -> str:
    """Format as plain, message-native text."""
    lines = [str(result.response or result.text or "").strip()]
    if result.suggestions:
        lines.append("")
        lines.extend(f"- {suggestion}" for suggestion in result.suggestions[:2])
    lines.append("")
    lines.append(f"{result.elapsed:.2f}s")
    return "\n".join(line for line in lines if line is not None).strip()


def format_json(result: UXResult) -> str:
    """Format as JSON."""
    return result.to_json()


def format_md(result: UXResult) -> str:
    """Format as minimal markdown."""
    body = str(result.response or result.text or "").strip()
    lines = ["# ✨ Response", "", body]
    if result.suggestions:
        lines.extend(["", *[f"- {item}" for item in result.suggestions[:2]]])
    return "\n".join(lines).strip()


__all__ = ["format_text", "format_json", "format_md"]
