import time
import uuid
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from core.protocol.shared_types import RunStatus
from core.observability.logger import get_structured_logger

slog = get_structured_logger("run_lifecycle")

class RunError(BaseModel):
    code: str
    message: str
    details: Dict[str, Any] = Field(default_factory=dict)

class RunState(BaseModel):
    """Represents the explicit state of a single execution run."""
    run_id: str = Field(default_factory=lambda: f"run_{uuid.uuid4().hex[:8]}")
    session_id: str
    status: RunStatus = RunStatus.QUEUED
    created_at: float = Field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    last_updated_at: float = Field(default_factory=time.time)
    
    # Traceability
    parent_run_id: Optional[str] = None
    event_ids: List[str] = Field(default_factory=list)
    
    # Results and Errors
    error: Optional[RunError] = None
    output_summary: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def transition_to(self, new_status: RunStatus):
        """Safely transition the run to a new status with validation."""
        old_status = self.status
        # Simple validation: cannot transition out of terminal states
        terminal_states = {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}
        if self.status in terminal_states:
            raise RuntimeError(f"Cannot transition run {self.run_id} from terminal state {self.status} to {new_status}")

        if new_status == RunStatus.STARTED and not self.started_at:
            self.started_at = time.time()
        
        if new_status in terminal_states:
            self.finished_at = time.time()

        self.status = new_status
        self.last_updated_at = time.time()
        
        # Emit status change event
        slog.log_event("run_status_changed", {
            "run_id": self.run_id,
            "old_status": old_status,
            "new_status": new_status,
            "duration": (self.finished_at - self.started_at) if self.finished_at and self.started_at else None
        }, session_id=self.session_id, run_id=self.run_id)

class RunLifecycleManager:
    """Manages the creation and state tracking of runs."""
    def __init__(self):
        self._active_runs: Dict[str, RunState] = {}

    def create_run(self, session_id: str, event_id: Optional[str] = None) -> RunState:
        run = RunState(session_id=session_id)
        if event_id:
            run.event_ids.append(event_id)
        self._active_runs[run.run_id] = run
        return run

    def get_run(self, run_id: str) -> Optional[RunState]:
        return self._active_runs.get(run_id)

    def update_status(self, run_id: str, status: RunStatus, error: Optional[RunError] = None):
        run = self.get_run(run_id)
        if not run:
            raise ValueError(f"Run {run_id} not found")
        
        if error:
            run.error = error
            
        run.transition_to(status)

# Global Singleton
run_lifecycle_manager = RunLifecycleManager()
