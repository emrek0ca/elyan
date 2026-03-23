"""
Workflow State Machine — Manage workflow run states and transitions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List
from datetime import datetime

from utils.logger import get_logger

logger = get_logger("workflow.state_machine")


class WorkflowState(Enum):
    """Workflow run state."""
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    DONE = "done"
    FAILED = "failed"


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
        self.runs = {}  # run_id -> WorkflowRun

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

        run.transition_to(new_state, metadata)
        return True


__all__ = [
    "WorkflowState",
    "WorkflowRun",
    "WorkflowStateMachine",
]
