from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

from config.settings import ELYAN_DIR
from utils.logger import get_logger

logger = get_logger("away_mode")


@dataclass
class AwayTaskRecord:
    task_id: str
    user_input: str
    user_id: str
    channel: str
    mode: str = "background"
    capability_domain: str = "general"
    workflow_id: str = ""
    state: str = "queued"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    run_id: str = ""
    result_summary: str = ""
    error: str = ""
    retry_count: int = 0
    max_retries: int = 0
    next_retry_at: float = 0.0
    attachments: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "user_input": self.user_input,
            "user_id": self.user_id,
            "channel": self.channel,
            "mode": self.mode,
            "capability_domain": self.capability_domain,
            "workflow_id": self.workflow_id,
            "state": self.state,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "run_id": self.run_id,
            "result_summary": self.result_summary,
            "error": self.error,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "next_retry_at": self.next_retry_at,
            "attachments": list(self.attachments),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "AwayTaskRecord":
        return cls(
            task_id=str(payload.get("task_id") or ""),
            user_input=str(payload.get("user_input") or ""),
            user_id=str(payload.get("user_id") or ""),
            channel=str(payload.get("channel") or ""),
            mode=str(payload.get("mode") or "background"),
            capability_domain=str(payload.get("capability_domain") or "general"),
            workflow_id=str(payload.get("workflow_id") or ""),
            state=str(payload.get("state") or "queued"),
            created_at=float(payload.get("created_at") or time.time()),
            updated_at=float(payload.get("updated_at") or time.time()),
            run_id=str(payload.get("run_id") or ""),
            result_summary=str(payload.get("result_summary") or ""),
            error=str(payload.get("error") or ""),
            retry_count=int(payload.get("retry_count") or 0),
            max_retries=int(payload.get("max_retries") or 0),
            next_retry_at=float(payload.get("next_retry_at") or 0.0),
            attachments=list(payload.get("attachments") or []),
            metadata=dict(payload.get("metadata") or {}),
        )


