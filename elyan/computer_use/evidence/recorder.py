"""ComputerUseRecorder — Evidence & Audit Trail Recording

Records all evidence from computer use tasks:
- Screenshots (PNG)
- Action trace (JSONL)
- Metadata (JSON)
- Video (optional, MP4)
"""

import json
import os
from pathlib import Path
from typing import Optional
from datetime import datetime

from core.observability.logger import get_structured_logger

slog = get_structured_logger("evidence_recorder")


class ComputerUseRecorder:
    """Record evidence from computer use tasks"""

    def __init__(self, storage_path: Optional[str] = None):
        """
        Initialize recorder

        Args:
            storage_path: Base directory for evidence (~/.elyan/computer_use/evidence)
        """
        if storage_path is None:
            storage_path = os.path.expanduser("~/.elyan/computer_use/evidence")

        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)

        slog.log_event("evidence_recorder_init", {
            "storage_path": str(self.storage_path)
        })

    async def record_task(self, task: dict) -> dict:
        """
        Record a complete computer use task

        Args:
            task: ComputerUseTask dict with all details

        Returns:
            {
                "success": bool,
                "task_id": str,
                "evidence_dir": str,
                "files_saved": {
                    "metadata": "metadata.json",
                    "action_trace": "action_trace.jsonl",
                    "screenshots": ["ss_0.png", "ss_1.png", ...]
                }
            }
        """
        task_id = task.get("task_id", f"task_{int(__import__('time').time())}")

        try:
            # Create task directory
            task_dir = self.storage_path / task_id
            task_dir.mkdir(parents=True, exist_ok=True)

            # Save metadata
            metadata = {
                "task_id": task_id,
                "user_intent": task.get("user_intent"),
                "status": task.get("status"),
                "created_at": task.get("created_at"),
                "completed_at": task.get("completed_at"),
                "steps": task.get("steps", 0),
                "evidence_count": len(task.get("evidence", [])),
                "error": task.get("error")
            }
            metadata_file = task_dir / "metadata.json"
            with open(metadata_file, "w") as f:
                json.dump(metadata, f, indent=2)

            # Save action trace (JSONL format)
            action_trace_file = task_dir / "action_trace.jsonl"
            with open(action_trace_file, "w") as f:
                for action in task.get("action_trace", []):
                    f.write(json.dumps(action) + "\n")

            # Create screenshots directory
            screenshots_dir = task_dir / "screenshots"
            screenshots_dir.mkdir(exist_ok=True)

            slog.log_event("evidence_task_recorded", {
                "task_id": task_id,
                "status": task.get("status"),
                "evidence_dir": str(task_dir),
                "files": {
                    "metadata": str(metadata_file),
                    "action_trace": str(action_trace_file),
                    "screenshots_dir": str(screenshots_dir)
                }
            })

            return {
                "success": True,
                "task_id": task_id,
                "evidence_dir": str(task_dir),
                "files_saved": {
                    "metadata": "metadata.json",
                    "action_trace": "action_trace.jsonl",
                    "screenshots_dir": "screenshots/"
                }
            }

        except Exception as e:
            slog.log_event("evidence_recording_error", {
                "task_id": task_id,
                "error": str(e)
            }, level="error")

            return {
                "success": False,
                "task_id": task_id,
                "error": str(e)
            }

    async def save_screenshot(
        self,
        task_id: str,
        screenshot_id: str,
        screenshot_bytes: bytes
    ) -> bool:
        """
        Save a single screenshot

        Args:
            task_id: Task identifier
            screenshot_id: Screenshot identifier (e.g., "ss_0")
            screenshot_bytes: PNG/JPG image bytes

        Returns:
            True if successful
        """
        try:
            task_dir = self.storage_path / task_id / "screenshots"
            task_dir.mkdir(parents=True, exist_ok=True)

            screenshot_file = task_dir / f"{screenshot_id}.png"
            with open(screenshot_file, "wb") as f:
                f.write(screenshot_bytes)

            return True
        except Exception as e:
            slog.log_event("screenshot_save_error", {
                "task_id": task_id,
                "screenshot_id": screenshot_id,
                "error": str(e)
            }, level="error")
            return False

    async def get_task_evidence(self, task_id: str) -> dict:
        """
        Retrieve evidence for a task

        Args:
            task_id: Task identifier

        Returns:
            {
                "task_id": str,
                "metadata": dict,
                "action_trace": list[dict],
                "screenshots": list[str],
                "evidence_dir": str
            }
        """
        try:
            task_dir = self.storage_path / task_id

            if not task_dir.exists():
                return {
                    "success": False,
                    "error": f"Task {task_id} not found"
                }

            # Load metadata
            metadata_file = task_dir / "metadata.json"
            metadata = {}
            if metadata_file.exists():
                with open(metadata_file, "r") as f:
                    metadata = json.load(f)

            # Load action trace
            action_trace = []
            action_trace_file = task_dir / "action_trace.jsonl"
            if action_trace_file.exists():
                with open(action_trace_file, "r") as f:
                    for line in f:
                        if line.strip():
                            action_trace.append(json.loads(line))

            # List screenshots
            screenshots = []
            screenshots_dir = task_dir / "screenshots"
            if screenshots_dir.exists():
                screenshots = sorted([
                    f.name for f in screenshots_dir.glob("*.png")
                ])

            return {
                "success": True,
                "task_id": task_id,
                "metadata": metadata,
                "action_trace": action_trace,
                "screenshots": screenshots,
                "evidence_dir": str(task_dir),
                "total_steps": len(action_trace),
                "total_screenshots": len(screenshots)
            }

        except Exception as e:
            slog.log_event("evidence_retrieval_error", {
                "task_id": task_id,
                "error": str(e)
            }, level="error")

            return {
                "success": False,
                "task_id": task_id,
                "error": str(e)
            }

    async def cleanup_old_evidence(self, days: int = 7) -> dict:
        """
        Clean up evidence older than N days

        Args:
            days: Keep evidence newer than this many days

        Returns:
            {"cleaned": int, "freed_mb": float}
        """
        import shutil
        import time

        try:
            now = time.time()
            cutoff = now - (days * 24 * 3600)
            cleaned = 0
            freed_bytes = 0

            for task_dir in self.storage_path.iterdir():
                if not task_dir.is_dir():
                    continue

                mtime = task_dir.stat().st_mtime
                if mtime < cutoff:
                    size = sum(
                        f.stat().st_size
                        for f in task_dir.rglob("*")
                        if f.is_file()
                    )
                    shutil.rmtree(task_dir)
                    cleaned += 1
                    freed_bytes += size

            slog.log_event("evidence_cleanup", {
                "days": days,
                "cleaned": cleaned,
                "freed_mb": freed_bytes / (1024 * 1024)
            })

            return {
                "cleaned": cleaned,
                "freed_mb": freed_bytes / (1024 * 1024)
            }

        except Exception as e:
            slog.log_event("cleanup_error", {
                "error": str(e)
            }, level="error")
            return {"error": str(e)}


# ============================================================================
# SINGLETON
# ============================================================================

_recorder: Optional[ComputerUseRecorder] = None


async def get_evidence_recorder(storage_path: Optional[str] = None) -> ComputerUseRecorder:
    """Get or create ComputerUseRecorder singleton"""
    global _recorder
    if _recorder is None:
        _recorder = ComputerUseRecorder(storage_path=storage_path)
    return _recorder
