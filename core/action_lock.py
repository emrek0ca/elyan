from __future__ import annotations

import time
import asyncio
from collections import deque
from typing import Any, Optional

from core.event_system import Event, EventPriority, get_event_bus
from utils.logger import get_logger

logger = get_logger("action_lock")


class ActionLockManager:
    """Conflict-aware action lock with event history and queued handoff."""

    _STALE_AFTER_SECONDS = 15 * 60

    def __init__(self):
        self.is_locked = False
        self.current_task_id: Optional[str] = None
        self.locked_at: Optional[float] = None
        self.progress: float = 0.0
        self.status_message: str = ""
        self.policy_scope: str = "global"
        self.conflict_key: str = ""
        self.owner: str = "system"
        self.last_conflict: dict[str, Any] = {}
        self.queued_requests: deque[dict[str, Any]] = deque(maxlen=16)
        self.history: deque[dict[str, Any]] = deque(maxlen=64)

    def _emit(self, event_type: str, payload: dict[str, Any], *, priority: EventPriority = EventPriority.NORMAL) -> None:
        try:
            payload = dict(payload or {})
            correlation_id = str(
                payload.get("task_id")
                or self.current_task_id
                or payload.get("policy_scope")
                or event_type
            )
            causation_id = str(payload.get("causation_id") or correlation_id)
            idempotency_key = str(payload.get("idempotency_key") or f"{event_type}:{correlation_id}")
            bus = get_event_bus()
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop and not loop.is_closed():
                loop.create_task(
                    bus.publish(
                        event_type=event_type,
                        data=payload,
                        priority=priority,
                        source="action_lock",
                        tags={"action_lock"},
                        metadata={"action_lock": True},
                        schema_version=1,
                        correlation_id=correlation_id,
                        causation_id=causation_id,
                        idempotency_key=idempotency_key,
                    )
                )
            else:
                event = Event(
                    event_id=f"action_lock_{int(time.time() * 1000)}",
                    event_type=event_type,
                    data=payload,
                    priority=priority,
                    source="action_lock",
                    tags={"action_lock"},
                    metadata={"action_lock": True},
                    schema_version=1,
                    correlation_id=correlation_id,
                    causation_id=causation_id,
                    idempotency_key=idempotency_key,
                )
                bus.event_history.append(event)
                bus.event_stats[event_type] += 1
        except Exception:
            pass

    def _record_history(self, event_type: str, payload: dict[str, Any]) -> None:
        self.history.append({"event_type": event_type, "timestamp": time.time(), **dict(payload)})

    def _is_stale(self) -> bool:
        return bool(self.is_locked and self.locked_at and (time.time() - float(self.locked_at or 0.0) >= self._STALE_AFTER_SECONDS))

    def snapshot(self) -> dict[str, Any]:
        return {
            "is_locked": self.is_locked,
            "current_task_id": self.current_task_id,
            "locked_at": self.locked_at,
            "progress": self.progress,
            "status_message": self.status_message,
            "policy_scope": self.policy_scope,
            "conflict_key": self.conflict_key,
            "owner": self.owner,
            "queue_depth": len(self.queued_requests),
            "last_conflict": dict(self.last_conflict),
            "history": list(self.history)[-8:],
        }

    def request_lock(
        self,
        task_id: str,
        message: str = "Başlatıldı",
        *,
        policy_scope: str = "global",
        conflict_key: str = "",
        owner: str = "system",
        allow_queue: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = time.time()
        request = {
            "task_id": str(task_id),
            "policy_scope": str(policy_scope or "global"),
            "conflict_key": str(conflict_key or task_id),
            "owner": str(owner or "system"),
            "message": str(message or "Başlatıldı"),
            "metadata": dict(metadata or {}),
            "requested_at": now,
        }

        if self.is_locked and self.current_task_id == request["task_id"]:
            self.status_message = request["message"]
            self.policy_scope = request["policy_scope"]
            self.conflict_key = request["conflict_key"]
            self.owner = request["owner"]
            self._record_history("action_lock.refreshed", request)
            self._emit("action_lock.refreshed", request)
            return {"acquired": True, "queued": False, "conflict": False, "task_id": request["task_id"]}

        if self.is_locked:
            conflict = {
                **request,
                "active_task_id": self.current_task_id,
                "active_policy_scope": self.policy_scope,
                "active_conflict_key": self.conflict_key,
                "active_owner": self.owner,
                "stale": self._is_stale(),
            }
            self.last_conflict = conflict
            self._record_history("action_lock.conflict", conflict)
            self._emit("action_lock.conflict", conflict, priority=EventPriority.HIGH)
            if self._is_stale():
                self.unlock(reason="stale_lock_auto_released")
            elif allow_queue:
                self.queued_requests.append(request)
                return {"acquired": False, "queued": True, "conflict": True, "reason": "active_lock", "task_id": request["task_id"]}
            return {"acquired": False, "queued": False, "conflict": True, "reason": "active_lock", "task_id": request["task_id"]}

        self.is_locked = True
        self.current_task_id = request["task_id"]
        self.locked_at = now
        self.status_message = request["message"]
        self.progress = 0.0
        self.policy_scope = request["policy_scope"]
        self.conflict_key = request["conflict_key"]
        self.owner = request["owner"]
        self._record_history("action_lock.acquired", request)
        self._emit("action_lock.acquired", request, priority=EventPriority.HIGH)
        logger.info(f"Action-Lock ENABLED for task: {task_id} scope={self.policy_scope}")
        return {"acquired": True, "queued": False, "conflict": False, "task_id": request["task_id"]}

    def lock(
        self,
        task_id: str,
        message: str = "Başlatıldı",
        *,
        policy_scope: str = "global",
        conflict_key: str = "",
        owner: str = "system",
    ):
        return self.request_lock(
            task_id,
            message,
            policy_scope=policy_scope,
            conflict_key=conflict_key,
            owner=owner,
        )

    def unlock(self, *, reason: str = "completed"):
        payload = {
            "task_id": self.current_task_id,
            "policy_scope": self.policy_scope,
            "conflict_key": self.conflict_key,
            "owner": self.owner,
            "reason": str(reason or "completed"),
            "queue_depth": len(self.queued_requests),
        }
        logger.info(f"Action-Lock DISABLED (Completed task: {self.current_task_id}) reason={reason}")
        self._record_history("action_lock.released", payload)
        self._emit("action_lock.released", payload)

        self.is_locked = False
        self.current_task_id = None
        self.locked_at = None
        self.progress = 0.0
        self.status_message = ""
        self.policy_scope = "global"
        self.conflict_key = ""
        self.owner = "system"

        if self.queued_requests:
            next_request = self.queued_requests.popleft()
            self.request_lock(
                next_request["task_id"],
                str(next_request.get("message") or "Başlatıldı"),
                policy_scope=str(next_request.get("policy_scope") or "global"),
                conflict_key=str(next_request.get("conflict_key") or next_request["task_id"]),
                owner=str(next_request.get("owner") or "system"),
                allow_queue=True,
                metadata=next_request.get("metadata") if isinstance(next_request.get("metadata"), dict) else {},
            )

    def update_status(self, progress: Optional[float], message: str):
        if progress is not None:
            self.progress = progress
        self.status_message = message
        self._record_history(
            "action_lock.progress",
            {"task_id": self.current_task_id, "progress": self.progress, "message": self.status_message},
        )

    def get_status_prefix(self) -> str:
        if self.is_locked:
            pct = int(self.progress * 100)
            return f"[URETIM %{pct}] "
        return ""


action_lock = ActionLockManager()
