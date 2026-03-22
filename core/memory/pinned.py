import json
import pathlib
from typing import Any, Dict, List, Optional
from core.observability.logger import get_structured_logger

slog = get_structured_logger("pinned_memory")

class PinnedMemory:
    """
    Manages "Pinned" context items that are always included in the prompt.
    Useful for stable system rules, specific project constraints, or constant user facts.
    """
    def __init__(self, base_dir: Optional[pathlib.Path] = None):
        self.base_dir = base_dir or pathlib.Path.home() / ".elyan" / "memory" / "pinned"
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._pins: Dict[str, str] = {}
        self._load_pins()

    def _load_pins(self):
        for p in self.base_dir.glob("*.txt"):
            self._pins[p.stem] = p.read_text(encoding="utf-8")

    def pin(self, key: str, content: str):
        """Adds or updates a pinned item."""
        self._pins[key] = content
        (self.base_dir / f"{key}.txt").write_text(content, encoding="utf-8")
        slog.log_event("memory_pinned", {"key": key, "size": len(content)})

    def unpin(self, key: str):
        """Removes a pinned item."""
        if key in self._pins:
            del self._pins[key]
            (self.base_dir / f"{key}.txt").unlink(missing_ok=True)
            slog.log_event("memory_unpinned", {"key": key})

    def get_all_pinned_content(self) -> str:
        """Returns all pinned content formatted for a prompt."""
        if not self._pins:
            return ""
        
        blocks = ["### PINNED CONTEXT & CONSTRAINTS"]
        for key, content in self._pins.items():
            blocks.append(f"#### {key.upper()}\n{content}")
        
        return "\n\n".join(blocks)

# Global instance
pinned_memory = PinnedMemory()
