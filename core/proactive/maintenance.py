"""
Elyan Maintenance Engine — Autonomous system maintenance

Log cleanup, cache invalidation, old file archiving, disk optimization.
"""

import os
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List
from config.elyan_config import elyan_config
from utils.logger import get_logger

logger = get_logger("maintenance")


class MaintenanceEngine:
    """Autonomous system maintenance tasks."""

    def __init__(self):
        self.log_dir = Path.home() / ".elyan" / "logs"
        self.cache_dir = Path.home() / ".elyan" / "cache"
        self.inbox_dir = Path.home() / ".elyan" / "inbox"
        self.proofs_dir = Path.home() / ".elyan" / "proofs"
        self.archive_dir = Path.home() / ".elyan" / "archive"
        self.archive_dir.mkdir(parents=True, exist_ok=True)

    async def run_full_maintenance(self) -> Dict[str, Any]:
        """Run all maintenance tasks."""
        results = {}
        results["log_cleanup"] = await self.cleanup_logs(max_age_days=7)
        results["cache_cleanup"] = await self.cleanup_cache()
        results["temp_cleanup"] = await self.cleanup_temp()
        retention_days = int(elyan_config.get("memory.attachmentRetentionDays", 7) or 7)
        retention_days = max(1, min(60, retention_days))
        results["inbox_cleanup"] = await self.cleanup_inbox(max_age_days=retention_days)
        results["proofs_cleanup"] = await self.cleanup_proofs(max_age_days=retention_days)
        
        total_freed = sum(r.get("freed_mb", 0) for r in results.values())
        return {
            "success": True,
            "tasks_completed": len(results),
            "total_freed_mb": round(total_freed, 2),
            "details": results,
        }

    async def cleanup_logs(self, max_age_days: int = 7) -> Dict[str, Any]:
        """Remove old log files."""
        if not self.log_dir.exists():
            return {"success": True, "removed": 0, "freed_mb": 0}

        cutoff = time.time() - (max_age_days * 86400)
        removed = 0
        freed = 0

        for log_file in self.log_dir.rglob("*.log"):
            try:
                if log_file.stat().st_mtime < cutoff:
                    freed += log_file.stat().st_size
                    log_file.unlink()
                    removed += 1
            except Exception:
                continue

        return {"success": True, "removed": removed, "freed_mb": round(freed / 1048576, 2)}

    async def cleanup_cache(self) -> Dict[str, Any]:
        """Clear expired cache entries."""
        if not self.cache_dir.exists():
            return {"success": True, "removed": 0, "freed_mb": 0}

        cutoff = time.time() - 86400  # 24h
        removed = 0
        freed = 0

        for cache_file in self.cache_dir.rglob("*"):
            if cache_file.is_file():
                try:
                    if cache_file.stat().st_mtime < cutoff:
                        freed += cache_file.stat().st_size
                        cache_file.unlink()
                        removed += 1
                except Exception:
                    continue

        return {"success": True, "removed": removed, "freed_mb": round(freed / 1048576, 2)}

    async def cleanup_temp(self) -> Dict[str, Any]:
        """Remove old Elyan temp directories."""
        import tempfile
        temp_base = Path(tempfile.gettempdir())
        removed = 0
        freed = 0

        for d in temp_base.glob("elyan_*"):
            try:
                if d.is_dir() and (time.time() - d.stat().st_mtime > 3600):
                    size = sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
                    shutil.rmtree(d, ignore_errors=True)
                    freed += size
                    removed += 1
            except Exception:
                continue

        return {"success": True, "removed": removed, "freed_mb": round(freed / 1048576, 2)}

    async def cleanup_inbox(self, max_age_days: int = 7) -> Dict[str, Any]:
        return await self._cleanup_path_tree(self.inbox_dir, max_age_days=max_age_days)

    async def cleanup_proofs(self, max_age_days: int = 7) -> Dict[str, Any]:
        return await self._cleanup_path_tree(self.proofs_dir, max_age_days=max_age_days)

    async def _cleanup_path_tree(self, root: Path, max_age_days: int = 7) -> Dict[str, Any]:
        if not root.exists():
            return {"success": True, "removed": 0, "freed_mb": 0}

        cutoff = time.time() - (max_age_days * 86400)
        removed = 0
        freed = 0
        for p in root.rglob("*"):
            try:
                if p.is_file() and p.stat().st_mtime < cutoff:
                    freed += p.stat().st_size
                    p.unlink()
                    removed += 1
            except Exception:
                continue
        return {"success": True, "removed": removed, "freed_mb": round(freed / 1048576, 2)}


# Global instance
maintenance = MaintenanceEngine()
