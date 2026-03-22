from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field
from datetime import datetime
import time
from core.protocol.shared_types import RunStatus, VerificationStatus, RiskLevel

class BaseEvent(BaseModel):
    """Base event for the Elyan Protocol Layer."""
    event_id: str
    timestamp: float = Field(default_factory=time.time)
    source: str = "system"

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
    policy: str = "followup"

class RunStarted(BaseEvent):
    session_id: str
    run_id: str

class RunStatusChanged(BaseEvent):
    session_id: str
    run_id: str
    old_status: RunStatus
    new_status: RunStatus
    metadata: Dict[str, Any] = Field(default_factory=dict)

# ── Tool & Approval Events ───────────────────────────────────────────────────

class ToolRequested(BaseEvent):
    session_id: str
    run_id: str
    tool_name: str
    params: Dict[str, Any]
    risk_level: RiskLevel = RiskLevel.READ_ONLY

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

class VerificationResult(BaseEvent):
    session_id: str
    run_id: str
    status: VerificationStatus
    reason: Optional[str] = None
    evidence: Dict[str, Any] = Field(default_factory=dict)

class RunCompleted(BaseEvent):
    session_id: str
    run_id: str
    success: bool
    final_output: str

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
    MessageReceived, SessionResolved, RunQueued, RunStarted, RunStatusChanged,
    ToolRequested, ToolSucceeded, ToolFailed, ApprovalRequested, ApprovalResolved,
    OutputBlockCreated, PreviewUpdated, VerificationResult, RunCompleted, RunCompacted,
    MemoryWritten, NodeRegistered, NodeHealthUpdated
]
