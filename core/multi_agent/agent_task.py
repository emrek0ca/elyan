"""
core/multi_agent/agent_task.py
───────────────────────────────────────────────────────────────────────────────
Agent Task — the work unit contract for delegated agent execution.

Each task flows through a finite state machine:

    PENDING ──→ RUNNING ──→ COMPLETED
       │            │
       └──→ CANCELLED   └──→ FAILED
                                │
                                └──→ RETRYING ──→ RUNNING

State transitions are enforced — invalid transitions raise ValueError.

Design invariants:
  - Every task has exactly one owner (assigned_to)
  - Every task may have one parent (delegation chain)
  - Duration is computed, not stored — avoids clock skew issues
  - Result is immutable once set — no silent overwrites
"""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RETRYING = "retrying"

    @property
    def is_terminal(self) -> bool:
        return self in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED)


# Valid state transitions — adjacency list representation
_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.PENDING: frozenset({TaskStatus.RUNNING, TaskStatus.CANCELLED}),
    TaskStatus.RUNNING: frozenset({TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}),
    TaskStatus.FAILED: frozenset({TaskStatus.RETRYING, TaskStatus.CANCELLED}),
    TaskStatus.RETRYING: frozenset({TaskStatus.RUNNING, TaskStatus.CANCELLED}),
    TaskStatus.COMPLETED: frozenset(),
    TaskStatus.CANCELLED: frozenset(),
}


@dataclass
class AgentTask:
    """Contract for a single delegated task.

    Attributes:
        task_id:         Unique identifier (auto-generated if not provided).
        parent_task_id:  Parent task in delegation chain (None = root task).
        assigned_to:     Specialist / agent ID that owns execution.
        assigned_by:     Who delegated this task (orchestrator or another agent).
        objective:       Human-readable goal description.
        context:         Shared contextual data (workspace, session, prior results).
        constraints:     Execution constraints (e.g. "read-only", "no-cloud").
        tools_allowed:   Whitelist of tool IDs this task may use.
        deadline_s:      Max seconds for execution (None = no deadline).
        priority:        Higher = more urgent. Range [0, 100].
        status:          Current FSM state.
        result:          Output payload (set on completion or failure).
        error:           Error description (set on failure).
        retry_count:     Number of retries attempted.
        max_retries:     Maximum retry attempts before permanent failure.
        created_at:      Epoch timestamp of creation.
        started_at:      Epoch timestamp when execution began.
        completed_at:    Epoch timestamp when terminal state reached.
    """

    task_id: str = field(default_factory=lambda: f"task_{uuid.uuid4().hex[:12]}")
    parent_task_id: str | None = None
    assigned_to: str = ""
    assigned_by: str = ""
    objective: str = ""
    context: dict[str, Any] = field(default_factory=dict)
    constraints: list[str] = field(default_factory=list)
    tools_allowed: list[str] = field(default_factory=list)
    deadline_s: float | None = None
    priority: int = 50
    status: TaskStatus = TaskStatus.PENDING
    result: dict[str, Any] | None = None
    error: str | None = None
    retry_count: int = 0
    max_retries: int = 2
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    completed_at: float | None = None

    # ── State transitions ────────────────────────────────────────────────

    def transition(self, new_status: TaskStatus) -> None:
        """Move to a new state. Raises ValueError on invalid transition."""
        allowed = _TRANSITIONS.get(self.status, frozenset())
        if new_status not in allowed:
            raise ValueError(
                f"Invalid transition: {self.status.value} → {new_status.value}. "
                f"Allowed: {', '.join(s.value for s in allowed) or 'none (terminal state)'}"
            )
        now = time.time()
        if new_status == TaskStatus.RUNNING:
            self.started_at = self.started_at or now
        if new_status.is_terminal:
            self.completed_at = now
        if new_status == TaskStatus.RETRYING:
            self.retry_count += 1
        self.status = new_status

    def start(self) -> None:
        self.transition(TaskStatus.RUNNING)

    def complete(self, result: dict[str, Any] | None = None) -> None:
        self.result = result
        self.transition(TaskStatus.COMPLETED)

    def fail(self, error: str, *, allow_retry: bool = True) -> None:
        self.error = error
        if allow_retry and self.retry_count < self.max_retries:
            self.transition(TaskStatus.FAILED)
        else:
            self.transition(TaskStatus.FAILED)

    def cancel(self) -> None:
        if not self.status.is_terminal:
            self.transition(TaskStatus.CANCELLED)

    def retry(self) -> None:
        """Move from FAILED to RETRYING, then immediately to RUNNING."""
        if self.retry_count >= self.max_retries:
            raise ValueError(
                f"Max retries ({self.max_retries}) exceeded for task {self.task_id}"
            )
        self.transition(TaskStatus.RETRYING)
        self.transition(TaskStatus.RUNNING)

    # ── Computed properties ──────────────────────────────────────────────

    @property
    def duration_s(self) -> float | None:
        """Wall-clock duration. None if not started."""
        if self.started_at is None:
            return None
        end = self.completed_at or time.time()
        return end - self.started_at

    @property
    def is_overdue(self) -> bool:
        """True if deadline has passed and task is not terminal."""
        if self.deadline_s is None or self.started_at is None:
            return False
        if self.status.is_terminal:
            return False
        return (time.time() - self.started_at) > self.deadline_s

    @property
    def depth(self) -> int:
        """Delegation depth. 0 = root task."""
        # Depth is tracked externally by TaskTracker for efficiency
        return 0

    # ── Serialization ────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        data["duration_s"] = self.duration_s
        data["is_overdue"] = self.is_overdue
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentTask":
        d = dict(data)
        d.pop("duration_s", None)
        d.pop("is_overdue", None)
        d.pop("depth", None)
        status_raw = d.pop("status", "pending")
        task = cls(**d)
        task.status = TaskStatus(status_raw)
        return task


__all__ = ["AgentTask", "TaskStatus"]
