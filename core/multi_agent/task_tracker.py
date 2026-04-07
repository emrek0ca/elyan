"""
core/multi_agent/task_tracker.py
───────────────────────────────────────────────────────────────────────────────
Agent Task Tracker — manages the task tree and lifecycle.

Responsibilities:
  - Register tasks and maintain parent-child relationships
  - Monitor deadlines and trigger timeout escalation
  - Emit lifecycle events to the message bus
  - Provide query APIs for task state inspection
  - Compute aggregate metrics (success rate, avg duration)

Data structure:
  Tasks are stored in a flat dict keyed by task_id.
  Parent-child relationships form a forest (multiple root tasks).
  Children are discovered via parent_task_id lookup — O(N) for tree
  queries but sufficient for typical task counts (< 1000 active).

Concurrency model:
  All mutations go through asyncio.Lock.
  Read-only queries (get, list, tree) are lock-free for performance.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from core.multi_agent.agent_task import AgentTask, TaskStatus
from core.multi_agent.message_bus import AgentMessage, get_message_bus
from core.observability.logger import get_structured_logger

slog = get_structured_logger("agent_task_tracker")


class AgentTaskTracker:
    """Singleton task lifecycle manager."""

    # Topic namespace for task lifecycle events
    TOPIC_PREFIX = "task.lifecycle"

    def __init__(self) -> None:
        self._tasks: dict[str, AgentTask] = {}
        self._lock = asyncio.Lock()
        self._deadline_task: asyncio.Task[None] | None = None

    # ── Registration ─────────────────────────────────────────────────────

    async def register(self, task: AgentTask) -> AgentTask:
        """Register a new task. Emits task.lifecycle.created event."""
        async with self._lock:
            self._tasks[task.task_id] = task
            self._ensure_deadline_monitor()
        await self._emit("created", task)
        slog.log_event("task_registered", {
            "task_id": task.task_id,
            "assigned_to": task.assigned_to,
            "objective": task.objective[:80],
            "parent": task.parent_task_id or "root",
        })
        return task

    # ── State transitions ────────────────────────────────────────────────

    async def start(self, task_id: str) -> AgentTask | None:
        """Transition task to RUNNING."""
        async with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return None
            task.start()
        await self._emit("started", task)
        return task

    async def complete(self, task_id: str, result: dict[str, Any] | None = None) -> AgentTask | None:
        """Transition task to COMPLETED with optional result."""
        async with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return None
            task.complete(result)
        await self._emit("completed", task)
        slog.log_event("task_completed", {
            "task_id": task_id,
            "duration_s": f"{task.duration_s:.2f}" if task.duration_s else "n/a",
        })
        return task

    async def fail(self, task_id: str, error: str, *, allow_retry: bool = True) -> AgentTask | None:
        """Transition task to FAILED."""
        async with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return None
            task.fail(error, allow_retry=allow_retry)
        await self._emit("failed", task)
        slog.log_event("task_failed", {"task_id": task_id, "error": error[:120]}, level="warning")
        return task

    async def cancel(self, task_id: str) -> AgentTask | None:
        """Cancel a task and all its children (cascade)."""
        cancelled: list[AgentTask] = []
        async with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return None
            # Cascade cancel to children
            to_cancel = [task_id]
            while to_cancel:
                tid = to_cancel.pop()
                t = self._tasks.get(tid)
                if t is None or t.status.is_terminal:
                    continue
                t.cancel()
                cancelled.append(t)
                # Find children
                for child in self._tasks.values():
                    if child.parent_task_id == tid and not child.status.is_terminal:
                        to_cancel.append(child.task_id)
        for t in cancelled:
            await self._emit("cancelled", t)
        return task

    async def retry(self, task_id: str) -> AgentTask | None:
        """Retry a failed task."""
        async with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return None
            task.retry()
        await self._emit("retrying", task)
        return task

    # ── Query ────────────────────────────────────────────────────────────

    def get(self, task_id: str) -> AgentTask | None:
        return self._tasks.get(task_id)

    def list_active(self) -> list[AgentTask]:
        """All non-terminal tasks, sorted by priority (descending)."""
        return sorted(
            (t for t in self._tasks.values() if not t.status.is_terminal),
            key=lambda t: t.priority,
            reverse=True,
        )

    def list_by_agent(self, agent_id: str) -> list[AgentTask]:
        """All tasks assigned to a specific agent."""
        return [t for t in self._tasks.values() if t.assigned_to == agent_id]

    def children(self, task_id: str) -> list[AgentTask]:
        """Direct children of a task."""
        return [t for t in self._tasks.values() if t.parent_task_id == task_id]

    def task_tree(self, root_task_id: str) -> dict[str, Any]:
        """Build a nested tree structure from a root task.

        Returns:
            {"task": AgentTask.to_dict(), "children": [subtree, ...]}
        """
        root = self._tasks.get(root_task_id)
        if root is None:
            return {}
        return self._build_subtree(root)

    def _build_subtree(self, task: AgentTask) -> dict[str, Any]:
        kids = self.children(task.task_id)
        return {
            "task": task.to_dict(),
            "children": [self._build_subtree(c) for c in kids],
        }

    # ── Metrics ──────────────────────────────────────────────────────────

    def metrics(self) -> dict[str, Any]:
        """Aggregate task metrics."""
        total = len(self._tasks)
        if total == 0:
            return {"total": 0}

        by_status: dict[str, int] = {}
        durations: list[float] = []
        success_count = 0
        terminal_count = 0

        for t in self._tasks.values():
            by_status[t.status.value] = by_status.get(t.status.value, 0) + 1
            if t.status.is_terminal:
                terminal_count += 1
                if t.status == TaskStatus.COMPLETED:
                    success_count += 1
                if t.duration_s is not None:
                    durations.append(t.duration_s)

        avg_duration = sum(durations) / len(durations) if durations else 0.0
        success_rate = success_count / terminal_count if terminal_count > 0 else 0.0

        return {
            "total": total,
            "by_status": by_status,
            "success_rate": round(success_rate, 3),
            "avg_duration_s": round(avg_duration, 2),
            "active": total - terminal_count,
            "overdue": sum(1 for t in self._tasks.values() if t.is_overdue),
        }

    # ── Deadline monitor ─────────────────────────────────────────────────

    def _ensure_deadline_monitor(self) -> None:
        if self._deadline_task is None or self._deadline_task.done():
            self._deadline_task = asyncio.ensure_future(self._deadline_loop())

    async def _deadline_loop(self) -> None:
        """Check for overdue tasks every 5 seconds."""
        while True:
            await asyncio.sleep(5.0)
            overdue: list[AgentTask] = []
            for t in self._tasks.values():
                if t.is_overdue:
                    overdue.append(t)
            for t in overdue:
                await self._emit("overdue", t)
                slog.log_event(
                    "task_overdue",
                    {
                        "task_id": t.task_id,
                        "deadline_s": t.deadline_s,
                        "elapsed_s": f"{t.duration_s:.1f}" if t.duration_s else "?",
                    },
                    level="warning",
                )
            # Stop loop if no active tasks
            if not any(not t.status.is_terminal for t in self._tasks.values()):
                break

    # ── Event emission ───────────────────────────────────────────────────

    async def _emit(self, event_type: str, task: AgentTask) -> None:
        """Publish lifecycle event to the message bus."""
        try:
            bus = get_message_bus()
            await bus.publish(
                AgentMessage(
                    topic=f"{self.TOPIC_PREFIX}.{event_type}",
                    from_agent="task_tracker",
                    payload=task.to_dict(),
                    correlation_id=task.parent_task_id or task.task_id,
                )
            )
        except Exception:
            pass  # Bus not available — degrade gracefully

    # ── Cleanup ──────────────────────────────────────────────────────────

    async def prune_completed(self, max_age_s: float = 3600) -> int:
        """Remove terminal tasks older than max_age_s. Returns count removed."""
        cutoff = time.time() - max_age_s
        async with self._lock:
            to_remove = [
                tid for tid, t in self._tasks.items()
                if t.status.is_terminal and (t.completed_at or 0) < cutoff
            ]
            for tid in to_remove:
                del self._tasks[tid]
        return len(to_remove)


# ── Singleton ───────────────────────────────────────────────────────────────

_tracker_instance: AgentTaskTracker | None = None


def get_task_tracker() -> AgentTaskTracker:
    """Get or create the singleton AgentTaskTracker."""
    global _tracker_instance
    if _tracker_instance is None:
        _tracker_instance = AgentTaskTracker()
    return _tracker_instance


__all__ = ["AgentTaskTracker", "get_task_tracker"]
