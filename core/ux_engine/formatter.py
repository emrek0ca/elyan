"""
Premium UX Output Formatters — Text, JSON, Markdown.
"""

from __future__ import annotations

import json
from .engine import UXResult


def format_text(result: UXResult) -> str:
    """Format as plain text with premium UX indicators."""
    lines = []

    lines.append("=" * 70)
    lines.append("✨ Premium UX Response")
    lines.append("=" * 70)
    lines.append("")

    # Main response
    lines.append(result.response)
    lines.append("")

    # Suggestions section
    if result.suggestions:
        lines.append("-" * 70)
        lines.append("💡 Öneriler:")
        for i, suggestion in enumerate(result.suggestions, 1):
            lines.append(f"  [{i}] {suggestion}")
        lines.append("")

    # Metadata
    lines.append("-" * 70)
    lines.append(f"⏱️  İşlem süresi: {result.elapsed:.2f}s")
    if result.streaming_enabled:
        lines.append("📡 Streaming aktif")
    if result.multimodal_inputs:
        lines.append(f"📎 Ek dosyalar: {len(result.multimodal_inputs)}")

    return "\n".join(lines)


def format_json(result: UXResult) -> str:
    """Format as JSON."""
    return result.to_json()


def format_md(result: UXResult) -> str:
    """Format as Markdown with rich formatting."""
    lines = []

    lines.append("# ✨ Premium UX Response")
    lines.append("")

    # Main response
    lines.append(result.response)
    lines.append("")

    # Suggestions
    if result.suggestions:
        lines.append("## 💡 Öneriler")
        lines.append("")
        for i, suggestion in enumerate(result.suggestions, 1):
            lines.append(f"**[{i}]** {suggestion}")
        lines.append("")

    # Context used
    if result.context_used:
        lines.append("## 📋 Context")
        lines.append("")
        for key, value in result.context_used.items():
            lines.append(f"- **{key}**: {str(value)[:50]}...")
        lines.append("")

    # Multi-modal summary
    if result.multimodal_inputs:
        lines.append("## 📎 Attachments")
        lines.append("")
        for inp in result.multimodal_inputs:
            lines.append(f"- `{inp}`")
        lines.append("")

    # Metadata
    lines.append("---")
    lines.append("")
    lines.append(f"**Duration**: {result.elapsed:.2f}s  ")
    if result.streaming_enabled:
        lines.append("**Streaming**: Enabled  ")

    return "\n".join(lines)


__all__ = ["format_text", "format_json", "format_md"]
