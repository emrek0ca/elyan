from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from core.pipeline_state import PipelineState


class SessionState(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass
class SubAgentTask:
    name: str
    action: str = "chat"
    params: Dict[str, Any] = field(default_factory=dict)
    description: str = ""
    objective: str = ""
    success_criteria: List[str] = field(default_factory=list)
    task_id: str = field(default_factory=lambda: f"subtask_{uuid.uuid4().hex[:8]}")
    dependencies: List[str] = field(default_factory=list)
    domain: str = "general"
    context: Dict[str, Any] = field(default_factory=dict)
    gates: List[str] = field(default_factory=list)
    target_files: List[str] = field(default_factory=list)
    tests_to_write: List[str] = field(default_factory=list)
    verification_steps: List[str] = field(default_factory=list)
    scope_guard: List[str] = field(default_factory=list)
    review_required: bool = False
    handoff_template: str = ""


@dataclass
class SubAgentResult:
    status: str
    result: Any
    notes: List[str] = field(default_factory=list)
    artifacts: List[str] = field(default_factory=list)
    execution_time_ms: int = 0
    token_usage: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SubAgentSession:
    session_id: str
    parent_session_id: str
    specialist_key: str
    task: SubAgentTask
    state: SessionState = SessionState.PENDING
    result: Optional[SubAgentResult] = None
    pipeline_state: PipelineState = field(default_factory=PipelineState)
    allowed_tools: frozenset[str] = frozenset()
    workspace_path: str = ""
    memory_path: str = ""
    auth_profile: str = "isolated"
    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    can_spawn: bool = False


__all__ = [
    "SessionState",
    "SubAgentTask",
    "SubAgentResult",
    "SubAgentSession",
]
