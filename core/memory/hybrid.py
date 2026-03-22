import os
import pathlib
import json
import time
from typing import Any, Dict, List, Optional
from core.observability.logger import get_structured_logger

slog = get_structured_logger("hybrid_memory")

class HybridMemory:
    """
    Implements the v2 Hybrid Memory model:
    - Readable Markdown files as the Source of Truth.
    - Flat files for profile, projects, and daily logs.
    """
    def __init__(self, base_dir: Optional[pathlib.Path] = None):
        self.base_dir = base_dir or pathlib.Path.home() / ".elyan" / "memory"
        self._ensure_dirs()

    def _ensure_dirs(self):
        """Creates the memory directory structure."""
        dirs = ["projects", "daily", "runs", "profile"]
        for d in dirs:
            (self.base_dir / d).mkdir(parents=True, exist_ok=True)

    def _get_project_path(self, project_id: str) -> pathlib.Path:
        p_dir = self.base_dir / "projects" / project_id
        p_dir.mkdir(parents=True, exist_ok=True)
        return p_dir / "MEMORY.md"

    def _get_daily_path(self) -> pathlib.Path:
        date_str = time.strftime("%Y-%m-%d")
        return self.base_dir / "daily" / f"{date_str}.md"

    def _get_profile_path() -> pathlib.Path:
        # User profile is usually global for now
        pass

    async def write_project_memory(self, project_id: str, content: str, append: bool = True):
        """Writes or appends to a project's MEMORY.md."""
        path = self._get_project_path(project_id)
        mode = "a" if append else "w"
        
        with open(path, mode, encoding="utf-8") as f:
            if append and path.stat().st_size > 0:
                f.write("\n\n---\n") # Separator for appends
            f.write(content)
            
        slog.log_event("memory_written", {"type": "project", "project_id": project_id, "size": len(content)})

    async def write_daily_log(self, content: str):
        """Appends to the daily YYYY-MM-DD.md log."""
        path = self._get_daily_path()
        timestamp = time.strftime("%H:%M:%S")
        
        header = f"## [{timestamp}]\n"
        full_content = f"{header}{content}\n"
        
        with open(path, "a", encoding="utf-8") as f:
            f.write(full_content)
            
        slog.log_event("memory_written", {"type": "daily", "size": len(full_content)})

    async def read_project_memory(self, project_id: str) -> str:
        path = self._get_project_path(project_id)
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    async def get_recent_daily_logs(self, days: int = 3) -> Dict[str, str]:
        """Retrieves the last N daily logs."""
        logs = {}
        for i in range(days):
            date_str = (pathlib.Path.home() / ".elyan" / "memory" / "daily").glob("*.md")
            # This is a placeholder, should ideally iterate through dates
        return logs

# Global instance
hybrid_memory = HybridMemory()
