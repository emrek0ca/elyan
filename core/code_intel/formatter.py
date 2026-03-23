"""
Code Output Formatters — Text, JSON, Markdown.
"""

from __future__ import annotations

import json
from .engine import CodeAnalysisResult


def format_text(result: CodeAnalysisResult) -> str:
    """Format as plain text."""
    lines = []

    if not result.success:
        return f"❌ Hata: {result.text}"

    lines.append("✓ Kod Analizi")
    lines.append("-" * 60)
    lines.append(result.text)

    if result.functions:
        lines.append("")
        lines.append("Fonksiyonlar:")
        for func in result.functions:
            lines.append(f"  - {func}")

    if result.classes:
        lines.append("")
        lines.append("Sınıflar:")
        for cls in result.classes:
            lines.append(f"  - {cls}")

    if result.complexity:
        lines.append("")
        lines.append(f"Karmaşıklık: {result.complexity}")

    if result.issues:
        lines.append("")
        lines.append("Güvenlik Sorunları:")
        for issue in result.issues:
            sev = issue.get("severity", "unknown")
            msg = issue.get("message", "")
            line = issue.get("line", "?")
            lines.append(f"  [{sev}] Satır {line}: {msg}")

    if result.output:
        lines.append("")
        lines.append("Çıktı:")
        lines.append(result.output[:300])

    return "\n".join(lines)


def format_json(result: CodeAnalysisResult) -> str:
    """Format as JSON."""
    data = {
        "success": result.success,
        "text": result.text,
        "language": result.language,
        "functions": result.functions,
        "classes": result.classes,
        "imports": result.imports,
        "complexity": result.complexity,
        "issue_count": len(result.issues),
        "issues": result.issues,
        "timestamp": result.timestamp,
    }
    return json.dumps(data, ensure_ascii=False, indent=2)


def format_md(result: CodeAnalysisResult) -> str:
    """Format as Markdown."""
    lines = []

    if not result.success:
        lines.append("# ❌ Analiz Başarısız")
        lines.append("")
        lines.append(result.text)
        return "\n".join(lines)

    lines.append("# 🔍 Kod Analizi")
    lines.append("")
    lines.append(result.text)

    if result.functions:
        lines.append("")
        lines.append("## Fonksiyonlar")
        for func in result.functions:
            lines.append(f"- `{func}()`")

    if result.classes:
        lines.append("")
        lines.append("## Sınıflar")
        for cls in result.classes:
            lines.append(f"- `class {cls}`")

    if result.complexity:
        lines.append("")
        lines.append("## Karmaşıklık")
        lines.append(f"- **Siklomatik Karmaşıklık**: {result.complexity}")

    if result.issues:
        lines.append("")
        lines.append("## 🔒 Güvenlik Sorunları")
        for issue in result.issues:
            sev = issue.get("severity", "unknown")
            msg = issue.get("message", "")
            line = issue.get("line", "?")
            emoji = "🔴" if sev == "critical" else "🟠" if sev == "high" else "🟡"
            lines.append(f"{emoji} **{sev.upper()}** (Satır {line}): {msg}")

    if result.output:
        lines.append("")
        lines.append("## Çıktı")
        lines.append("```")
        lines.append(result.output[:300])
        lines.append("```")

    return "\n".join(lines)


__all__ = [
    "format_text",
    "format_json",
    "format_md",
]
