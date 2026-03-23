"""
Run Store - Tracks execution runs with steps, tool calls, and status.

Provides persistent storage of run records in ~/.elyan/runs/<run_id>.json
"""

import json
import os
import asyncio
from dataclasses import dataclass, asdict, field
from typing import Optional, List, Dict, Any
from datetime import datetime
from pathlib import Path

from core.observability.logger import get_structured_logger

slog = get_structured_logger("run_store")


@dataclass
class RunStep:
    """Single step in a run."""
    step_id: str
    name: str
    status: str  # pending, running, completed, error, skipped
    started_at: float
    completed_at: Optional[float] = None
    error: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    dependencies: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)

    def duration_seconds(self) -> Optional[float]:
        """Get step duration."""
        if self.completed_at:
            return self.completed_at - self.started_at
        return None


@dataclass
class RunRecord:
    """Single execution run record."""
    run_id: str
    session_id: str
    status: str  # pending, completed, error, cancelled
    intent: str
    steps: List[Dict[str, Any]] = field(default_factory=list)
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    started_at: float = field(default_factory=lambda: datetime.now().timestamp())
    completed_at: Optional[float] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return asdict(self)

    def duration_seconds(self) -> Optional[float]:
        """Get duration if completed."""
        if self.completed_at:
            return self.completed_at - self.started_at
        return None


