import os
import shutil
import pathlib
from typing import Any, Dict, List, Optional
from core.protocol.shared_types import RiskLevel
from core.observability.logger import get_structured_logger

slog = get_structured_logger("capability_filesystem")

class FilesystemCapability:
    """
    Implements safe filesystem operations according to ADR-007.
    """
    def __init__(self, allowed_roots: List[str] = None):
        self.allowed_roots = allowed_roots or [str(pathlib.Path.home())]

    def _is_safe_path(self, path: str) -> bool:
        resolved = pathlib.Path(path).expanduser().resolve()
        for root in self.allowed_roots:
            if str(resolved).startswith(str(pathlib.Path(root).expanduser().resolve())):
                return True
        return False

    async def list_directory(self, path: str) -> Dict[str, Any]:
        if not self._is_safe_path(path):
            raise PermissionError(f"Access denied: {path}")
        
        p = pathlib.Path(path).expanduser().resolve()
        items = []
        for item in p.iterdir():
            items.append({
                "name": item.name,
                "type": "directory" if item.is_dir() else "file",
                "size": item.stat().st_size if item.is_file() else None,
                "modified": item.stat().st_mtime
            })
        return {"items": items}

    async def read_file(self, path: str) -> Dict[str, Any]:
        if not self._is_safe_path(path):
            raise PermissionError(f"Access denied: {path}")
        
        p = pathlib.Path(path).expanduser().resolve()
        content = p.read_text(encoding="utf-8")
        return {"content": content}

    async def write_file(self, path: str, content: str, atomic: bool = True) -> Dict[str, Any]:
        if not self._is_safe_path(path):
            raise PermissionError(f"Access denied: {path}")
        
        p = pathlib.Path(path).expanduser().resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        
        if atomic:
            temp_path = p.with_suffix(f".{os.getpid()}.tmp")
            temp_path.write_text(content, encoding="utf-8")
            temp_path.replace(p)
        else:
            p.write_text(content, encoding="utf-8")
            
        slog.log_event("file_written", {"path": str(p), "size": len(content), "atomic": atomic})
        return {"status": "success", "path": str(p)}

    async def trash_file(self, path: str) -> Dict[str, Any]:
        """Moves a file to a local trash directory instead of deleting it."""
        if not self._is_safe_path(path):
            raise PermissionError(f"Access denied: {path}")
            
        p = pathlib.Path(path).expanduser().resolve()
        if not p.exists():
            raise FileNotFoundError(f"File not found: {path}")
            
        trash_dir = pathlib.Path.home() / ".elyan" / "trash"
        trash_dir.mkdir(parents=True, exist_ok=True)
        
        target_path = trash_dir / f"{p.name}.{int(os.time.time())}.bak"
        shutil.move(str(p), str(target_path))
        
        slog.log_event("file_trashed", {"path": str(p), "trash_path": str(target_path)})
        return {"status": "success", "original_path": str(p), "trash_path": str(target_path)}

# Global instance
filesystem_capability = FilesystemCapability()