class AwayTaskRegistry:
    def __init__(self, storage_path: Optional[Path] = None):
        self.storage_path = Path(storage_path or (ELYAN_DIR / "away_tasks.json")).expanduser()
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self._tasks: Dict[str, AwayTaskRecord] = self._load()

    def _load(self) -> Dict[str, AwayTaskRecord]:
        if not self.storage_path.exists():
            return {}
        try:
            payload = json.loads(self.storage_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning(f"Away task registry load failed: {exc}")
            return {}
        if not isinstance(payload, dict):
            return {}
        loaded: Dict[str, AwayTaskRecord] = {}
        for task_id, row in payload.items():
            if not isinstance(row, dict):
                continue
            record = AwayTaskRecord.from_dict({"task_id": task_id, **row})
            loaded[record.task_id] = record
        return loaded

    def _save(self) -> None:
        payload = {task_id: record.to_dict() for task_id, record in self._tasks.items()}
        self.storage_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def create(
        self,
        *,
        user_input: str,
        user_id: str,
        channel: str,
        capability_domain: str = "general",
        workflow_id: str = "",
        mode: str = "background",
        metadata: Dict[str, Any] | None = None,
    ) -> AwayTaskRecord:
        record = AwayTaskRecord(
            task_id=f"away_{uuid.uuid4().hex[:10]}",
            user_input=str(user_input or ""),
            user_id=str(user_id or ""),
            channel=str(channel or ""),
            capability_domain=str(capability_domain or "general"),
            workflow_id=str(workflow_id or ""),
            mode=str(mode or "background"),
            max_retries=max(0, int((metadata or {}).get("max_retries", 0) or 0)),
            metadata=dict(metadata or {}),
        )
        self._tasks[record.task_id] = record
        self._save()
        return record

    def get(self, task_id: str) -> Optional[AwayTaskRecord]:
        return self._tasks.get(str(task_id or ""))

    def update(self, task_id: str, **fields: Any) -> Optional[AwayTaskRecord]:
        record = self.get(task_id)
        if record is None:
            return None
        for key, value in fields.items():
            if hasattr(record, key):
                setattr(record, key, value)
        record.updated_at = time.time()
        self._save()
        return record

    def list_resume_candidates(self) -> List[AwayTaskRecord]:
        now = time.time()
        candidates = [
            record
            for record in self._tasks.values()
            if record.state in {"queued", "running"}
            or (
                record.state in {"failed", "partial"}
                and bool(record.metadata.get("auto_retry"))
                and (
                    (record.state == "partial" and bool(record.metadata.get("retry_on_partial", True)))
                    or (record.state == "failed" and bool(record.metadata.get("retry_on_failure", True)))
                )
                and int(record.retry_count) < int(record.max_retries)
                and float(record.next_retry_at or 0.0) <= now
            )
        ]
        candidates.sort(key=lambda item: item.updated_at, reverse=True)
        return candidates

    def list_all(self) -> List[AwayTaskRecord]:
        items = list(self._tasks.values())
        items.sort(key=lambda item: item.updated_at, reverse=True)
        return items

    def list_for_user(
        self,
        user_id: str,
        *,
        limit: int = 10,
        states: List[str] | None = None,
    ) -> List[AwayTaskRecord]:
        wanted = {str(item).strip().lower() for item in (states or []) if str(item).strip()}
        items = [
            record
            for record in self._tasks.values()
            if str(record.user_id or "") == str(user_id or "")
            and (not wanted or str(record.state or "").strip().lower() in wanted)
        ]
        items.sort(key=lambda item: item.updated_at, reverse=True)
        return items[: max(1, int(limit or 10))]

    def latest_for_user(
        self,
        user_id: str,
        *,
        states: List[str] | None = None,
    ) -> Optional[AwayTaskRecord]:
        items = self.list_for_user(user_id, limit=1, states=states)
        return items[0] if items else None

    def cancel(self, task_id: str) -> Optional[AwayTaskRecord]:
        record = self.get(task_id)
        if record is None:
            return None
        if record.state in {"completed", "failed", "cancelled"}:
            return record
        return self.update(task_id, state="cancelled")

    def requeue(self, task_id: str) -> Optional[AwayTaskRecord]:
        record = self.get(task_id)
        if record is None:
            return None
        return self.update(
            task_id,
            state="queued",
            error="",
            result_summary="",
            run_id="",
            next_retry_at=0.0,
            attachments=[],
        )


class CompletionNotifier:
    def __init__(self):
        self._callbacks: List[Callable[[AwayTaskRecord], Awaitable[None] | None]] = []

    def register(self, callback: Callable[[AwayTaskRecord], Awaitable[None] | None]) -> None:
        self._callbacks.append(callback)

    async def notify(self, record: AwayTaskRecord) -> None:
        for callback in list(self._callbacks):
            try:
                result = callback(record)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:
                logger.warning(f"Completion callback failed for {record.task_id}: {exc}")


class BackgroundTaskRunner:
    def __init__(
        self,
        registry: Optional[AwayTaskRegistry] = None,
        notifier: Optional[CompletionNotifier] = None,
    ):
        self.registry = registry or AwayTaskRegistry()
        self.notifier = notifier or CompletionNotifier()
        self._running: Dict[str, asyncio.Task] = {}
        self._resume_handler: Optional[Callable[[AwayTaskRecord], Awaitable[Dict[str, Any]]]] = None
        self._resume_loop_task: Optional[asyncio.Task] = None
        self._resume_interval_s: float = 30.0

    @staticmethod
    def _retry_delay_seconds(record: AwayTaskRecord) -> float:
        retry_count = max(0, int(getattr(record, "retry_count", 0) or 0))
        return min(300.0, 15.0 * (2 ** retry_count))

    async def submit(
        self,
        *,
        user_input: str,
        user_id: str,
        channel: str,
        capability_domain: str,
        workflow_id: str,
        handler: Callable[[AwayTaskRecord], Awaitable[Dict[str, Any]]],
        metadata: Dict[str, Any] | None = None,
    ) -> AwayTaskRecord:
        record = self.registry.create(
            user_input=user_input,
            user_id=user_id,
            channel=channel,
            capability_domain=capability_domain,
            workflow_id=workflow_id,
            metadata=metadata,
        )
        self._running[record.task_id] = asyncio.create_task(self._run_task(record.task_id, handler), name=f"away-task:{record.task_id}")
        return record

    def set_resume_handler(self, handler: Callable[[AwayTaskRecord], Awaitable[Dict[str, Any]]]) -> None:
        self._resume_handler = handler

    async def _run_task(
        self,
        task_id: str,
        handler: Callable[[AwayTaskRecord], Awaitable[Dict[str, Any]]],
    ) -> None:
        record = self.registry.update(task_id, state="running")
        if record is None:
            return
        try:
            result = await handler(record)
            status = str(result.get("status") or "completed").strip().lower()
            state = "completed" if status == "success" else ("partial" if status == "partial" else "failed")
            should_retry = (
                state in {"failed", "partial"}
                and bool(getattr(record, "metadata", {}).get("auto_retry"))
                and (
                    (state == "partial" and bool(getattr(record, "metadata", {}).get("retry_on_partial", True)))
                    or (state == "failed" and bool(getattr(record, "metadata", {}).get("retry_on_failure", True)))
                )
                and int(getattr(record, "retry_count", 0) or 0) < int(getattr(record, "max_retries", 0) or 0)
            )
            next_retry_at = time.time() + self._retry_delay_seconds(record) if should_retry else 0.0
            record = self.registry.update(
                task_id,
                state="queued" if should_retry else state,
                run_id=str(result.get("run_id") or ""),
                result_summary=str(result.get("summary") or result.get("text") or ""),
                error=str(result.get("error") or ""),
                retry_count=(int(getattr(record, "retry_count", 0) or 0) + 1) if should_retry else int(getattr(record, "retry_count", 0) or 0),
                next_retry_at=next_retry_at,
                attachments=list(result.get("attachments") or []),
            )
            if record is not None and not should_retry:
                await self.notifier.notify(record)
        except Exception as exc:
            should_retry = (
                bool(getattr(record, "metadata", {}).get("auto_retry"))
                and bool(getattr(record, "metadata", {}).get("retry_on_failure", True))
                and int(getattr(record, "retry_count", 0) or 0) < int(getattr(record, "max_retries", 0) or 0)
            )
            next_retry_at = time.time() + self._retry_delay_seconds(record) if should_retry else 0.0
            record = self.registry.update(
                task_id,
                state="queued" if should_retry else "failed",
                error=str(exc),
                retry_count=(int(getattr(record, "retry_count", 0) or 0) + 1) if should_retry else int(getattr(record, "retry_count", 0) or 0),
                next_retry_at=next_retry_at,
            )
            if record is not None and not should_retry:
                await self.notifier.notify(record)
        finally:
            self._running.pop(task_id, None)

    async def resume_pending(
        self,
        handler: Callable[[AwayTaskRecord], Awaitable[Dict[str, Any]]] | None = None,
    ) -> List[str]:
        active_handler = handler or self._resume_handler
        if not callable(active_handler):
            return []
        resumed: List[str] = []
        for record in self.registry.list_resume_candidates():
            if record.task_id in self._running:
                continue
            self._running[record.task_id] = asyncio.create_task(self._run_task(record.task_id, active_handler), name=f"away-task:{record.task_id}")
            resumed.append(record.task_id)
        return resumed

    async def start_resume_loop(
        self,
        handler: Callable[[AwayTaskRecord], Awaitable[Dict[str, Any]]] | None = None,
        *,
        interval_s: float = 30.0,
    ) -> None:
        if callable(handler):
            self._resume_handler = handler
        if self._resume_loop_task and not self._resume_loop_task.done():
            return
        self._resume_interval_s = max(2.0, float(interval_s or 30.0))

        async def _loop() -> None:
            while True:
                try:
                    await self.resume_pending()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.warning(f"Away resume loop failed: {exc}")
                await asyncio.sleep(self._resume_interval_s)

        self._resume_loop_task = asyncio.create_task(_loop(), name="away-task-resume-loop")

    async def stop_resume_loop(self) -> None:
        task = self._resume_loop_task
        self._resume_loop_task = None
        if not task:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def cancel(self, task_id: str) -> Optional[AwayTaskRecord]:
        task = self._running.pop(str(task_id or ""), None)
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
        return self.registry.cancel(task_id)

    async def retry(self, task_id: str) -> Optional[AwayTaskRecord]:
        record = self.registry.requeue(task_id)
        if record is None:
            return None
        if record.task_id in self._running:
            return record
        if callable(self._resume_handler):
            self._running[record.task_id] = asyncio.create_task(
                self._run_task(record.task_id, self._resume_handler),
                name=f"away-task:{record.task_id}",
            )
        return record


away_task_registry = AwayTaskRegistry()
away_completion_notifier = CompletionNotifier()
background_task_runner = BackgroundTaskRunner(away_task_registry, away_completion_notifier)


__all__ = [
    "AwayTaskRecord",
    "AwayTaskRegistry",
    "CompletionNotifier",
    "BackgroundTaskRunner",
    "away_task_registry",
    "away_completion_notifier",
    "background_task_runner",
]