class RunStore:
    """Manages persistent run record storage."""

    def __init__(self, store_path: Optional[str] = None):
        """Initialize run store.

        Args:
            store_path: Custom storage path, defaults to ~/.elyan/runs
        """
        if store_path is None:
            store_path = os.path.expanduser("~/.elyan/runs")
        self.store_path = Path(store_path)
        self.store_path.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()

    async def record_run(self, run: RunRecord) -> None:
        """Save a run record to disk."""
        async with self._lock:
            try:
                file_path = self.store_path / f"{run.run_id}.json"
                # Write to temporary file first, then rename (atomic)
                temp_path = file_path.with_suffix(".tmp")
                with open(temp_path, "w") as f:
                    json.dump(run.to_dict(), f, indent=2, default=str)
                temp_path.replace(file_path)
                slog.log_event("run_recorded", {
                    "run_id": run.run_id,
                    "status": run.status
                })
            except Exception as e:
                slog.log_event("run_record_error", {
                    "run_id": run.run_id,
                    "error": str(e)
                }, level="error")

    async def get_run(self, run_id: str) -> Optional[RunRecord]:
        """Retrieve a run record by ID."""
        async with self._lock:
            try:
                file_path = self.store_path / f"{run_id}.json"
                if not file_path.exists():
                    return None
                with open(file_path, "r") as f:
                    data = json.load(f)
                return RunRecord(**data)
            except Exception as e:
                slog.log_event("run_get_error", {
                    "run_id": run_id,
                    "error": str(e)
                }, level="warning")
                return None

    async def list_runs(
        self,
        limit: int = 20,
        status: Optional[str] = None
    ) -> List[RunRecord]:
        """List runs, optionally filtered by status.

        Args:
            limit: Maximum number of runs to return
            status: Filter by status (pending, completed, error, cancelled)

        Returns:
            List of RunRecord objects, most recent first
        """
        async with self._lock:
            try:
                runs = []
                files = sorted(
                    self.store_path.glob("*.json"),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True
                )
                for file_path in files[:limit * 2]:  # Read more to filter
                    try:
                        with open(file_path, "r") as f:
                            data = json.load(f)
                            run = RunRecord(**data)
                            if status is None or run.status == status:
                                runs.append(run)
                                if len(runs) >= limit:
                                    break
                    except Exception as e:
                        slog.log_event("run_list_file_error", {
                            "file": file_path.name,
                            "error": str(e)
                        }, level="warning")
                return runs
            except Exception as e:
                slog.log_event("run_list_error", {
                    "error": str(e)
                }, level="error")
                return []

    async def cancel_run(self, run_id: str) -> bool:
        """Mark a run as cancelled."""
        async with self._lock:
            try:
                file_path = self.store_path / f"{run_id}.json"
                if not file_path.exists():
                    return False
                with open(file_path, "r") as f:
                    data = json.load(f)
                data["status"] = "cancelled"
                data["completed_at"] = datetime.now().timestamp()
                with open(file_path, "w") as f:
                    json.dump(data, f, indent=2, default=str)
                slog.log_event("run_cancelled", {"run_id": run_id})
                return True
            except Exception as e:
                slog.log_event("run_cancel_error", {
                    "run_id": run_id,
                    "error": str(e)
                }, level="error")
                return False

    async def cleanup_old_runs(self, days: int = 7) -> int:
        """Delete runs older than N days. Returns count deleted."""
        async with self._lock:
            try:
                cutoff = datetime.now().timestamp() - (days * 86400)
                deleted = 0
                for file_path in self.store_path.glob("*.json"):
                    try:
                        stat = file_path.stat()
                        if stat.st_mtime < cutoff:
                            file_path.unlink()
                            deleted += 1
                    except Exception:
                        pass
                if deleted > 0:
                    slog.log_event("runs_cleanup", {"deleted": deleted})
                return deleted
            except Exception as e:
                slog.log_event("run_cleanup_error", {
                    "error": str(e)
                }, level="error")
                return 0

    async def get_step_timeline(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Get step timeline for visualization (Gantt chart data).

        Returns:
            Dict with steps, timeline, critical path, or None if run not found
        """
        run = await self.get_run(run_id)
        if not run:
            return None

        if not run.steps:
            return {
                "run_id": run_id,
                "steps": [],
                "total_duration": run.duration_seconds(),
                "critical_path": [],
                "step_count": 0
            }

        # Build timeline
        timeline = []
        for step_data in run.steps:
            if isinstance(step_data, dict):
                step = step_data
            else:
                step = asdict(step_data)

            timeline.append({
                "step_id": step.get("step_id", f"step_{len(timeline)}"),
                "name": step.get("name", "Unknown"),
                "status": step.get("status", "unknown"),
                "start": step.get("started_at", 0),
                "duration": step.get("completed_at", step.get("started_at", 0)) - step.get("started_at", 0) if step.get("completed_at") else 0,
                "dependencies": step.get("dependencies", []),
                "error": step.get("error")
            })

        # Calculate critical path
        critical_path = self._calculate_critical_path(timeline)

        return {
            "run_id": run_id,
            "steps": timeline,
            "total_duration": run.duration_seconds(),
            "critical_path": critical_path,
            "step_count": len(timeline),
            "run_status": run.status
        }

    def _calculate_critical_path(self, steps: List[Dict[str, Any]]) -> List[str]:
        """Calculate critical path through steps."""
        if not steps:
            return []

        # Find steps with no dependencies (start steps)
        start_steps = [s for s in steps if not s.get("dependencies")]
        if not start_steps:
            return [s["step_id"] for s in steps[:1]]  # Fallback

        # Simple critical path: longest duration chain
        visited = set()
        path = []

        def find_longest_path(step_id: str) -> float:
            if step_id in visited:
                return 0
            visited.add(step_id)

            step = next((s for s in steps if s["step_id"] == step_id), None)
            if not step:
                return 0

            duration = step.get("duration", 0)
            max_child_duration = 0

            # Find dependent steps (reverse dependencies)
            for s in steps:
                if step_id in s.get("dependencies", []):
                    child_duration = find_longest_path(s["step_id"])
                    if child_duration > max_child_duration:
                        max_child_duration = child_duration

            return duration + max_child_duration

        # Calculate longest path
        longest_path = []
        longest_duration = 0

        for start_step in start_steps:
            visited.clear()
            duration = find_longest_path(start_step["step_id"])
            if duration > longest_duration:
                longest_duration = duration
                longest_path = [start_step["step_id"]]

        return longest_path


# Global instance
_run_store: Optional[RunStore] = None


def get_run_store(store_path: Optional[str] = None) -> RunStore:
    """Get or create the run store singleton."""
    global _run_store
    if _run_store is None:
        _run_store = RunStore(store_path)
    return _run_store
