"""
Elyan Report Engine — PDF, HTML, Markdown report generation

Template-based report creation with chart, table, and text support.
"""

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from core.storage_paths import resolve_elyan_data_dir
from utils.logger import get_logger

logger = get_logger("report_engine")

def _default_report_dir() -> Path:
    return resolve_elyan_data_dir() / "reports"


REPORT_DIR = _default_report_dir()
REPORT_DIR.mkdir(parents=True, exist_ok=True)


class ReportEngine:
    """Generate structured reports in multiple formats."""

    async def generate(
        self,
        title: str,
        sections: List[Dict[str, Any]],
        format: str = "markdown",
        output_dir: str = None,
    ) -> Dict[str, Any]:
        """Generate a report.
        
        sections: List of {"heading": str, "content": str, "type": "text|table|chart"}
        """
        out_dir = Path(output_dir or str(REPORT_DIR))
        out_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        safe_title = title.lower().replace(" ", "_")[:30]

        if format == "markdown":
            return await self._generate_markdown(title, sections, out_dir, f"{safe_title}_{timestamp}")
        elif format == "html":
            return await self._generate_html(title, sections, out_dir, f"{safe_title}_{timestamp}")
        else:
            return {"success": False, "error": f"Unsupported format: {format}"}

    async def _generate_markdown(self, title, sections, out_dir, filename) -> Dict[str, Any]:
        lines = [f"# {title}\n", f"*Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}*\n\n---\n"]
        
        for section in sections:
            heading = section.get("heading", "")
            content = section.get("content", "")
            stype = section.get("type", "text")

            if heading:
                lines.append(f"\n## {heading}\n")

            if stype == "table" and isinstance(content, list):
                if content:
                    headers = list(content[0].keys())
                    lines.append("| " + " | ".join(headers) + " |")
                    lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
                    for row in content:
                        lines.append("| " + " | ".join(str(row.get(h, "")) for h in headers) + " |")
                    lines.append("")
            else:
                lines.append(str(content) + "\n")

        path = out_dir / f"{filename}.md"
        path.write_text("\n".join(lines))
        return {"success": True, "path": str(path), "format": "markdown"}

    async def _generate_html(self, title, sections, out_dir, filename) -> Dict[str, Any]:
        html_parts = [
            f"<!DOCTYPE html><html><head><title>{title}</title>",
            "<style>body{font-family:system-ui;max-width:800px;margin:auto;padding:2rem;background:#0a0a0a;color:#e0e0e0}",
            "table{width:100%;border-collapse:collapse;margin:1rem 0}th,td{border:1px solid #333;padding:8px;text-align:left}",
            "th{background:#1a1a2e}h1{color:#00d4ff}h2{color:#7b68ee}</style></head><body>",
            f"<h1>{title}</h1><p><em>{time.strftime('%Y-%m-%d %H:%M:%S')}</em></p><hr>",
        ]

        for section in sections:
            heading = section.get("heading", "")
            content = section.get("content", "")
            stype = section.get("type", "text")

            if heading:
                html_parts.append(f"<h2>{heading}</h2>")

            if stype == "table" and isinstance(content, list) and content:
                headers = list(content[0].keys())
                html_parts.append("<table><thead><tr>" + "".join(f"<th>{h}</th>" for h in headers) + "</tr></thead><tbody>")
                for row in content:
                    html_parts.append("<tr>" + "".join(f"<td>{row.get(h, '')}</td>" for h in headers) + "</tr>")
                html_parts.append("</tbody></table>")
            else:
                html_parts.append(f"<p>{content}</p>")

        html_parts.append("</body></html>")
        path = out_dir / f"{filename}.html"
        path.write_text("\n".join(html_parts))
        return {"success": True, "path": str(path), "format": "html"}


# Global instance
report_engine = ReportEngine()
