"""
Comprehensive Task Executor
Executes complex multi-step workflows with research, document generation, and visualization
"""

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum
from utils.logger import get_logger

logger = get_logger("comprehensive_executor")


class WorkflowStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepType(Enum):
    RESEARCH = "research"
    DOCUMENT = "document"
    VISUALIZATION = "visualization"
    FILE_OPERATION = "file_operation"
    NOTIFICATION = "notification"
    CUSTOM = "custom"


@dataclass
class WorkflowStep:
    """A step in the workflow"""
    id: str
    name: str
    step_type: StepType
    params: Dict[str, Any]
    depends_on: List[str] = field(default_factory=list)
    status: WorkflowStatus = WorkflowStatus.PENDING
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


@dataclass
class Workflow:
    """Complete workflow definition"""
    id: str
    name: str
    description: str
    steps: List[WorkflowStep]
    status: WorkflowStatus = WorkflowStatus.PENDING
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    results: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


class ComprehensiveExecutor:
    """Execute complex multi-step workflows"""

    def __init__(self):
        self.active_workflows: Dict[str, Workflow] = {}
        self._workflow_counter = 0

    def _generate_workflow_id(self) -> str:
        """Generate unique workflow ID"""
        self._workflow_counter += 1
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"workflow_{timestamp}_{self._workflow_counter}"

    def create_research_workflow(
        self,
        topic: str,
        depth: str = "comprehensive",
        include_document: bool = True,
        include_visualization: bool = True,
        document_format: str = "docx",
        language: str = "tr"
    ) -> Workflow:
        """
        Create a comprehensive research workflow

        Args:
            topic: Research topic
            depth: Research depth (quick/standard/comprehensive/academic)
            include_document: Generate document from results
            include_visualization: Create visualizations
            document_format: Output document format
            language: Language for output

        Returns:
            Workflow object
        """
        workflow_id = self._generate_workflow_id()
        steps = []

        # Step 1: Deep Research
        steps.append(WorkflowStep(
            id="research",
            name=f"Derin araştırma: {topic}",
            step_type=StepType.RESEARCH,
            params={
                "topic": topic,
                "depth": depth,
                "language": language,
                "include_academic": True
            }
        ))

        # Step 2: Create Visualizations (depends on research)
        if include_visualization:
            steps.append(WorkflowStep(
                id="visualization",
                name="Araştırma görselleştirmesi",
                step_type=StepType.VISUALIZATION,
                params={
                    "research_data_from": "research"
                },
                depends_on=["research"]
            ))

        # Step 3: Generate Document (depends on research)
        if include_document:
            steps.append(WorkflowStep(
                id="document",
                name="Araştırma belgesi oluştur",
                step_type=StepType.DOCUMENT,
                params={
                    "research_data_from": "research",
                    "format": document_format,
                    "template": "research_report",
                    "language": language
                },
                depends_on=["research"]
            ))

        # Step 4: Send Notification (depends on all)
        depends = ["research"]
        if include_visualization:
            depends.append("visualization")
        if include_document:
            depends.append("document")

        steps.append(WorkflowStep(
            id="notification",
            name="Tamamlanma bildirimi",
            step_type=StepType.NOTIFICATION,
            params={
                "title": "Araştırma Tamamlandı",
                "message": f"'{topic}' araştırması tamamlandı"
            },
            depends_on=depends
        ))

        workflow = Workflow(
            id=workflow_id,
            name=f"Kapsamlı Araştırma: {topic}",
            description=f"{topic} hakkında {depth} düzeyde araştırma, belge ve görselleştirme",
            steps=steps
        )

        self.active_workflows[workflow_id] = workflow
        return workflow

    def create_custom_workflow(
        self,
        name: str,
        description: str,
        step_definitions: List[Dict[str, Any]]
    ) -> Workflow:
        """
        Create a custom workflow from step definitions

        Args:
            name: Workflow name
            description: Workflow description
            step_definitions: List of step definitions

        Returns:
            Workflow object
        """
        workflow_id = self._generate_workflow_id()
        steps = []

        type_map = {
            "research": StepType.RESEARCH,
            "document": StepType.DOCUMENT,
            "visualization": StepType.VISUALIZATION,
            "file": StepType.FILE_OPERATION,
            "notification": StepType.NOTIFICATION,
            "custom": StepType.CUSTOM
        }

        for i, step_def in enumerate(step_definitions):
            step_type = type_map.get(step_def.get("type", "custom"), StepType.CUSTOM)
            step_id = step_def.get("id", f"step_{i+1}")

            steps.append(WorkflowStep(
                id=step_id,
                name=step_def.get("name", f"Adım {i+1}"),
                step_type=step_type,
                params=step_def.get("params", {}),
                depends_on=step_def.get("depends_on", [])
            ))

        workflow = Workflow(
            id=workflow_id,
            name=name,
            description=description,
            steps=steps
        )

        self.active_workflows[workflow_id] = workflow
        return workflow

    async def execute_workflow(
        self,
        workflow: Workflow,
        progress_callback: Optional[Callable] = None
    ) -> Dict[str, Any]:
        """
        Execute a workflow

        Args:
            workflow: Workflow to execute
            progress_callback: Optional callback for progress updates

        Returns:
            Workflow results
        """
        logger.info(f"Starting workflow: {workflow.name}")
        workflow.status = WorkflowStatus.RUNNING
        workflow.started_at = datetime.now().isoformat()

        try:
            completed_steps = set()
            step_results = {}

            while len(completed_steps) < len(workflow.steps):
                # Find ready steps (all dependencies completed)
                ready_steps = [
                    step for step in workflow.steps
                    if step.id not in completed_steps
                    and all(dep in completed_steps for dep in step.depends_on)
                ]

                if not ready_steps:
                    # Check for circular dependencies or errors
                    pending = [s.id for s in workflow.steps if s.id not in completed_steps]
                    logger.error(f"No ready steps, pending: {pending}")
                    break

                # Execute ready steps (can be parallel if no dependencies between them)
                for step in ready_steps:
                    step.status = WorkflowStatus.RUNNING
                    step.started_at = datetime.now().isoformat()

                    if progress_callback:
                        progress = (len(completed_steps) / len(workflow.steps)) * 100
                        await progress_callback(progress, f"Çalıştırılıyor: {step.name}")

                    try:
                        # Execute step based on type
                        result = await self._execute_step(step, step_results)
                        step.result = result
                        step.status = WorkflowStatus.COMPLETED
                        step_results[step.id] = result

                    except Exception as e:
                        logger.error(f"Step {step.id} failed: {e}")
                        step.status = WorkflowStatus.FAILED
                        step.error = str(e)
                        step_results[step.id] = {"success": False, "error": str(e)}

                    step.completed_at = datetime.now().isoformat()
                    completed_steps.add(step.id)

            # Determine overall status
            failed_steps = [s for s in workflow.steps if s.status == WorkflowStatus.FAILED]
            if failed_steps:
                workflow.status = WorkflowStatus.FAILED
                workflow.error = f"{len(failed_steps)} adım başarısız oldu"
            else:
                workflow.status = WorkflowStatus.COMPLETED

            workflow.completed_at = datetime.now().isoformat()
            workflow.results = step_results

            if progress_callback:
                await progress_callback(100, "Workflow tamamlandı")

            return {
                "success": workflow.status == WorkflowStatus.COMPLETED,
                "workflow_id": workflow.id,
                "name": workflow.name,
                "status": workflow.status.value,
                "steps_completed": len(completed_steps),
                "steps_failed": len(failed_steps),
                "total_steps": len(workflow.steps),
                "results": step_results,
                "started_at": workflow.started_at,
                "completed_at": workflow.completed_at
            }

        except Exception as e:
            logger.error(f"Workflow execution error: {e}")
            workflow.status = WorkflowStatus.FAILED
            workflow.error = str(e)
            workflow.completed_at = datetime.now().isoformat()

            return {
                "success": False,
                "workflow_id": workflow.id,
                "error": str(e)
            }

    async def _execute_step(
        self,
        step: WorkflowStep,
        previous_results: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute a single workflow step"""
        logger.info(f"Executing step: {step.name} ({step.step_type.value})")

        # Resolve references to previous step results
        params = self._resolve_params(step.params, previous_results)

        if step.step_type == StepType.RESEARCH:
            return await self._execute_research(params)

        elif step.step_type == StepType.DOCUMENT:
            return await self._execute_document(params, previous_results)

        elif step.step_type == StepType.VISUALIZATION:
            return await self._execute_visualization(params, previous_results)

        elif step.step_type == StepType.NOTIFICATION:
            return await self._execute_notification(params)

        elif step.step_type == StepType.FILE_OPERATION:
            return await self._execute_file_operation(params)

        elif step.step_type == StepType.CUSTOM:
            return {"success": True, "message": "Custom step executed"}

        return {"success": False, "error": "Unknown step type"}

    def _resolve_params(
        self,
        params: Dict[str, Any],
        previous_results: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Resolve parameter references to previous step results"""
        resolved = {}

        for key, value in params.items():
            if isinstance(value, str) and value.endswith("_from") and value[:-5] in previous_results:
                # Reference to previous step result
                ref_step = value[:-5]
                resolved[key.replace("_from", "")] = previous_results.get(ref_step, {})
            elif key.endswith("_from"):
                # Direct reference
                ref_step = value
                resolved_key = key.replace("_from", "_data")
                resolved[resolved_key] = previous_results.get(ref_step, {})
            else:
                resolved[key] = value

        return resolved

    async def _execute_research(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute research step"""
        try:
            from tools.research_tools import deep_research
            return await deep_research(
                topic=params.get("topic", ""),
                depth=params.get("depth", "standard"),
                language=params.get("language", "tr"),
                focus_areas=params.get("focus_areas"),
                include_academic=params.get("include_academic", True)
            )
        except Exception as e:
            logger.error(f"Research step error: {e}")
            return {"success": False, "error": str(e)}

    async def _execute_document(
        self,
        params: Dict[str, Any],
        previous_results: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute document generation step"""
        try:
            from tools.document_generator import generate_research_document

            # Get research data from previous step
            research_data = params.get("research_data_data") or previous_results.get("research", {})

            return await generate_research_document(
                research_data=research_data,
                format=params.get("format", "docx"),
                template=params.get("template", "research_report"),
                custom_title=params.get("custom_title"),
                language=params.get("language", "tr")
            )
        except Exception as e:
            logger.error(f"Document step error: {e}")
            return {"success": False, "error": str(e)}

    async def _execute_visualization(
        self,
        params: Dict[str, Any],
        previous_results: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute visualization step"""
        try:
            from tools.visualization import create_research_visualization

            # Get research data from previous step
            research_data = params.get("research_data_data") or previous_results.get("research", {})

            return await create_research_visualization(research_data)
        except Exception as e:
            logger.error(f"Visualization step error: {e}")
            return {"success": False, "error": str(e)}

    async def _execute_notification(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute notification step"""
        try:
            from tools import AVAILABLE_TOOLS
            send_notification = AVAILABLE_TOOLS.get("send_notification")
            if send_notification:
                return await send_notification(
                    title=params.get("title", "Bildirim"),
                    message=params.get("message", "")
                )
            return {"success": True, "message": "Notification sent (simulated)"}
        except Exception as e:
            logger.error(f"Notification step error: {e}")
            return {"success": False, "error": str(e)}

    async def _execute_file_operation(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute file operation step"""
        try:
            from tools import AVAILABLE_TOOLS
            operation = params.get("operation", "write_file")
            tool = AVAILABLE_TOOLS.get(operation)
            if tool:
                return await tool(**params)
            return {"success": False, "error": f"Unknown operation: {operation}"}
        except Exception as e:
            logger.error(f"File operation step error: {e}")
            return {"success": False, "error": str(e)}

    def get_workflow_status(self, workflow_id: str) -> Dict[str, Any]:
        """Get workflow status"""
        workflow = self.active_workflows.get(workflow_id)
        if not workflow:
            return {"success": False, "error": "Workflow bulunamadı"}

        step_statuses = []
        for step in workflow.steps:
            step_statuses.append({
                "id": step.id,
                "name": step.name,
                "type": step.step_type.value,
                "status": step.status.value,
                "error": step.error
            })

        return {
            "success": True,
            "workflow_id": workflow.id,
            "name": workflow.name,
            "status": workflow.status.value,
            "steps": step_statuses,
            "created_at": workflow.created_at,
            "started_at": workflow.started_at,
            "completed_at": workflow.completed_at
        }

    def cancel_workflow(self, workflow_id: str) -> Dict[str, Any]:
        """Cancel a workflow"""
        workflow = self.active_workflows.get(workflow_id)
        if not workflow:
            return {"success": False, "error": "Workflow bulunamadı"}

        if workflow.status == WorkflowStatus.RUNNING:
            workflow.status = WorkflowStatus.CANCELLED
            workflow.completed_at = datetime.now().isoformat()
            return {"success": True, "message": "Workflow iptal edildi"}

        return {"success": False, "error": "Workflow çalışmıyor"}

    def list_workflows(
        self,
        include_completed: bool = False
    ) -> List[Dict[str, Any]]:
        """List all workflows"""
        workflows = []
        for workflow in self.active_workflows.values():
            if not include_completed and workflow.status == WorkflowStatus.COMPLETED:
                continue

            workflows.append({
                "id": workflow.id,
                "name": workflow.name,
                "status": workflow.status.value,
                "steps": len(workflow.steps),
                "created_at": workflow.created_at
            })

        return workflows


# Singleton instance
_executor_instance = None


def get_comprehensive_executor() -> ComprehensiveExecutor:
    """Get or create comprehensive executor instance"""
    global _executor_instance
    if _executor_instance is None:
        _executor_instance = ComprehensiveExecutor()
    return _executor_instance


async def run_research_workflow(
    topic: str,
    depth: str = "comprehensive",
    include_document: bool = True,
    include_visualization: bool = True,
    document_format: str = "docx",
    language: str = "tr"
) -> Dict[str, Any]:
    """
    Run a complete research workflow

    Args:
        topic: Research topic
        depth: Research depth
        include_document: Generate document
        include_visualization: Create visualizations
        document_format: Output format
        language: Language

    Returns:
        Workflow results
    """
    executor = get_comprehensive_executor()
    workflow = executor.create_research_workflow(
        topic=topic,
        depth=depth,
        include_document=include_document,
        include_visualization=include_visualization,
        document_format=document_format,
        language=language
    )
    return await executor.execute_workflow(workflow)
