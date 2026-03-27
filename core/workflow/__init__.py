"""
core/workflow — Workflow Orchestration Module
Create, store, and execute multi-step workflows.
"""

from __future__ import annotations

from .contracts import (
    FLOW_TEMPLATES,
    WorkflowAgentRole,
    WorkflowFlowTemplate,
    WorkflowLifecycleState,
    WorkflowStageDefinition,
    WorkflowTaskType,
)
from .engine import WorkflowEngine, WorkflowDefinition, WorkflowStep, WorkflowResult
from .formatter import format_text, format_json, format_md
from .vertical_runner import VerticalWorkflowRunner, get_vertical_workflow_runner

_workflow_engine: WorkflowEngine | None = None


def get_workflow_engine() -> WorkflowEngine:
    """Singleton: get or create WorkflowEngine."""
    global _workflow_engine
    if _workflow_engine is None:
        _workflow_engine = WorkflowEngine()
    return _workflow_engine


__all__ = [
    "WorkflowEngine",
    "WorkflowDefinition",
    "WorkflowStep",
    "WorkflowResult",
    "get_workflow_engine",
    "format_text",
    "format_json",
    "format_md",
    "FLOW_TEMPLATES",
    "WorkflowAgentRole",
    "WorkflowFlowTemplate",
    "WorkflowLifecycleState",
    "WorkflowStageDefinition",
    "WorkflowTaskType",
    "VerticalWorkflowRunner",
    "get_vertical_workflow_runner",
]
