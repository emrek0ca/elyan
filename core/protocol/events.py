from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field
import time
from core.protocol.shared_types import ExecutionMode, QueuePolicy, RunStatus, VerificationStatus, RiskLevel

class BaseEvent(BaseModel):
    """Base event for the Elyan Protocol Layer."""
    event_id: str
    timestamp: float = Field(default_factory=time.time)
    source: str = "system"
    schema_version: int = 1
    correlation_id: Optional[str] = None
    causation_id: Optional[str] = None
    idempotency_key: Optional[str] = None
    business_justification: Optional[str] = None

# ── Identity Schemas ─────────────────────────────────────────────────────────

class ActorIdentity(BaseModel):
    actor_id: str
    actor_type: str  # user, system, automation
    display_name: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

class SessionIdentity(BaseModel):
    session_id: str
    owner_id: str
    created_at: float
    metadata: Dict[str, Any] = Field(default_factory=dict)

class WorkspaceIdentity(BaseModel):
    workspace_id: str
    path: str
    name: str
    metadata: Dict[str, Any] = Field(default_factory=dict)

# ── Message Events ──────────────────────────────────────────────────────────

class MessageReceived(BaseEvent):
    channel: str
    channel_id: str
    user_id: str
    text: str
    attachments: List[Dict[str, Any]] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

# ── Session & Run Events ─────────────────────────────────────────────────────

class SessionResolved(BaseEvent):
    session_id: str
    user_id: str
    channel: str
    workspace_id: Optional[str] = None
    agent_id: str = "default"

class RunQueued(BaseEvent):
    session_id: str
    run_id: str
    policy: QueuePolicy = QueuePolicy.FOLLOWUP
    queue_depth: int = 0

class RunStarted(BaseEvent):
    session_id: str
    run_id: str
    execution_mode: Optional[ExecutionMode] = None

class RunStatusChanged(BaseEvent):
    session_id: str
    run_id: str
    old_status: RunStatus
    new_status: RunStatus
    metadata: Dict[str, Any] = Field(default_factory=dict)

class SessionStateChanged(BaseEvent):
    session_id: str
    actor_id: str
    old_lane_state: str
    new_lane_state: str
    queue_policy: QueuePolicy = QueuePolicy.FOLLOWUP
    metadata: Dict[str, Any] = Field(default_factory=dict)

class PlanCreated(BaseEvent):
    session_id: str
    run_id: str
    planner_id: str
    plan_id: str
    step_count: int = 0
    execution_mode: Optional[ExecutionMode] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

class PlanStepStarted(BaseEvent):
    session_id: str
    run_id: str
    plan_id: str
    step_id: str
    phase: str
    specialist_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

class PlanStepCompleted(BaseEvent):
    session_id: str
    run_id: str
    plan_id: str
    step_id: str
    phase: str
    success: bool = True
    metadata: Dict[str, Any] = Field(default_factory=dict)

# ── Consensus, Learning & Mode Events ───────────────────────────────────────

class ConsensusProposed(BaseEvent):
    session_id: str
    consensus_id: str
    topic: str
    proposed_by: str
    candidates: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

class ConsensusResolved(BaseEvent):
    session_id: str
    consensus_id: str
    resolved_by: str
    accepted: bool
    selected_option: Optional[str] = None
    rationale: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

class LearningSignalRecorded(BaseEvent):
    session_id: str
    signal_type: str
    value: float
    source_event_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

class ModeSwitched(BaseEvent):
    session_id: str
    from_mode: ExecutionMode
    to_mode: ExecutionMode
    reason: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

class DeadlockRecovered(BaseEvent):
    session_id: str
    run_id: str
    deadlock_type: str
    recovery_action: str
    attempts: int = 1
    metadata: Dict[str, Any] = Field(default_factory=dict)

# ── Tool & Approval Events ───────────────────────────────────────────────────

class ToolRequested(BaseEvent):
    session_id: str
    run_id: str
    tool_name: str
    params: Dict[str, Any]
    risk_level: RiskLevel = RiskLevel.READ_ONLY
    approval_required: bool = False
    tool_request_id: Optional[str] = None

