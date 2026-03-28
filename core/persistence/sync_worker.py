from __future__ import annotations

import asyncio
from typing import Any

from core.observability.logger import get_structured_logger

from .runtime_db import RuntimeDatabase, get_runtime_database

slog = get_structured_logger("runtime_sync_worker")


async def sync_runtime_outbox_once(*, runtime_db: RuntimeDatabase | None = None, limit: int = 100) -> int:
    db = runtime_db or get_runtime_database()
    outbox = getattr(db, "outbox", None)
    workspace_sync = getattr(db, "workspace_sync", None)
    if outbox is None or workspace_sync is None or not getattr(workspace_sync, "enabled", False):
        return 0

    delivered = 0
    try:
        pending = list(outbox.list_pending(limit=max(1, int(limit or 100))))
    except Exception as exc:
        slog.log_event("runtime_sync_list_pending_failed", {"error": str(exc)}, level="warning")
        return 0

    for event in pending:
        event_id = str(event.get("event_id") or "")
        if not event_id:
            continue
        try:
            accepted = workspace_sync.accept_outbox_event(dict(event or {}))
            if accepted:
                outbox.mark_delivered(event_id)
                delivered += 1
        except Exception as exc:
            try:
                outbox.mark_retry(event_id, error=str(exc))
            except Exception:
                pass
            attempts = int(event.get("delivery_attempts") or 0) + 1
            if attempts >= getattr(outbox, "_MAX_ATTEMPTS", 5):
                slog.log_event(
                    "runtime_sync_dead_lettered",
                    {
                        "event_id": event_id,
                        "aggregate_type": str(event.get("aggregate_type") or "unknown"),
                        "event_type": str(event.get("event_type") or "unknown"),
                        "attempts": attempts,
                        "error": str(exc),
                    },
                    level="warning",
                )
                continue
            slog.log_event(
                "runtime_sync_delivery_failed",
                {
                    "event_id": event_id,
                    "aggregate_type": str(event.get("aggregate_type") or "unknown"),
                    "event_type": str(event.get("event_type") or "unknown"),
                    "error": str(exc),
                },
                level="warning",
            )
    return delivered


class RuntimeSyncWorker:
    def __init__(self, *, interval_seconds: float = 1.5, batch_size: int = 100) -> None:
        self.interval_seconds = max(0.25, float(interval_seconds or 1.5))
        self.batch_size = max(1, int(batch_size or 100))
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        try:
            if not getattr(get_runtime_database().workspace_sync, "enabled", False):
                return
        except Exception:
            return
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(self._run_loop(), name="runtime-sync-worker")

    async def stop(self) -> None:
        self._stop_event.set()
        if not self._task:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        finally:
            self._task = None

    async def run_once(self) -> int:
        return await sync_runtime_outbox_once(limit=self.batch_size)

    async def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                slog.log_event("runtime_sync_loop_failed", {"error": str(exc)}, level="warning")
            await asyncio.sleep(self.interval_seconds)


__all__ = ["RuntimeSyncWorker", "sync_runtime_outbox_once"]
