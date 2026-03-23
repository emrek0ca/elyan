"""
Workflow Engine — Create, store, and execute workflows.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from utils.logger import get_logger
from .state_machine import WorkflowStateMachine, WorkflowState

logger = get_logger("workflow.engine")


@dataclass
class WorkflowStep:
    """Single workflow step."""
    name: str
    action: str  # "shell" | "python" | tool_name
    params: dict
    retry: int = 1
    timeout: int = 30
    on_failure: str = "abort"  # abort | continue | retry


@dataclass
class WorkflowDefinition:
    """Complete workflow definition."""
    workflow_id: str
    name: str
    description: str
    steps: List[WorkflowStep]
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class WorkflowResult:
    """Workflow execution result."""
    success: bool
    workflow_id: str
    name: str
    steps_total: int
    steps_done: int
    steps_failed: int
    outputs: List[dict] = field(default_factory=list)  # {name, success, output, duration}
    text: str = ""
    elapsed: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


class WorkflowEngine:
    """
    Workflow orchestration engine.
    - Create workflows from specs
    - Run workflows step-by-step
    - Persist workflows to disk
    """

    def __init__(self):
        self.sm = WorkflowStateMachine()
        self._workflows = {}  # workflow_id -> WorkflowDefinition
        self._load_workflows()

    def _get_workflows_dir(self) -> Path:
        """Get ~/.elyan/workflows directory."""
        workflows_dir = Path.home() / ".elyan" / "workflows"
        workflows_dir.mkdir(parents=True, exist_ok=True)
        return workflows_dir

    def _load_workflows(self):
        """Load workflows from disk."""
        workflows_dir = self._get_workflows_dir()
        for workflow_file in workflows_dir.glob("*.json"):
            try:
                data = json.loads(workflow_file.read_text())
                workflow_id = data.get("workflow_id", "")
                steps = [WorkflowStep(**step) for step in data.get("steps", [])]
                wf = WorkflowDefinition(
                    workflow_id=workflow_id,
                    name=data.get("name", ""),
                    description=data.get("description", ""),
                    steps=steps,
                    created_at=data.get("created_at", ""),
                )
                self._workflows[workflow_id] = wf
            except Exception as e:
                logger.warning(f"Failed to load workflow {workflow_file}: {e}")

    def create(
        self,
        name: str,
        steps: List[dict],
        description: str = "",
        workflow_id: Optional[str] = None,
    ) -> WorkflowDefinition:
        """
        Create a new workflow.

        Args:
            name: Workflow name
            steps: List of step dicts {name, action, params, retry, timeout, on_failure}
            description: optional description
            workflow_id: optional custom ID

        Returns:
            WorkflowDefinition
        """
        if not workflow_id:
            workflow_id = str(uuid.uuid4())[:12]

        parsed_steps = [WorkflowStep(**step) for step in steps]

        wf = WorkflowDefinition(
            workflow_id=workflow_id,
            name=name,
            description=description,
            steps=parsed_steps,
        )

        self._workflows[workflow_id] = wf
        self._save_workflow(wf)

        logger.info(f"Created workflow {workflow_id}: {name}")
        return wf

    def _save_workflow(self, wf: WorkflowDefinition):
        """Save workflow to disk."""
        workflows_dir = self._get_workflows_dir()
        wf_file = workflows_dir / f"{wf.workflow_id}.json"

        data = {
            "workflow_id": wf.workflow_id,
            "name": wf.name,
            "description": wf.description,
            "steps": [asdict(step) for step in wf.steps],
            "created_at": wf.created_at,
        }

        wf_file.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        logger.info(f"Saved workflow {wf.workflow_id}")

    def get(self, workflow_id: str) -> Optional[WorkflowDefinition]:
        """Get a workflow by ID."""
        return self._workflows.get(workflow_id)

    def list(self) -> List[dict]:
        """List all workflows."""
        return [
            {
                "workflow_id": wf.workflow_id,
                "name": wf.name,
                "step_count": len(wf.steps),
                "created_at": wf.created_at,
            }
            for wf in self._workflows.values()
        ]

    def delete(self, workflow_id: str) -> bool:
        """Delete a workflow."""
        if workflow_id not in self._workflows:
            return False

        del self._workflows[workflow_id]

        workflows_dir = self._get_workflows_dir()
        wf_file = workflows_dir / f"{workflow_id}.json"
        wf_file.unlink(missing_ok=True)

        logger.info(f"Deleted workflow {workflow_id}")
        return True

    async def run(self, workflow_id: str) -> WorkflowResult:
        """Execute a workflow."""
        wf = self.get(workflow_id)
        if not wf:
            return WorkflowResult(
                success=False,
                workflow_id=workflow_id,
                name="",
                steps_total=0,
                steps_done=0,
                steps_failed=0,
                text="Workflow not found",
            )

        return await self.run_inline(
            [asdict(step) for step in wf.steps],
            name=wf.name,
        )

    async def run_inline(
        self,
        steps: List[dict],
        name: str = "inline",
    ) -> WorkflowResult:
        """Execute steps inline without persistence."""
        import time
        start_time = time.time()

        outputs = []
        steps_done = 0
        steps_failed = 0

        logger.info(f"Starting workflow '{name}' with {len(steps)} steps")

        for i, step_dict in enumerate(steps):
            step = WorkflowStep(**step_dict)

            try:
                output = await self._execute_step(step)
                outputs.append({
                    "name": step.name,
                    "success": output.get("success", False),
                    "output": output.get("output", ""),
                    "duration": output.get("duration", 0),
                })

                if output.get("success"):
                    steps_done += 1
                else:
                    steps_failed += 1
                    if step.on_failure == "abort":
                        logger.warning(f"Step {step.name} failed, aborting")
                        break

            except Exception as e:
                logger.error(f"Step {step.name} error: {e}")
                steps_failed += 1
                outputs.append({
                    "name": step.name,
                    "success": False,
                    "output": str(e),
                    "duration": 0,
                })

                if step.on_failure == "abort":
                    break

        elapsed = time.time() - start_time

        success = steps_failed == 0
        text = f"Workflow '{name}' {'completed' if success else 'failed'}: {steps_done}/{len(steps)} steps"

        return WorkflowResult(
            success=success,
            workflow_id="inline",
            name=name,
            steps_total=len(steps),
            steps_done=steps_done,
            steps_failed=steps_failed,
            outputs=outputs,
            text=text,
            elapsed=elapsed,
        )

    async def _execute_step(self, step: WorkflowStep) -> dict:
        """Execute a single step."""
        import time
        start = time.time()

        try:
            if step.action == "shell":
                from tools.code_execution_tools import execute_shell_command
                result = await execute_shell_command(step.params.get("command", ""))
            elif step.action == "python":
                from tools.code_execution_tools import execute_python_code
                result = await execute_python_code(step.params.get("code", ""))
            else:
                # Unknown action
                return {
                    "success": False,
                    "output": f"Unknown action: {step.action}",
                    "duration": time.time() - start,
                }

            return {
                "success": result.get("success", False),
                "output": result.get("output", ""),
                "duration": time.time() - start,
            }

        except Exception as e:
            return {
                "success": False,
                "output": str(e),
                "duration": time.time() - start,
            }


__all__ = [
    "WorkflowEngine",
    "WorkflowDefinition",
    "WorkflowStep",
    "WorkflowResult",
]