class ToolApproved(BaseEvent):
    session_id: str
    run_id: str
    tool_name: str
    request_id: str
    approver_id: str
    metadata: Dict[str, Any] = Field(default_factory=dict)

class ToolRejected(BaseEvent):
    session_id: str
    run_id: str
    tool_name: str
    request_id: str
    approver_id: str
    reason: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

class ToolSucceeded(BaseEvent):
    session_id: str
    run_id: str
    tool_name: str
    result: Any

class ToolFailed(BaseEvent):
    session_id: str
    run_id: str
    tool_name: str
    error: str

class ApprovalRequested(BaseEvent):
    session_id: str
    run_id: str
    request_id: str
    action_type: str
    payload: Dict[str, Any]
    risk_level: RiskLevel
    reason: str

class ApprovalResolved(BaseEvent):
    session_id: str
    run_id: str
    request_id: str
    approved: bool
    resolver_id: str
    comment: Optional[str] = None

# ── Output & Verification Events ─────────────────────────────────────────────

class OutputBlockCreated(BaseEvent):
    session_id: str
    run_id: str
    block_type: str  # text, code, json, ui
    content: str

class PreviewUpdated(BaseEvent):
    session_id: str
    run_id: str
    preview_state: Dict[str, Any]

class VerificationStarted(BaseEvent):
    session_id: str
    run_id: str
    verifier_id: str
    verification_target: str
    metadata: Dict[str, Any] = Field(default_factory=dict)

class VerificationResult(BaseEvent):
    session_id: str
    run_id: str
    status: VerificationStatus
    reason: Optional[str] = None
    evidence: Dict[str, Any] = Field(default_factory=dict)

class RecoveryStarted(BaseEvent):
    session_id: str
    run_id: str
    recovery_id: str
    strategy: str
    trigger: str
    metadata: Dict[str, Any] = Field(default_factory=dict)

class RecoveryCompleted(BaseEvent):
    session_id: str
    run_id: str
    recovery_id: str
    outcome: str
    resumed_run: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)

class RunCompleted(BaseEvent):
    session_id: str
    run_id: str
    success: bool
    final_output: str

class RunFailed(BaseEvent):
    session_id: str
    run_id: str
    failure_code: str
    reason: str
    recoverable: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)

class RunCancelled(BaseEvent):
    session_id: str
    run_id: str
    cancelled_by: str
    reason: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

class RunCompacted(BaseEvent):
    session_id: str
    run_id: str
    compact_summary: str

# ── Memory & Node Events ─────────────────────────────────────────────────────

class MemoryWritten(BaseEvent):
    session_id: str
    level: str  # working, episodic, profile, project
    content: str
    metadata: Dict[str, Any] = Field(default_factory=dict)

class NodeRegistered(BaseEvent):
    node_id: str
    node_type: str
    capabilities: List[str]
    hostname: str
    ip_address: Optional[str] = None

class NodeHealthUpdated(BaseEvent):
    node_id: str
    status: str
    cpu_usage: float
    memory_usage: float
    last_seen: float = Field(default_factory=time.time)

# ── Union Export ─────────────────────────────────────────────────────────────

ElyanEvent = Union[
    MessageReceived, SessionResolved, RunQueued, RunStarted, RunStatusChanged, SessionStateChanged,
    PlanCreated, PlanStepStarted, PlanStepCompleted,
    ConsensusProposed, ConsensusResolved, LearningSignalRecorded, ModeSwitched, DeadlockRecovered,
    ToolRequested, ToolApproved, ToolRejected, ToolSucceeded, ToolFailed, ApprovalRequested, ApprovalResolved,
    OutputBlockCreated, PreviewUpdated, VerificationStarted, VerificationResult,
    RecoveryStarted, RecoveryCompleted, RunCompleted, RunFailed, RunCancelled, RunCompacted,
    MemoryWritten, NodeRegistered, NodeHealthUpdated
]
