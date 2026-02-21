import subprocess
import os
import asyncio
from pathlib import Path
from typing import Dict, Any, Optional
from utils.logger import get_logger

logger = get_logger("slidev_generator")

class SlidevGenerator:
    def __init__(self):
        self.base_dir = Path.home() / ".elyan" / "projects" / "slides"
        self.base_dir.mkdir(parents=True, exist_ok=True)

    async def create_presentation(self, name: str, content: str) -> Dict[str, Any]:
        proj_dir = self.base_dir / name
        proj_dir.mkdir(parents=True, exist_ok=True)
        
        md_path = proj_dir / "slides.md"
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(content)
            
        logger.info(f"Slidev project created: {md_path}")
        return {
            "success": True,
            "path": str(md_path),
            "command": f"cd {proj_dir} && npx slidev"
        }

    async def export_pdf(self, name: str) -> Optional[str]:
        proj_dir = self.base_dir / name
        if not proj_dir.exists(): return None
        
        output_pdf = proj_dir / f"{name}.pdf"
        try:
            logger.info(f"Exporting Slidev to PDF: {name}")
            # Requires playwright installed for slidev
            subprocess.run(["npx", "slidev", "export", "--output", str(output_pdf)], cwd=proj_dir, check=True)
            return str(output_pdf)
        except Exception as e:
            logger.error(f"Slidev export error: {e}")
            return None

# Global instance
slidev_gen = SlidevGenerator()
