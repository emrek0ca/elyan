"""
Workflow Automation - Automated task execution and orchestration
"""

import logging
from typing import Dict, List, Optional, Callable
from enum import Enum
from datetime import datetime

logger = logging.getLogger(__name__)


class WorkflowStatus(Enum):
    """Workflow status"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class WorkflowAutomation:
    """Automates workflows"""

    def __init__(self):
        self.workflows: Dict[str, Dict] = {}
        self.execution_history: List[Dict] = []
        self.task_handlers: Dict[str, Callable] = {}

    def create_workflow(self, workflow_id: str, name: str, tasks: List[Dict]) -> str:
        """Create workflow"""
        self.workflows[workflow_id] = {
            "id": workflow_id,
            "name": name,
            "tasks": tasks,
            "created_at": datetime.now().isoformat(),
            "status": WorkflowStatus.PENDING.value
        }
        logger.info(f"Workflow created: {workflow_id}")
        return workflow_id

    def execute_workflow(self, workflow_id: str) -> Dict:
        """Execute workflow"""
        if workflow_id not in self.workflows:
            return {"error": "Workflow not found"}

        workflow = self.workflows[workflow_id]
        workflow["status"] = WorkflowStatus.RUNNING.value

        results = []
        for task in workflow.get("tasks", []):
            task_result = self._execute_task(task)
            results.append(task_result)

            if not task_result.get("success"):
                workflow["status"] = WorkflowStatus.FAILED.value
                break
        else:
            workflow["status"] = WorkflowStatus.COMPLETED.value

        execution_record = {
            "workflow_id": workflow_id,
            "executed_at": datetime.now().isoformat(),
            "results": results,
            "status": workflow["status"]
        }
        self.execution_history.append(execution_record)

        return execution_record

    def _execute_task(self, task: Dict) -> Dict:
        """Execute single task"""
        task_type = task.get("type", "generic")
        task_name = task.get("name", "unknown")

        # Execute task
        if task_type in self.task_handlers:
            try:
                result = self.task_handlers[task_type](task.get("params", {}))
                return {"task": task_name, "success": True, "result": result}
            except Exception as e:
                return {"task": task_name, "success": False, "error": str(e)}

        return {"task": task_name, "success": True, "result": "Task executed"}

    def register_task_handler(self, task_type: str, handler: Callable):
        """Register task handler"""
        self.task_handlers[task_type] = handler

    def get_workflow_status(self, workflow_id: str) -> Dict:
        """Get workflow status"""
        if workflow_id not in self.workflows:
            return {"error": "Not found"}

        workflow = self.workflows[workflow_id]
        recent_executions = [e for e in self.execution_history if e["workflow_id"] == workflow_id]

        return {
            "id": workflow_id,
            "name": workflow["name"],
            "status": workflow["status"],
            "task_count": len(workflow.get("tasks", [])),
            "executions": len(recent_executions)
        }

    def schedule_workflow(self, workflow_id: str, schedule: str) -> Dict:
        """Schedule workflow execution"""
        if workflow_id not in self.workflows:
            return {"error": "Workflow not found"}

        return {
            "workflow_id": workflow_id,
            "schedule": schedule,
            "scheduled_at": datetime.now().isoformat()
        }

    def get_execution_history(self, limit: int = 10) -> List[Dict]:
        """Get execution history"""
        return self.execution_history[-limit:]
