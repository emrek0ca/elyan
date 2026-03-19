"""
core/task_state_machine.py
─────────────────────────────────────────────────────────────────────────────
PHASE 4: Task State Machine (~400 lines)
Track multi-task execution with state persistence and event logging.
─────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any, Set, Callable
from enum import Enum
import time
import json
from utils.logger import get_logger

logger = get_logger("task_state_machine")


class TaskState(Enum):
    """Task execution states."""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CLEANUP = "cleanup"
    RETRY = "retry"
    CANCELLED = "cancelled"


@dataclass
class StateTransition:
    """Record of state transition."""
    from_state: TaskState
    to_state: TaskState
    timestamp: float = field(default_factory=time.time)
    reason: Optional[str] = None
    context: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskCheckpoint:
    """Checkpoint in task execution."""
    checkpoint_id: str
    task_id: str
    timestamp: float
    data: Dict[str, Any]  # State snapshot


class TaskStateMachine:
    """Manage multi-task execution state."""

    def __init__(self, session_id: str, max_retries: int = 3):
        """Initialize state machine."""
        self.session_id = session_id
        self.max_retries = max_retries
        self.task_states: Dict[str, TaskState] = {}
        self.retry_counts: Dict[str, int] = {}
        self.state_transitions: List[StateTransition] = []
        self.checkpoints: List[TaskCheckpoint] = []
        self.event_log: List[Dict[str, Any]] = []
        self.state_callbacks: Dict[TaskState, List[Callable]] = {}
        self.resources: Dict[str, Any] = {}
        self.start_time = time.time()
        self.end_time: Optional[float] = None

    def register_task(self, task_id: str) -> None:
        """Register a task in the state machine."""
        self.task_states[task_id] = TaskState.PENDING
        self.retry_counts[task_id] = 0
        self._log_event("task_registered", {"task_id": task_id})

    def transition(self, task_id: str, new_state: TaskState, reason: Optional[str] = None) -> bool:
        """Transition task to new state."""
        if task_id not in self.task_states:
            logger.error(f"Task {task_id} not registered")
            return False

        old_state = self.task_states[task_id]

        # Validate transition
        if not self._is_valid_transition(old_state, new_state):
            logger.error(f"Invalid transition: {old_state.name} -> {new_state.name}")
            return False

        # Record transition
        transition = StateTransition(
            from_state=old_state,
            to_state=new_state,
            reason=reason,
        )
        self.state_transitions.append(transition)

        # Update state
        self.task_states[task_id] = new_state

        # Log event
        self._log_event("state_transition", {
            "task_id": task_id,
            "from_state": old_state.name,
            "to_state": new_state.name,
            "reason": reason,
        })

        # Trigger callbacks
        self._trigger_callbacks(new_state)

        logger.info(f"Task {task_id}: {old_state.name} -> {new_state.name}")

        return True

    def _is_valid_transition(self, from_state: TaskState, to_state: TaskState) -> bool:
        """Check if state transition is valid."""
        valid_transitions = {
            TaskState.PENDING: {TaskState.RUNNING, TaskState.CANCELLED},
            TaskState.RUNNING: {TaskState.SUCCESS, TaskState.FAILED, TaskState.CLEANUP, TaskState.RETRY},
            TaskState.FAILED: {TaskState.RETRY, TaskState.CLEANUP, TaskState.CANCELLED},
            TaskState.RETRY: {TaskState.RUNNING, TaskState.FAILED, TaskState.CLEANUP},
            TaskState.SUCCESS: {TaskState.CLEANUP},
            TaskState.CLEANUP: set(),
            TaskState.CANCELLED: {TaskState.CLEANUP},
        }

        return to_state in valid_transitions.get(from_state, set())

    def mark_failure(self, task_id: str) -> bool:
        """Mark task as failed and handle retry."""
        if task_id not in self.task_states:
            return False

        # Increment retry count
        self.retry_counts[task_id] = self.retry_counts.get(task_id, 0) + 1

        # Check retry limit
        if self.retry_counts[task_id] < self.max_retries:
            return self.transition(task_id, TaskState.RETRY, "Retrying after failure")
        else:
            return self.transition(task_id, TaskState.FAILED, "Max retries exceeded")

    def checkpoint(self, task_id: str, data: Dict[str, Any]) -> None:
        """Create checkpoint for task state recovery."""
        checkpoint = TaskCheckpoint(
            checkpoint_id=f"{task_id}_cp_{len(self.checkpoints)}",
            task_id=task_id,
            timestamp=time.time(),
            data=data,
        )
        self.checkpoints.append(checkpoint)
        self._log_event("checkpoint_created", {
            "task_id": task_id,
            "checkpoint_id": checkpoint.checkpoint_id,
        })

    def get_checkpoint(self, task_id: str) -> Optional[TaskCheckpoint]:
        """Get latest checkpoint for task."""
        matching = [cp for cp in self.checkpoints if cp.task_id == task_id]
        return matching[-1] if matching else None

    def register_resource(self, resource_id: str, resource: Any) -> None:
        """Register resource for cleanup on exit."""
        self.resources[resource_id] = resource
        self._log_event("resource_registered", {"resource_id": resource_id})

    async def cleanup(self) -> None:
        """Cleanup resources and transition to cleanup state."""
        logger.info(f"Starting cleanup for session {self.session_id}")

        # Transition all running tasks to cleanup
        for task_id in self.task_states:
            if self.task_states[task_id] in (TaskState.PENDING, TaskState.RUNNING, TaskState.RETRY):
                self.transition(task_id, TaskState.CLEANUP, "Session cleanup")

        # Clean up resources
        for resource_id, resource in self.resources.items():
            try:
                if hasattr(resource, "close"):
                    resource.close()
                elif hasattr(resource, "__aexit__"):
                    await resource.__aexit__(None, None, None)
                self._log_event("resource_cleaned", {"resource_id": resource_id})
            except Exception as e:
                logger.error(f"Error cleaning resource {resource_id}: {e}")

        self.end_time = time.time()
        self._log_event("cleanup_complete", {"duration_seconds": self.duration_seconds})

    def on_state_change(self, state: TaskState, callback: Callable) -> None:
        """Register callback for state changes."""
        if state not in self.state_callbacks:
            self.state_callbacks[state] = []
        self.state_callbacks[state].append(callback)

    def _trigger_callbacks(self, state: TaskState) -> None:
        """Trigger callbacks for state change."""
        if state in self.state_callbacks:
            for callback in self.state_callbacks[state]:
                try:
                    result = callback()
                    if hasattr(result, "__await__"):
                        import asyncio
                        asyncio.create_task(result)
                except Exception as e:
                    logger.error(f"Callback error: {e}")

    def _log_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """Log event for audit trail."""
        event = {
            "timestamp": time.time(),
            "event_type": event_type,
            "session_id": self.session_id,
            **data,
        }
        self.event_log.append(event)

    def get_status(self) -> Dict[str, Any]:
        """Get current status of all tasks."""
        return {
            "session_id": self.session_id,
            "task_states": {tid: state.name for tid, state in self.task_states.items()},
            "retry_counts": self.retry_counts,
            "duration_seconds": self.duration_seconds,
            "total_tasks": len(self.task_states),
            "completed_tasks": sum(1 for s in self.task_states.values() if s == TaskState.SUCCESS),
            "failed_tasks": sum(1 for s in self.task_states.values() if s == TaskState.FAILED),
        }

    @property
    def duration_seconds(self) -> float:
        """Get session duration."""
        end = self.end_time or time.time()
        return end - self.start_time

    def to_json(self) -> str:
        """Serialize state machine to JSON."""
        return json.dumps({
            "session_id": self.session_id,
            "task_states": {tid: state.name for tid, state in self.task_states.items()},
            "transitions": [
                {
                    "from": t.from_state.name,
                    "to": t.to_state.name,
                    "reason": t.reason,
                    "timestamp": t.timestamp,
                }
                for t in self.state_transitions
            ],
            "event_log": self.event_log,
            "duration_seconds": self.duration_seconds,
        }, indent=2)
