import pathlib
import shutil
import os
from typing import Any, Dict, List, Optional
from core.observability.logger import get_structured_logger

slog = get_structured_logger("rollback_engine")

class RollbackEngine:
    """
    Handles reversing side effects when actions fail or are cancelled.
    """
    async def rollback_action(self, capability: str, action: str, params: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
        """
        Attempts to undo a specific action.
        """
        if capability == "filesystem":
            return await self._rollback_filesystem(action, params, result)
        
        return {"status": "unsupported", "reason": f"No rollback logic for {capability}.{action}"}

    async def _rollback_filesystem(self, action: str, params: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
        if action == "write_file":
            # If we wrote a file, rollback means deleting it (or restoring previous if we had snapshots)
            # For v1, we just log that we could delete it if it was a new file.
            path = params.get("path")
            p = pathlib.Path(path).expanduser().resolve()
            if p.exists():
                # In a more advanced version, we'd restore from a backup.
                return {"status": "manual_intervention_required", "reason": f"Rollback for write_file requires manual restoration of {path}"}

        if action == "trash_file":
            # If we trashed it, rollback means moving it back from trash
            trash_path = result.get("trash_path")
            original_path = result.get("original_path")
            
            if trash_path and original_path:
                tp = pathlib.Path(trash_path)
                op = pathlib.Path(original_path)
                if tp.exists():
                    shutil.move(str(tp), str(op))
                    slog.log_event("file_restored", {"path": str(op), "from": str(tp)})
                    return {"status": "success", "path": str(op)}
            
        return {"status": "failed", "reason": "Insufficient metadata for filesystem rollback"}

# Global instance
rollback_engine = RollbackEngine()
