"""
Output Formatters for research results.
- Markdown with footnotes
- JSON for API
- CLI summary with colors
"""

from __future__ import annotations

import json
from typing import Optional
from .engine import ResearchResult


def format_cited_answer(result: ResearchResult) -> str:
    """
    Format as Markdown with footnotes [1][2][3].
    Example:
        According to research[1], X is Y[2]. Recent studies[3] show...
        [1] Source title - https://...
        [2] Source title - https://...
    """
    lines = []

    # Main answer
    lines.append(result.answer)
    lines.append("")

    # Bibliography/footnotes
    if result.citations:
        lines.append("## Kaynaklar")
        for i, source in enumerate(result.citations, 1):
            lines.append(
                f"[{i}] {source.title} — {source.url} "
                f"(güvenilirlik: {source.reliability:.0%})"
            )

        # Confidence footer
        lines.append("")
        lines.append(f"**Genel Güvenirlik**: {result.confidence:.0%}")

    return "\n".join(lines)


def format_json_result(result: ResearchResult) -> str:
    """Format as JSON (for API integration)."""
    return json.dumps(result.to_dict(), ensure_ascii=False, indent=2)


def format_cli_summary(result: ResearchResult) -> str:
    """
    Format for terminal with colors and compact layout.
    Example:
        🔬 Research Summary
        Query: X is Y?
        Confidence: 85%
        Sources: 12

        Answer:
        Lorem ipsum...

        Top Sources:
        [1] Title — domain (reliability: 85%)
        [2] Title — domain (reliability: 72%)
    """
    lines = []

    # Header
    lines.append("🔬 Research Summary")
    lines.append("-" * 50)

    # Meta
    lines.append(f"Query: {result.query}")
    lines.append(f"Confidence: {result.confidence:.0%}")
    lines.append(f"Sources: {len(result.citations)}")
    lines.append(f"ID: {result.research_id}")
    lines.append("")

    # Answer section
    lines.append("📝 Answer:")
    lines.append("-" * 50)
    # Truncate if too long
    answer = result.answer
    if len(answer) > 500:
        answer = answer[:500] + "..."
    lines.append(answer)
    lines.append("")

    # Top sources
    if result.citations:
        lines.append("📚 Top Sources:")
        lines.append("-" * 50)
        for i, source in enumerate(result.citations[:5], 1):
            # Extract domain from URL
            domain = source.url.split("/")[2] if "/" in source.url else source.url
            lines.append(
                f"[{i}] {source.title[:50]:<50} ({source.reliability:.0%})"
            )
            lines.append(f"    {source.url}")

    return "\n".join(lines)


__all__ = [
    "format_cited_answer",
    "format_json_result",
    "format_cli_summary",
]
