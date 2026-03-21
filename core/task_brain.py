from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

from config.settings import ELYAN_DIR
from core.storage_paths import resolve_elyan_data_dir
from core.learning_digest import build_task_learning_snapshot


_VALID_STATES = {
    "pending",
    "planning",
    "executing",
    "verifying",
    "completed",
    "failed",
    "partial",
}


@dataclass
class TaskEvent:
    state: str
    ts: float
    note: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        payload = {
            "state": self.state,
            "ts": self.ts,
        }
        if self.note:
            payload["note"] = self.note
        if self.metadata:
            payload["metadata"] = dict(self.metadata)
        return payload


@dataclass
class TaskRecord:
    task_id: str
    objective: str
    context: Dict[str, Any] = field(default_factory=dict)
    subtasks: List[Dict[str, Any]] = field(default_factory=list)
    artifacts: List[Dict[str, Any]] = field(default_factory=list)
    learning: Dict[str, Any] = field(default_factory=dict)
    state: str = "pending"
    history: List[TaskEvent] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def transition(self, state: str, *, note: str = "", metadata: Dict[str, Any] | None = None) -> None:
        next_state = str(state or "").strip().lower()
        if next_state not in _VALID_STATES:
            next_state = "pending"
        now = time.time()
        self.state = next_state
        self.updated_at = now
        self.history.append(TaskEvent(state=next_state, ts=now, note=str(note or ""), metadata=dict(metadata or {})))
        self.learning = build_task_learning_snapshot(self)

    def register_artifacts(self, artifacts: List[Dict[str, Any]] | None) -> None:
        seen = {str(item.get("path") or "").strip() for item in self.artifacts if isinstance(item, dict)}
        for artifact in list(artifacts or []):
            if not isinstance(artifact, dict):
                continue
            path = str(artifact.get("path") or "").strip()
            if path and path not in seen:
                self.artifacts.append(dict(artifact))
                seen.add(path)
        self.updated_at = time.time()
        self.learning = build_task_learning_snapshot(self)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "objective": self.objective,
            "context": dict(self.context),
            "subtasks": list(self.subtasks),
            "artifacts": list(self.artifacts),
            "learning": dict(self.learning),
            "state": self.state,
            "history": [event.to_dict() for event in self.history],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class TaskBrain:
    def __init__(self, storage_path: Path | None = None):
        candidate = Path(storage_path or (ELYAN_DIR / "task_brain.json")).expanduser()
        try:
            candidate.parent.mkdir(parents=True, exist_ok=True)
            probe = candidate.parent / ".task_brain_write_test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            self.storage_path = candidate
        except Exception:
            self.storage_path = (resolve_elyan_data_dir() / "task_brain.json").expanduser()
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self._tasks: Dict[str, TaskRecord] = self._load()

    def _load(self) -> Dict[str, TaskRecord]:
        if not self.storage_path.exists():
            return {}
        try:
            payload = json.loads(self.storage_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        if not isinstance(payload, dict):
            return {}
        loaded: Dict[str, TaskRecord] = {}
        for task_id, row in payload.items():
            if not isinstance(row, dict):
                continue
            try:
                record = TaskRecord(
                    task_id=str(row.get("task_id") or task_id),
                    objective=str(row.get("objective") or ""),
                    context=dict(row.get("context") or {}),
                    subtasks=list(row.get("subtasks") or []),
                    artifacts=list(row.get("artifacts") or []),
                    learning=dict(row.get("learning") or {}),
                    state=str(row.get("state") or "pending"),
                    history=[
                        TaskEvent(
                            state=str(event.get("state") or "pending"),
                            ts=float(event.get("ts") or time.time()),
                            note=str(event.get("note") or ""),
                            metadata=dict(event.get("metadata") or {}),
                        )
                        for event in list(row.get("history") or [])
                        if isinstance(event, dict)
                    ],
                    created_at=float(row.get("created_at") or time.time()),
                    updated_at=float(row.get("updated_at") or time.time()),
                )
            except Exception:
                continue
            loaded[record.task_id] = record
        return loaded

    def _save(self) -> None:
        payload = {task_id: record.to_dict() for task_id, record in self._tasks.items()}
        try:
            self.storage_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            self.storage_path = (resolve_elyan_data_dir() / "task_brain.json").expanduser()
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            self.storage_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _refresh_learning(self, task: TaskRecord) -> None:
        task.learning = build_task_learning_snapshot(task)

    def create_task(
        self,
        *,
        objective: str,
        user_input: str,
        channel: str,
        user_id: str,
        attachments: List[str] | None = None,
        task_card: Dict[str, Any] | None = None,
    ) -> TaskRecord:
        task = TaskRecord(
            task_id=f"task_{uuid.uuid4().hex[:10]}",
            objective=str(objective or user_input or "").strip() or "Untitled task",
            context={
                "user_input": str(user_input or ""),
                "channel": str(channel or ""),
                "user_id": str(user_id or ""),
                "attachments": list(attachments or []),
                "task_card": dict(task_card or {}),
            },
        )
        task.transition("pending", note="task_created")
        self._refresh_learning(task)
        self._tasks[task.task_id] = task
        self._save()
        return task

    def save_task(self, task: TaskRecord) -> None:
        self._refresh_learning(task)
        self._tasks[str(task.task_id or "")] = task
        self._save()

    def get(self, task_id: str) -> TaskRecord | None:
        return self._tasks.get(str(task_id or ""))

    def list_all(
        self,
        *,
        limit: int | None = None,
        states: List[str] | None = None,
    ) -> List[TaskRecord]:
        wanted = {str(item).strip().lower() for item in (states or []) if str(item).strip()}
        items = [
            record
            for record in self._tasks.values()
            if not wanted or str(record.state or "").strip().lower() in wanted
        ]
        items.sort(key=lambda item: item.updated_at, reverse=True)
        if limit is None:
            return items
        return items[: max(1, int(limit or 1))]

    def list_for_user(
        self,
        user_id: str,
        *,
        limit: int = 10,
        states: List[str] | None = None,
    ) -> List[TaskRecord]:
        wanted = {str(item).strip().lower() for item in (states or []) if str(item).strip()}
        items = [
            record
            for record in self._tasks.values()
            if str(record.context.get("user_id") or "") == str(user_id or "")
            and (not wanted or str(record.state or "").strip().lower() in wanted)
        ]
        items.sort(key=lambda item: item.updated_at, reverse=True)
        return items[: max(1, int(limit or 10))]

    def latest_for_user(
        self,
        user_id: str,
        *,
        states: List[str] | None = None,
    ) -> TaskRecord | None:
        items = self.list_for_user(user_id, limit=1, states=states)
        return items[0] if items else None


task_brain = TaskBrain()


__all__ = ["TaskBrain", "TaskRecord", "task_brain"]
