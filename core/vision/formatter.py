"""
Vision Output Formatters — Markdown, JSON, CLI summary.
"""

from __future__ import annotations

import json
from .engine import VisionResult


def format_text(result: VisionResult) -> str:
    """
    Format as plain text summary.
    """
    lines = []

    if not result.success:
        return f"❌ Hata: {result.text}"

    lines.append("✓ Gorsel Analizi")
    lines.append("-" * 50)
    lines.append(result.text)

    if result.image_path:
        lines.append("")
        lines.append(f"Dosya: {result.image_path}")

    if result.source:
        lines.append(f"Kaynak: {result.source}")

    return "\n".join(lines)


def format_json(result: VisionResult) -> str:
    """Format as JSON."""
    data = {
        "success": result.success,
        "text": result.text,
        "image_path": result.image_path,
        "source": result.source,
        "timestamp": result.timestamp,
        "raw": result.raw,
    }
    return json.dumps(data, ensure_ascii=False, indent=2)


def format_md(result: VisionResult) -> str:
    """Format as Markdown."""
    lines = []

    if not result.success:
        lines.append("# ❌ Analiz Basarısız")
        lines.append("")
        lines.append(result.text)
        return "\n".join(lines)

    lines.append("# 👁️ Gorsel Analizi")
    lines.append("")
    lines.append(result.text)
    lines.append("")

    if result.image_path:
        lines.append("## Dosya")
        lines.append(f"- Yol: `{result.image_path}`")

    if result.source:
        lines.append("")
        lines.append("## Kaynak")
        lines.append(f"- Provider: {result.source}")

    lines.append("")
    lines.append(f"*Zaman: {result.timestamp}*")

    return "\n".join(lines)


__all__ = [
    "format_text",
    "format_json",
    "format_md",
]
