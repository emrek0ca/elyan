import pathlib
import json
from typing import Any, Dict, List, Optional
from core.workspace_contract import ensure_workspace_contract
from core.observability.logger import get_structured_logger

slog = get_structured_logger("workspace_manager")

class WorkspaceManager:
    """
    Manages Elyan project workspaces and their contracts.
    """
    def __init__(self, base_dir: Optional[pathlib.Path] = None):
        self.base_dir = base_dir or pathlib.Path.home() / ".elyan" / "workspaces"
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._workspaces: Dict[str, Dict[str, Any]] = {}
        self._load_registry()

    def _load_registry(self):
        reg_path = self.base_dir / "registry.json"
        if reg_path.exists():
            try:
                self._workspaces = json.loads(reg_path.read_text(encoding="utf-8"))
            except Exception:
                self._workspaces = {}

    def _save_registry(self):
        reg_path = self.base_dir / "registry.json"
        reg_path.write_text(json.dumps(self._workspaces, indent=2, ensure_ascii=False), encoding="utf-8")

    async def get_or_create_workspace(self, workspace_id: str, role: str = "general") -> Dict[str, Any]:
        """Resolves a workspace ID to a physical path and ensures contracts."""
        if workspace_id in self._workspaces:
            ws_data = self._workspaces[workspace_id]
            path = ws_data["path"]
        else:
            path = str(self.base_dir / workspace_id)
            self._workspaces[workspace_id] = {
                "path": path,
                "role": role,
                "created_at": pathlib.Path(path).stat().st_ctime if pathlib.Path(path).exists() else None
            }
            self._save_registry()

        # Ensure directory and contracts exist
        ensure_workspace_contract(path, role=role)
        
        slog.log_event("workspace_resolved", {"workspace_id": workspace_id, "path": path})
        return self._workspaces[workspace_id]

    async def list_workspaces(self) -> List[Dict[str, Any]]:
        return [{"id": k, **v} for k, v in self._workspaces.items()]

# Global instance
workspace_manager = WorkspaceManager()
