"""Computer Use API Endpoints

REST API for computer use tasks:
- Task execution
- Task status
- Evidence retrieval
- Approval workflow integration
"""

from typing import Dict, Any, Optional
import asyncio

from core.observability.logger import get_structured_logger

slog = get_structured_logger("computer_use_api")


class ComputerUseAPI:
    """Computer Use REST API endpoints"""

    def __init__(self):
        """Initialize API"""
        self.running_tasks = {}  # task_id -> task state

    async def start_task(
        self,
        user_intent: str,
        approval_level: str = "CONFIRM",
        timeout_seconds: int = 300
    ) -> Dict[str, Any]:
        """
        Start a computer use task

        POST /api/v1/computer_use/tasks

        Args:
            user_intent: Task description (e.g., "Chrome açılır, x.com'a gidilir")
            approval_level: CONFIRM, SCREEN, TWO_FA
            timeout_seconds: Maximum execution time

        Returns:
            {"task_id": "task_...", "status": "pending", "created_at": ...}
        """
        try:
            from elyan.computer_use.tool import get_computer_use_tool

            tool = get_computer_use_tool()
            task_id = f"task_{int(__import__('time').time())}"

            # Store task reference
            self.running_tasks[task_id] = {
                "status": "pending",
                "intent": user_intent,
                "approval_level": approval_level,
                "created_at": __import__('time').time()
            }

            slog.log_event("computer_use_task_started", {
                "task_id": task_id,
                "intent": user_intent[:50],
                "approval_level": approval_level
            })

            return {
                "success": True,
                "task_id": task_id,
                "status": "pending",
                "created_at": self.running_tasks[task_id]["created_at"]
            }

        except Exception as e:
            slog.log_event("task_start_error", {
                "error": str(e)
            }, level="error")

            return {
                "success": False,
                "error": str(e)
            }

    async def get_task_status(self, task_id: str) -> Dict[str, Any]:
        """
        Get task status

        GET /api/v1/computer_use/tasks/{task_id}

        Returns:
            {"task_id": "...", "status": "running|completed|failed", ...}
        """
        try:
            if task_id not in self.running_tasks:
                return {
                    "success": False,
                    "error": f"Task {task_id} not found"
                }

            task = self.running_tasks[task_id]

            return {
                "success": True,
                "task_id": task_id,
                "status": task.get("status"),
                "intent": task.get("intent"),
                "created_at": task.get("created_at"),
                "completed_at": task.get("completed_at"),
                "steps": task.get("steps", 0),
                "error": task.get("error")
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    async def get_task_evidence(self, task_id: str) -> Dict[str, Any]:
        """
        Get task evidence (screenshots, action trace, etc)

        GET /api/v1/computer_use/tasks/{task_id}/evidence

        Returns:
            {
                "task_id": "...",
                "evidence_dir": "path/to/evidence",
                "screenshots": ["ss_0.png", "ss_1.png", ...],
                "action_count": 7,
                "metadata": {...}
            }
        """
        try:
            from elyan.computer_use.evidence.recorder import get_evidence_recorder

            recorder = await get_evidence_recorder()
            evidence = await recorder.get_task_evidence(task_id)

            return evidence

        except Exception as e:
            slog.log_event("evidence_retrieval_error", {
                "task_id": task_id,
                "error": str(e)
            }, level="error")

            return {
                "success": False,
                "error": str(e)
            }

    async def list_tasks(
        self,
        status: Optional[str] = None,
        limit: int = 20
    ) -> Dict[str, Any]:
        """
        List computer use tasks

        GET /api/v1/computer_use/tasks?status=completed&limit=20

        Returns:
            {"tasks": [...], "total": 7}
        """
        try:
            tasks = []
            for task_id, task in list(self.running_tasks.items())[-limit:]:
                if status and task.get("status") != status:
                    continue

                tasks.append({
                    "task_id": task_id,
                    "intent": task.get("intent")[:50],
                    "status": task.get("status"),
                    "created_at": task.get("created_at"),
                    "completed_at": task.get("completed_at")
                })

            return {
                "success": True,
                "tasks": tasks,
                "total": len(tasks)
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }


# ============================================================================
# SINGLETON
# ============================================================================

_api: Optional[ComputerUseAPI] = None


def get_computer_use_api() -> ComputerUseAPI:
    """Get or create ComputerUseAPI singleton"""
    global _api
    if _api is None:
        _api = ComputerUseAPI()
    return _api
