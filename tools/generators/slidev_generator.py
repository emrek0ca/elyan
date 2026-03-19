"""Slidev presentation generator with manifest-aware output."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional

from tools.office_tools.content_manifest import manifest_to_slide_markdown
from utils.logger import get_logger

logger = get_logger("slidev_generator")


class SlidevGenerator:
    def __init__(self):
        self.base_dir = Path.home() / ".elyan" / "projects" / "slides"
        self.base_dir.mkdir(parents=True, exist_ok=True)

    async def create_presentation(self, name: str, content: str | dict[str, Any]) -> Dict[str, Any]:
        proj_dir = self.base_dir / name
        proj_dir.mkdir(parents=True, exist_ok=True)

        manifest_payload: dict[str, Any] | None = None
        if isinstance(content, dict):
            manifest_payload = dict(content.get("office_content_manifest") or content)
            deck_markdown = manifest_to_slide_markdown(manifest_payload)
        else:
            deck_markdown = str(content or "").strip()

        md_path = proj_dir / "slides.md"
        md_path.write_text(deck_markdown + ("\n" if deck_markdown and not deck_markdown.endswith("\n") else ""), encoding="utf-8")

        manifest_path = ""
        if manifest_payload:
            manifest_path_obj = proj_dir / "office_content_manifest.json"
            manifest_path_obj.write_text(json.dumps(manifest_payload, ensure_ascii=False, indent=2), encoding="utf-8")
            manifest_path = str(manifest_path_obj)

        logger.info(f"Slidev project created: {md_path}")
        response: Dict[str, Any] = {
            "success": True,
            "path": str(md_path),
            "command": f"cd {proj_dir} && npx slidev",
        }
        if manifest_path:
            response["manifest_path"] = manifest_path
        return response

    async def export_pdf(self, name: str) -> Optional[str]:
        proj_dir = self.base_dir / name
        if not proj_dir.exists():
            return None

        output_pdf = proj_dir / f"{name}.pdf"
        try:
            logger.info(f"Exporting Slidev to PDF: {name}")
            subprocess.run(["npx", "slidev", "export", "--output", str(output_pdf)], cwd=proj_dir, check=True)
            return str(output_pdf)
        except Exception as exc:
            logger.error(f"Slidev export error: {exc}")
            return None


# Global instance
slidev_gen = SlidevGenerator()
