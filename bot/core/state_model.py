# state_model.py implementation
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Callable
from enum import Enum
import time

class GoalStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    ACHIEVED = "achieved"
    FAILED = "failed"

class StepStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    AWAITING_APPROVAL = "awaiting_approval"

class ApprovalStatus(Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    TIMEOUT = "timeout"

@dataclass
class Goal:
    intent: str
    definition: str
    success_criteria: List[str]
    params: Dict[str, Any] = field(default_factory=dict)
    status: GoalStatus = GoalStatus.PENDING

@dataclass
class TaskStep:
    id: str
    description: str
    tool_name: str
    params: Dict[str, Any]
    verification: str
    status: StepStatus = StepStatus.PENDING
    observation: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    retry_count: int = 0  # Track retry attempts

@dataclass
class ApprovalRequest:
    """Represents a pending approval for a high-risk operation"""
    step_id: str
    tool_name: str
    description: str
    action: str
    risk_level: str
    timestamp: float = field(default_factory=time.time)
    status: ApprovalStatus = ApprovalStatus.PENDING
    approval_callback: Optional[Callable] = None
    timeout_seconds: int = 30

    def is_expired(self) -> bool:
        return (time.time() - self.timestamp) > self.timeout_seconds

@dataclass
class AgentState:
    current_goal: Optional[Goal] = None
    plan: List[TaskStep] = field(default_factory=list)
    current_step_index: int = 0
    history: List[Dict[str, Any]] = field(default_factory=list)
    system_observation: str = ""
    error_reason: Optional[str] = None
    pending_approval: Optional[ApprovalRequest] = None
    request_id: str = ""  # Unique request identifier for cancellation
    should_cancel: bool = False  # Flag to request cancellation
    data_pipe: Dict[str, Any] = field(default_factory=dict) # Autonomous data piping

    def is_complete(self) -> bool:
        if not self.current_goal:
            return True
        return self.current_goal.status in [GoalStatus.ACHIEVED, GoalStatus.FAILED]

    def get_current_step(self) -> Optional[TaskStep]:
        if 0 <= self.current_step_index < len(self.plan):
            return self.plan[self.current_step_index]
        return None
