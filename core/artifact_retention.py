from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any, Dict

from config.elyan_config import elyan_config
from core.storage_paths import resolve_elyan_data_dir, resolve_runs_root


def _cfg_int(key: str, default: int, minimum: int, maximum: int) -> int:
    try:
        raw = elyan_config.get(key, default)
        value = int(default if raw in (None, "") else raw)
    except Exception:
        value = int(default)
    return max(minimum, min(maximum, value))


def _cfg_bool(key: str, default: bool = True) -> bool:
    value = elyan_config.get(key, default)
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in {"0", "false", "no", "off", "disabled"}:
        return False
    if text in {"1", "true", "yes", "on", "enabled"}:
        return True
    return bool(default)


def _mtime(path: Path) -> float:
    try:
        latest = float(path.stat().st_mtime)
    except Exception:
        return 0.0
    if path.is_dir():
        for item in path.rglob("*"):
            try:
                latest = max(latest, float(item.stat().st_mtime))
            except Exception:
                continue
    return latest


def _remove_path(path: Path) -> tuple[int, int]:
    files = 0
    bytes_freed = 0
    try:
        if path.is_file():
            bytes_freed = int(path.stat().st_size)
            path.unlink(missing_ok=True)
            return 1, bytes_freed
        if path.is_dir():
            for item in path.rglob("*"):
                if item.is_file():
                    files += 1
                    try:
                        bytes_freed += int(item.stat().st_size)
                    except Exception:
                        pass
            shutil.rmtree(path, ignore_errors=True)
    except Exception:
        return 0, 0
    return files, bytes_freed


def _prune_top_level_children(root: Path, *, cutoff_ts: float, keep_recent: int = 0) -> Dict[str, Any]:
    if not root.exists():
        return {"removed": 0, "freed_mb": 0.0}
    children = [item for item in root.iterdir() if item.exists()]
    children.sort(key=_mtime, reverse=True)
    keep = {str(item) for item in children[: max(0, int(keep_recent or 0))]}
    removed = 0
    bytes_freed = 0
    for child in children:
        if str(child) in keep or _mtime(child) >= cutoff_ts:
            continue
        count, freed = _remove_path(child)
        removed += count
        bytes_freed += freed
    return {"removed": removed, "freed_mb": round(bytes_freed / 1048576, 2)}


def _prune_old_files(root: Path, *, cutoff_ts: float) -> Dict[str, Any]:
    if not root.exists():
        return {"removed": 0, "freed_mb": 0.0}
    removed = 0
    bytes_freed = 0
    for item in root.rglob("*"):
        try:
            if not item.is_file() or _mtime(item) >= cutoff_ts:
                continue
            bytes_freed += int(item.stat().st_size)
            item.unlink(missing_ok=True)
            removed += 1
        except Exception:
            continue
    for directory in sorted((p for p in root.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
        try:
            if not any(directory.iterdir()):
                directory.rmdir()
        except Exception:
            continue
    return {"removed": removed, "freed_mb": round(bytes_freed / 1048576, 2)}


def prune_elyan_artifacts() -> Dict[str, Any]:
    base_dir = resolve_elyan_data_dir()
    runs_cutoff = time.time() - (_cfg_int("maintenance.runsRetentionDays", 14, 1, 365) * 86400)
    reports_cutoff = time.time() - (_cfg_int("maintenance.reportsRetentionDays", 30, 1, 365) * 86400)
    jobs_cutoff = time.time() - (_cfg_int("maintenance.jobsRetentionDays", 14, 1, 365) * 86400)
    keep_recent_runs = _cfg_int("maintenance.keepRecentRuns", 200, 0, 5000)
    keep_recent_jobs = _cfg_int("maintenance.keepRecentJobs", 50, 0, 2000)

    details = {
        "runs": _prune_top_level_children(resolve_runs_root(), cutoff_ts=runs_cutoff, keep_recent=keep_recent_runs),
        "reports": _prune_old_files(base_dir / "reports", cutoff_ts=reports_cutoff),
        "jobs": _prune_top_level_children(base_dir / "jobs", cutoff_ts=jobs_cutoff, keep_recent=keep_recent_jobs),
    }
    total_removed = sum(int(item.get("removed") or 0) for item in details.values())
    total_freed = round(sum(float(item.get("freed_mb") or 0.0) for item in details.values()), 2)
    return {
        "success": True,
        "removed": total_removed,
        "freed_mb": total_freed,
        "details": details,
    }


def maybe_prune_elyan_artifacts(*, min_interval_hours: int = 6) -> Dict[str, Any]:
    if not _cfg_bool("maintenance.artifactRetentionEnabled", True):
        return {"success": True, "skipped": True, "reason": "disabled"}
    base_dir = resolve_elyan_data_dir()
    maintenance_dir = base_dir / "maintenance"
    maintenance_dir.mkdir(parents=True, exist_ok=True)
    state_path = maintenance_dir / "artifact_retention_state.json"
    now = time.time()
    min_interval_s = max(1800, int(min_interval_hours or 6) * 3600)
    state: Dict[str, Any] = {}
    if state_path.exists():
        try:
            loaded = json.loads(state_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                state = loaded
        except Exception:
            state = {}
    last_run = float(state.get("last_run_ts", 0.0) or 0.0)
    if last_run and (now - last_run) < min_interval_s:
        return {"success": True, "skipped": True, "reason": "cooldown", "last_run_ts": last_run}
    result = prune_elyan_artifacts()
    state_path.write_text(
        json.dumps({"last_run_ts": now, "last_result": result}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    result["skipped"] = False
    return result


__all__ = ["maybe_prune_elyan_artifacts", "prune_elyan_artifacts"]
