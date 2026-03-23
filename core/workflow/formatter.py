"""
Workflow Output Formatters — Text, JSON, Markdown.
"""

from __future__ import annotations

import json
from .engine import WorkflowResult


def format_text(result: WorkflowResult) -> str:
    """Format as plain text."""
    lines = []

    lines.append("⚙️  Workflow Execution")
    lines.append("-" * 60)
    lines.append(f"Workflow: {result.name}")
    lines.append(f"Status: {'✓ Başarı' if result.success else '✗ Başarısız'}")
    lines.append(f"Adımlar: {result.steps_done}/{result.steps_total}")
    if result.steps_failed:
        lines.append(f"Başarısız: {result.steps_failed}")
    lines.append(f"Süresi: {result.elapsed:.1f}s")
    lines.append("")

    if result.outputs:
        lines.append("Step Outputs:")
        for i, output in enumerate(result.outputs, 1):
            status = "✓" if output.get("success") else "✗"
            lines.append(f"[{i}] {status} {output.get('name', '?')}")
            if output.get("output"):
                lines.append(f"    Output: {output.get('output')[:100]}")

    return "\n".join(lines)


def format_json(result: WorkflowResult) -> str:
    """Format as JSON."""
    data = {
        "success": result.success,
        "workflow_id": result.workflow_id,
        "name": result.name,
        "steps_total": result.steps_total,
        "steps_done": result.steps_done,
        "steps_failed": result.steps_failed,
        "outputs": result.outputs,
        "elapsed": result.elapsed,
        "timestamp": result.timestamp,
    }
    return json.dumps(data, ensure_ascii=False, indent=2)


def format_md(result: WorkflowResult) -> str:
    """Format as Markdown (timeline view)."""
    lines = []

    lines.append("# ⚙️ Workflow Execution")
    lines.append("")
    lines.append(f"**Workflow**: {result.name}")
    lines.append(f"**Status**: {'✓ Başarı' if result.success else '✗ Başarısız'}")
    lines.append(f"**Duration**: {result.elapsed:.1f}s")
    lines.append(f"**Steps**: {result.steps_done}/{result.steps_total} completed")
    lines.append("")

    if result.outputs:
        lines.append("## Timeline")
        lines.append("")
        for i, output in enumerate(result.outputs, 1):
            status = "✓" if output.get("success") else "✗"
            duration = output.get("duration", 0)
            lines.append(f"### [{i}] {status} {output.get('name', '?')} ({duration:.2f}s)")
            if output.get("output"):
                lines.append(f"```")
                lines.append(output.get("output")[:200])
                lines.append(f"```")

    return "\n".join(lines)


__all__ = [
    "format_text",
    "format_json",
    "format_md",
]
