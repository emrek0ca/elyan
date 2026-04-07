import os
import pathlib
import shutil
import time
from typing import Any, Dict, List

from core.execution_guard import get_execution_guard
from core.observability.logger import get_structured_logger

slog = get_structured_logger("capability_filesystem")


def _identity_from_metadata(metadata: dict[str, Any] | None = None) -> dict[str, str]:
    payload = metadata if isinstance(metadata, dict) else {}
    nested = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    return {
        "workspace_id": str(payload.get("workspace_id") or nested.get("workspace_id") or "local-workspace").strip() or "local-workspace",
        "session_id": str(payload.get("session_id") or nested.get("session_id") or "").strip(),
        "run_id": str(payload.get("run_id") or nested.get("run_id") or "").strip(),
        "actor_id": str(payload.get("actor_id") or payload.get("user_id") or nested.get("actor_id") or nested.get("user_id") or "").strip(),
    }


def _observe_filesystem_runtime(
    *,
    action: str,
    success: bool,
    metadata: dict[str, Any] | None = None,
    reason: str = "",
    extra: dict[str, Any] | None = None,
) -> None:
    identity = _identity_from_metadata(metadata)
    verification = {
        "status": "success" if success else "failed",
        "ok": bool(success),
        "failed_codes": [] if success else ["filesystem_operation_failed"],
    }
    get_execution_guard().observe_capability_runtime(
        capability="filesystem",
        action=str(action or "").strip().lower(),
        success=bool(success),
        workspace_id=identity["workspace_id"],
        actor_id=identity["actor_id"],
        session_id=identity["session_id"],
        run_id=identity["run_id"],
        reason=str(reason or "").strip(),
        verification=verification,
        metadata=dict(extra or {}),
        level="info" if success else "warning",
    )


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

    async def list_directory(self, path: str, metadata: dict[str, Any] | None = None) -> Dict[str, Any]:
        if not self._is_safe_path(path):
            _observe_filesystem_runtime(
                action="list_directory",
                success=False,
                metadata=metadata,
                reason=f"Access denied: {path}",
                extra={"path": str(path or "")},
            )
            raise PermissionError(f"Access denied: {path}")

        p = pathlib.Path(path).expanduser().resolve()
        items = []
        for item in p.iterdir():
            items.append(
                {
                    "name": item.name,
                    "type": "directory" if item.is_dir() else "file",
                    "size": item.stat().st_size if item.is_file() else None,
                    "modified": item.stat().st_mtime,
                }
            )
        payload = {"items": items}
        _observe_filesystem_runtime(
            action="list_directory",
            success=True,
            metadata=metadata,
            extra={"path": str(p), "item_count": len(items)},
        )
        return payload

    async def read_file(self, path: str, metadata: dict[str, Any] | None = None) -> Dict[str, Any]:
        if not self._is_safe_path(path):
            _observe_filesystem_runtime(
                action="read_file",
                success=False,
                metadata=metadata,
                reason=f"Access denied: {path}",
                extra={"path": str(path or "")},
            )
            raise PermissionError(f"Access denied: {path}")

        p = pathlib.Path(path).expanduser().resolve()
        content = p.read_text(encoding="utf-8")
        payload = {"content": content}
        _observe_filesystem_runtime(
            action="read_file",
            success=True,
            metadata=metadata,
            extra={"path": str(p), "size": len(content)},
        )
        return payload

    async def write_file(self, path: str, content: str, atomic: bool = True, metadata: dict[str, Any] | None = None) -> Dict[str, Any]:
        if not self._is_safe_path(path):
            _observe_filesystem_runtime(
                action="write_file",
                success=False,
                metadata=metadata,
                reason=f"Access denied: {path}",
                extra={"path": str(path or ""), "atomic": bool(atomic)},
            )
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
        payload = {"status": "success", "path": str(p)}
        _observe_filesystem_runtime(
            action="write_file",
            success=True,
            metadata=metadata,
            extra={"path": str(p), "size": len(content), "atomic": bool(atomic)},
        )
        return payload

    async def trash_file(self, path: str, metadata: dict[str, Any] | None = None) -> Dict[str, Any]:
        """Moves a file to a local trash directory instead of deleting it."""
        if not self._is_safe_path(path):
            _observe_filesystem_runtime(
                action="trash_file",
                success=False,
                metadata=metadata,
                reason=f"Access denied: {path}",
                extra={"path": str(path or "")},
            )
            raise PermissionError(f"Access denied: {path}")

        p = pathlib.Path(path).expanduser().resolve()
        if not p.exists():
            _observe_filesystem_runtime(
                action="trash_file",
                success=False,
                metadata=metadata,
                reason=f"File not found: {path}",
                extra={"path": str(p)},
            )
            raise FileNotFoundError(f"File not found: {path}")

        trash_dir = pathlib.Path.home() / ".elyan" / "trash"
        trash_dir.mkdir(parents=True, exist_ok=True)

        target_path = trash_dir / f"{p.name}.{int(time.time())}.bak"
        shutil.move(str(p), str(target_path))

        slog.log_event("file_trashed", {"path": str(p), "trash_path": str(target_path)})
        payload = {"status": "success", "original_path": str(p), "trash_path": str(target_path)}
        _observe_filesystem_runtime(
            action="trash_file",
            success=True,
            metadata=metadata,
            extra={"path": str(p), "trash_path": str(target_path)},
        )
        return payload


# Global instance
filesystem_capability = FilesystemCapability()
