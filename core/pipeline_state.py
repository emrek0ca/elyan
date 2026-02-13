"""
Pipeline state manager for resumable long-running tasks.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from utils.logger import get_logger

logger = get_logger("pipeline_state")


class PipelineStateManager:
    def __init__(self, state_path: Path | None = None):
        if state_path is None:
            preferred = Path.home() / ".wiqo"
            fallback = Path(__file__).parent.parent / ".wiqo"
            target_dir = preferred
            try:
                preferred.mkdir(parents=True, exist_ok=True)
                probe = preferred / ".write_test"
                probe.write_text("ok", encoding="utf-8")
                probe.unlink(missing_ok=True)
            except Exception:
                fallback.mkdir(parents=True, exist_ok=True)
                target_dir = fallback
            state_path = target_dir / "pipeline_state.json"
        self.state_path = state_path
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self._state = {"active": {}, "history": []}
        self._load()

    def _load(self):
        try:
            if self.state_path.exists():
                self._state = json.loads(self.state_path.read_text(encoding="utf-8"))
                if not isinstance(self._state, dict):
                    self._state = {"active": {}, "history": []}
        except Exception as exc:
            logger.debug(f"pipeline_state load failed: {exc}")
            self._state = {"active": {}, "history": []}

    def _save(self):
        try:
            self.state_path.write_text(json.dumps(self._state, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.debug(f"pipeline_state save failed: {exc}")

    def start(self, user_id: str, user_input: str, domain: str, tasks: list[dict[str, Any]]) -> str:
        pipeline_id = f"pl_{uuid.uuid4().hex[:12]}"
        now = time.time()
        self._state["active"][pipeline_id] = {
            "pipeline_id": pipeline_id,
            "user_id": str(user_id or "unknown"),
            "domain": str(domain or "general"),
            "user_input": str(user_input or ""),
            "status": "running",
            "created_at": now,
            "updated_at": now,
            "tasks": tasks,
            "progress": {"completed": 0, "failed": 0, "total": len(tasks)},
            "last_error": "",
        }
        self._save()
        return pipeline_id

    def mark_task(self, pipeline_id: str, task_id: str, success: bool, error: str = ""):
        p = self._state.get("active", {}).get(pipeline_id)
        if not p:
            return
        tasks = p.get("tasks", [])
        for t in tasks:
            if str(t.get("id")) == str(task_id):
                t["status"] = "done" if success else "failed"
                t["error"] = str(error or "")
                break
        progress = p.get("progress", {})
        if success:
            progress["completed"] = int(progress.get("completed", 0)) + 1
        else:
            progress["failed"] = int(progress.get("failed", 0)) + 1
            p["last_error"] = str(error or "")
        p["updated_at"] = time.time()
        self._save()

    def complete(self, pipeline_id: str, success: bool, summary: str = ""):
        active = self._state.get("active", {})
        p = active.pop(pipeline_id, None)
        if not p:
            return
        p["status"] = "completed" if success else "failed"
        p["completed_at"] = time.time()
        p["summary"] = str(summary or "")
        history = self._state.setdefault("history", [])
        history.append(p)
        self._state["history"] = history[-100:]
        self._save()

    def list_resume_candidates(self, user_id: str | None = None) -> list[dict[str, Any]]:
        candidates = []
        for p in self._state.get("active", {}).values():
            if user_id and str(p.get("user_id")) != str(user_id):
                continue
            candidates.append(
                {
                    "pipeline_id": p.get("pipeline_id"),
                    "domain": p.get("domain"),
                    "user_input": p.get("user_input"),
                    "progress": p.get("progress", {}),
                    "updated_at": p.get("updated_at"),
                }
            )
        return candidates


_pipeline_state: PipelineStateManager | None = None


def get_pipeline_state() -> PipelineStateManager:
    global _pipeline_state
    if _pipeline_state is None:
        _pipeline_state = PipelineStateManager()
    return _pipeline_state
