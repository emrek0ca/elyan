"""
Canonical workflow contracts for Elyan vNext.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Set


class WorkflowTaskType(str, Enum):
    DOCUMENT = "document"
    PRESENTATION = "presentation"
    WEBSITE = "website"


class WorkflowLifecycleState(str, Enum):
    RECEIVED = "received"
    CLASSIFIED = "classified"
    SCOPED = "scoped"
    PLANNED = "planned"
    GATHERING_CONTEXT = "gathering_context"
    EXECUTING = "executing"
    REVIEWING = "reviewing"
    REVISING = "revising"
    READY_FOR_APPROVAL = "ready_for_approval"
    EXPORTING = "exporting"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"


class WorkflowAgentRole(str, Enum):
    EXECUTIVE = "executive"
    PLANNER = "planner"
    RESEARCH = "research"
    ARTIFACT = "artifact"
    CODE = "code"
    REVIEW = "review"
    SECURITY = "security"


WORKFLOW_TRANSITIONS: Dict[str, Set[str]] = {
    WorkflowLifecycleState.RECEIVED.value: {
        WorkflowLifecycleState.CLASSIFIED.value,
        WorkflowLifecycleState.EXECUTING.value,
        WorkflowLifecycleState.FAILED.value,
    },
    WorkflowLifecycleState.CLASSIFIED.value: {
        WorkflowLifecycleState.SCOPED.value,
        WorkflowLifecycleState.EXECUTING.value,
        WorkflowLifecycleState.FAILED.value,
    },
    WorkflowLifecycleState.SCOPED.value: {
        WorkflowLifecycleState.PLANNED.value,
        WorkflowLifecycleState.EXECUTING.value,
        WorkflowLifecycleState.FAILED.value,
    },
    WorkflowLifecycleState.PLANNED.value: {
        WorkflowLifecycleState.GATHERING_CONTEXT.value,
        WorkflowLifecycleState.EXECUTING.value,
        WorkflowLifecycleState.FAILED.value,
    },
    WorkflowLifecycleState.GATHERING_CONTEXT.value: {
        WorkflowLifecycleState.EXECUTING.value,
        WorkflowLifecycleState.FAILED.value,
    },
    WorkflowLifecycleState.EXECUTING.value: {
        WorkflowLifecycleState.REVIEWING.value,
        WorkflowLifecycleState.READY_FOR_APPROVAL.value,
        WorkflowLifecycleState.EXPORTING.value,
        WorkflowLifecycleState.COMPLETED.value,
        WorkflowLifecycleState.PAUSED.value,
        WorkflowLifecycleState.FAILED.value,
    },
    WorkflowLifecycleState.REVIEWING.value: {
        WorkflowLifecycleState.REVISING.value,
        WorkflowLifecycleState.READY_FOR_APPROVAL.value,
        WorkflowLifecycleState.EXPORTING.value,
        WorkflowLifecycleState.COMPLETED.value,
        WorkflowLifecycleState.PAUSED.value,
        WorkflowLifecycleState.FAILED.value,
    },
    WorkflowLifecycleState.REVISING.value: {
        WorkflowLifecycleState.EXECUTING.value,
        WorkflowLifecycleState.REVIEWING.value,
        WorkflowLifecycleState.FAILED.value,
    },
    WorkflowLifecycleState.READY_FOR_APPROVAL.value: {
        WorkflowLifecycleState.EXPORTING.value,
        WorkflowLifecycleState.EXECUTING.value,
        WorkflowLifecycleState.COMPLETED.value,
        WorkflowLifecycleState.FAILED.value,
    },
    WorkflowLifecycleState.EXPORTING.value: {
        WorkflowLifecycleState.COMPLETED.value,
        WorkflowLifecycleState.FAILED.value,
    },
    WorkflowLifecycleState.PAUSED.value: {
        WorkflowLifecycleState.EXECUTING.value,
        WorkflowLifecycleState.REVIEWING.value,
        WorkflowLifecycleState.FAILED.value,
    },
    WorkflowLifecycleState.COMPLETED.value: set(),
    WorkflowLifecycleState.FAILED.value: set(),
}


@dataclass(frozen=True)
class WorkflowStageDefinition:
    state: WorkflowLifecycleState
    owner: WorkflowAgentRole
    timeout_sec: int
    retry_budget: int
    approval_required: bool = False
    failure_reasons: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class WorkflowFlowTemplate:
    task_type: WorkflowTaskType
    stages: List[WorkflowStageDefinition]
    artifact_targets: List[str]


FLOW_TEMPLATES: Dict[str, WorkflowFlowTemplate] = {
    WorkflowTaskType.DOCUMENT.value: WorkflowFlowTemplate(
        task_type=WorkflowTaskType.DOCUMENT,
        stages=[
            WorkflowStageDefinition(WorkflowLifecycleState.RECEIVED, WorkflowAgentRole.EXECUTIVE, 30, 0),
            WorkflowStageDefinition(WorkflowLifecycleState.CLASSIFIED, WorkflowAgentRole.EXECUTIVE, 30, 0),
            WorkflowStageDefinition(WorkflowLifecycleState.SCOPED, WorkflowAgentRole.PLANNER, 60, 1),
            WorkflowStageDefinition(WorkflowLifecycleState.PLANNED, WorkflowAgentRole.PLANNER, 90, 1),
            WorkflowStageDefinition(WorkflowLifecycleState.GATHERING_CONTEXT, WorkflowAgentRole.RESEARCH, 180, 2),
            WorkflowStageDefinition(WorkflowLifecycleState.EXECUTING, WorkflowAgentRole.ARTIFACT, 300, 2),
            WorkflowStageDefinition(WorkflowLifecycleState.REVIEWING, WorkflowAgentRole.REVIEW, 120, 1),
            WorkflowStageDefinition(WorkflowLifecycleState.READY_FOR_APPROVAL, WorkflowAgentRole.SECURITY, 600, 0, approval_required=True),
            WorkflowStageDefinition(WorkflowLifecycleState.EXPORTING, WorkflowAgentRole.ARTIFACT, 180, 1),
        ],
        artifact_targets=["docx", "pdf"],
    ),
    WorkflowTaskType.PRESENTATION.value: WorkflowFlowTemplate(
        task_type=WorkflowTaskType.PRESENTATION,
        stages=[
            WorkflowStageDefinition(WorkflowLifecycleState.RECEIVED, WorkflowAgentRole.EXECUTIVE, 30, 0),
            WorkflowStageDefinition(WorkflowLifecycleState.CLASSIFIED, WorkflowAgentRole.EXECUTIVE, 30, 0),
            WorkflowStageDefinition(WorkflowLifecycleState.SCOPED, WorkflowAgentRole.PLANNER, 60, 1),
            WorkflowStageDefinition(WorkflowLifecycleState.PLANNED, WorkflowAgentRole.PLANNER, 90, 1),
            WorkflowStageDefinition(WorkflowLifecycleState.GATHERING_CONTEXT, WorkflowAgentRole.RESEARCH, 180, 2),
            WorkflowStageDefinition(WorkflowLifecycleState.EXECUTING, WorkflowAgentRole.ARTIFACT, 300, 2),
            WorkflowStageDefinition(WorkflowLifecycleState.REVIEWING, WorkflowAgentRole.REVIEW, 120, 1),
            WorkflowStageDefinition(WorkflowLifecycleState.EXPORTING, WorkflowAgentRole.ARTIFACT, 180, 1),
        ],
        artifact_targets=["pptx"],
    ),
    WorkflowTaskType.WEBSITE.value: WorkflowFlowTemplate(
        task_type=WorkflowTaskType.WEBSITE,
        stages=[
            WorkflowStageDefinition(WorkflowLifecycleState.RECEIVED, WorkflowAgentRole.EXECUTIVE, 30, 0),
            WorkflowStageDefinition(WorkflowLifecycleState.CLASSIFIED, WorkflowAgentRole.EXECUTIVE, 30, 0),
            WorkflowStageDefinition(WorkflowLifecycleState.SCOPED, WorkflowAgentRole.PLANNER, 60, 1),
            WorkflowStageDefinition(WorkflowLifecycleState.PLANNED, WorkflowAgentRole.PLANNER, 90, 1),
            WorkflowStageDefinition(WorkflowLifecycleState.GATHERING_CONTEXT, WorkflowAgentRole.RESEARCH, 180, 2),
            WorkflowStageDefinition(WorkflowLifecycleState.EXECUTING, WorkflowAgentRole.CODE, 420, 2),
            WorkflowStageDefinition(WorkflowLifecycleState.REVIEWING, WorkflowAgentRole.REVIEW, 180, 1),
        ],
        artifact_targets=["react_scaffold"],
    ),
}


def get_allowed_transitions(state: str) -> Set[str]:
    return set(WORKFLOW_TRANSITIONS.get(str(state), set()))


def is_terminal_state(state: str) -> bool:
    token = str(state)
    return token in {
        WorkflowLifecycleState.COMPLETED.value,
        WorkflowLifecycleState.FAILED.value,
    }
