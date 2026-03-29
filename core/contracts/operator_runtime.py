from __future__ import annotations

import time
import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from elyan.approval.matrix import ApprovalLevel
from elyan.sandbox.policy import SandboxConfig


def _ts() -> float:
    return time.time()


class OperatorAttachmentModel(BaseModel):
    path: str
    type: str = "file"
    mime: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="allow")


class OperatorRequestModel(BaseModel):
    request_id: str = ""
    host: str = ""
    channel: str = "cli"
    user_id: str = "local"
    machine_id: str = "primary"
    device_id: str = "primary"
    session_id: str = "default"
    input_text: str = ""
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    constraints: dict[str, Any] = Field(default_factory=dict)
    safety_mode: str = "balanced_supervised"
    delivery_preferences: dict[str, Any] = Field(default_factory=dict)
    privacy_level: str = "local_first"
    cost_budget_usd: float | None = None
    local_first: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="allow")

    @classmethod
    def from_any(cls, value: Any) -> "OperatorRequestModel":
        if isinstance(value, cls):
            return value
        if hasattr(value, "to_dict"):
            try:
                data = value.to_dict()
                if isinstance(data, dict):
                    return cls.model_validate(data)
            except Exception:
                pass
        if isinstance(value, dict):
            return cls.model_validate(value)
        return cls.model_validate({})


class SkillManifest(BaseModel):
    skill_id: str = ""
    name: str = ""
    version: str = "1.0.0"
    description: str = ""
    category: str = "general"
    source: str = "builtin"
    integration_type: str = ""
    required_scopes: list[str] = Field(default_factory=list)
    auth_strategy: str = ""
    fallback_policy: str = ""
    supported_platforms: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    required_tools: list[str] = Field(default_factory=list)
    optional_tools: list[str] = Field(default_factory=list)
    commands: list[str] = Field(default_factory=list)
    approval_tools: list[str] = Field(default_factory=list)
    blocked_tools: list[str] = Field(default_factory=list)
    evidence_contract: dict[str, Any] = Field(default_factory=dict)
    latency_level: str = "standard"
    auto_intent: bool = False
    enabled: bool = True
    runtime_ready: bool = True
    workflow_id: str = ""
    trigger_markers: list[str] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=list)
    output_artifacts: list[str] = Field(default_factory=list)
    quality_checklist: list[str] = Field(default_factory=list)
    approval_level: ApprovalLevel = ApprovalLevel.NONE
    sandbox_config: SandboxConfig = Field(default_factory=SandboxConfig)
    real_time: bool = False
    tool_policy: dict[str, Any] = Field(default_factory=dict)
    output_contract: dict[str, Any] = Field(default_factory=dict)
    workflow_bundle: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    updated_at: float = Field(default_factory=_ts)

    model_config = ConfigDict(extra="allow")


class CapabilityManifest(BaseModel):
    capability_id: str = ""
    domain: str = ""
    request_class: str = ""
    confidence: float = 0.0
    objective: str = ""
    workflow_id: str = ""
    primary_action: str = ""
    preferred_tools: list[str] = Field(default_factory=list)
    output_artifacts: list[str] = Field(default_factory=list)
    quality_checklist: list[str] = Field(default_factory=list)
    learning_tags: list[str] = Field(default_factory=list)
    complexity_tier: str = "low"
    suggested_job_type: str = "communication"
    multi_agent_recommended: bool = False
    orchestration_mode: str = "single_agent"
    workflow_profile_applicable: bool = False
    requires_design_phase: bool = False
    requires_worktree: bool = False
    content_kind: str = "task"
    output_formats: list[str] = Field(default_factory=list)
    style_profile: str = "executive"
    source_policy: str = "trusted"
    quality_contract: list[str] = Field(default_factory=list)
    memory_scope: str = "task_routed"
    preview: str = ""
    request_contract: dict[str, Any] = Field(default_factory=dict)
    latency_level: str = "standard"
    requires_real_time: bool = False
    integration_type: str = ""
    required_scopes: list[str] = Field(default_factory=list)
    auth_strategy: str = ""
    fallback_policy: str = ""
    supported_platforms: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    approval_level: int = 0
    model_role: str = "router"
    selected_model: dict[str, Any] = Field(default_factory=dict)
    workflow_bundle: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    updated_at: float = Field(default_factory=_ts)

    model_config = ConfigDict(extra="allow")


class ProjectBrief(BaseModel):
    brief_id: str = Field(default_factory=lambda: f"brief_{uuid.uuid4().hex[:12]}")
    task_id: str = ""
    title: str = ""
    objective: str = ""
    repo_root: str = ""
    repo_type: str = ""
    language: str = ""
    framework: str = ""
    package_manager: str = ""
    stack_family: str = ""
    risk_level: str = "normal"
    deliverables: list[dict[str, Any]] = Field(default_factory=list)
    verification_gates: list[str] = Field(default_factory=list)
    output_dir: str = ""
    style_direction: str = ""
    privacy_mode: str = "local_first"
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: float = Field(default_factory=_ts)

    model_config = ConfigDict(extra="allow")

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class ProjectArtifact(BaseModel):
    artifact_id: str = Field(default_factory=lambda: f"artifact_{uuid.uuid4().hex[:12]}")
    brief_id: str = ""
    path: str = ""
    kind: str = "artifact"
    label: str = ""
    expected: bool = True
    source: str = "task_spec"
    checksum: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: float = Field(default_factory=_ts)

    model_config = ConfigDict(extra="allow")

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class ExecutionEvidence(BaseModel):
    evidence_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    request_id: str = ""
    user_id: str = ""
    kind: str = "artifact"
    path: str = ""
    sha256: str = ""
    screenshot_path: str = ""
    tool: str = ""
    source: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: float = Field(default_factory=_ts)

    model_config = ConfigDict(extra="allow")


class FrameObservation(BaseModel):
    observation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    daemon_id: str = ""
    captured_at: float = Field(default_factory=_ts)
    fps: float = 0.0
    latency_ms: float = 0.0
    screenshot_path: str = ""
    window_metadata: dict[str, Any] = Field(default_factory=dict)
    accessibility: dict[str, Any] = Field(default_factory=dict)
    vision: dict[str, Any] = Field(default_factory=dict)
    ocr: dict[str, Any] = Field(default_factory=dict)
    summary: str = ""
    changed: bool = False
    source: str = "local"
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="allow")


class OperatorOutcome(BaseModel):
    request_id: str = ""
    user_id: str = ""
    channel: str = "cli"
    device_id: str = "primary"
    session_id: str = "default"
    status: str = "planned"
    success: bool = False
    response_text: str = ""
    request_class: str = ""
    skill: dict[str, Any] = Field(default_factory=dict)
    capability: dict[str, Any] = Field(default_factory=dict)
    model_runtime: dict[str, Any] = Field(default_factory=dict)
    execution_path: str = ""
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    verification: dict[str, Any] = Field(default_factory=dict)
    decision_trace: dict[str, Any] = Field(default_factory=dict)
    latency_ms: float = 0.0
    fallback_reason: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: float = Field(default_factory=_ts)

    model_config = ConfigDict(extra="allow")


__all__ = [
    "CapabilityManifest",
    "ExecutionEvidence",
    "FrameObservation",
    "OperatorAttachmentModel",
    "OperatorOutcome",
    "OperatorRequestModel",
    "ProjectArtifact",
    "ProjectBrief",
    "SkillManifest",
]
