"""
Workflow State Machine — Manage workflow run states and transitions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional

from utils.logger import get_logger

from .contracts import WorkflowLifecycleState, get_allowed_transitions

logger = get_logger("workflow.state_machine")


class WorkflowState(Enum):
    """Workflow run state with canonical lifecycle values and legacy aliases."""

    IDLE = WorkflowLifecycleState.RECEIVED.value
    RECEIVED = WorkflowLifecycleState.RECEIVED.value
    CLASSIFIED = WorkflowLifecycleState.CLASSIFIED.value
    SCOPED = WorkflowLifecycleState.SCOPED.value
    PLANNED = WorkflowLifecycleState.PLANNED.value
    GATHERING_CONTEXT = WorkflowLifecycleState.GATHERING_CONTEXT.value
    RUNNING = WorkflowLifecycleState.EXECUTING.value
    EXECUTING = WorkflowLifecycleState.EXECUTING.value
    REVIEWING = WorkflowLifecycleState.REVIEWING.value
    REVISING = WorkflowLifecycleState.REVISING.value
    READY_FOR_APPROVAL = WorkflowLifecycleState.READY_FOR_APPROVAL.value
    EXPORTING = WorkflowLifecycleState.EXPORTING.value
    PAUSED = WorkflowLifecycleState.PAUSED.value
    DONE = WorkflowLifecycleState.COMPLETED.value
    COMPLETED = WorkflowLifecycleState.COMPLETED.value
    FAILED = WorkflowLifecycleState.FAILED.value


@dataclass
class WorkflowRun:
    """Represents a workflow execution run."""

    run_id: str
    workflow_id: str
    state: WorkflowState
    current_step: int = 0
    history: List[dict] = field(default_factory=list)
    started_at: float = field(default_factory=lambda: datetime.now().timestamp())
    metadata: dict = field(default_factory=dict)

    def transition_to(self, new_state: WorkflowState, metadata: Optional[dict] = None):
        """Transition to new state."""
        old_state = self.state
        allowed = get_allowed_transitions(old_state.value)
        if old_state != new_state and new_state.value not in allowed:
            raise ValueError(f"Illegal workflow transition: {old_state.value} -> {new_state.value}")

        self.state = new_state
        history_entry = {
            "timestamp": datetime.now().isoformat(),
            "from": old_state.value,
            "to": new_state.value,
            "metadata": metadata or {},
        }
        self.history.append(history_entry)
        logger.info(f"Run {self.run_id}: {old_state.value} → {new_state.value}")

    def to_dict(self) -> dict:
        """Serialize to dict."""
        return {
            "run_id": self.run_id,
            "workflow_id": self.workflow_id,
            "state": self.state.value,
            "current_step": self.current_step,
            "history": self.history,
            "started_at": self.started_at,
            "metadata": self.metadata,
        }


class WorkflowStateMachine:
    """Manage workflow run states."""

    def __init__(self):
        self.runs = {}

    def start_run(self, workflow_id: str, run_id: Optional[str] = None) -> WorkflowRun:
        """Start a new workflow run."""
        if not run_id:
            import uuid

            run_id = str(uuid.uuid4())[:12]

        run = WorkflowRun(
            run_id=run_id,
            workflow_id=workflow_id,
            state=WorkflowState.IDLE,
        )
        self.runs[run_id] = run

        logger.info(f"Started run {run_id} for workflow {workflow_id}")
        return run

    def get_run(self, run_id: str) -> Optional[WorkflowRun]:
        """Get a run by ID."""
        return self.runs.get(run_id)

    def transition_run(
        self,
        run_id: str,
        new_state: WorkflowState,
        metadata: Optional[dict] = None,
    ) -> bool:
        """Transition a run to new state."""
        run = self.get_run(run_id)
        if not run:
            logger.warning(f"Run not found: {run_id}")
            return False

        try:
            run.transition_to(new_state, metadata)
            return True
        except ValueError as exc:
            logger.warning(str(exc))
            return False


__all__ = [
    "WorkflowState",
    "WorkflowRun",
    "WorkflowStateMachine",
]
