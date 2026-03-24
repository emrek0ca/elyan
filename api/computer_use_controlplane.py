"""Computer Use ControlPlane REST API

Provides HTTP endpoints for Computer Use task management and integration.
"""

from typing import Dict, Any, Optional
from core.computer_use_integration import (
    get_computer_use_integration,
    ComputerUseRequest
)
from core.observability.logger import get_structured_logger

slog = get_structured_logger("computer_use_api")


class ComputerUseControlPlaneAPI:
    """REST API for Computer Use ControlPlane integration"""

    def __init__(self):
        """Initialize API"""
        self.integration = get_computer_use_integration()

    async def start_task(
        self,
        user_intent: str,
        approval_level: str = "CONFIRM",
        session_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Start a Computer Use task

        POST /api/v1/computer_use/controlplane/tasks

        Args:
            user_intent: Task description (e.g., "Open Chrome and read Elon's tweet")
            approval_level: CONFIRM, SCREEN, TWO_FA, AUTO
            session_id: Session identifier for context

        Returns:
            {
                "task_id": "task_...",
                "status": "pending",
                "session_id": "...",
                "created_at": 1234567890.0
            }
        """
        try:
            request = ComputerUseRequest(
                user_intent=user_intent,
                approval_level=approval_level,
                session_id=session_id
            )

            # Note: execute_task is async, caller should handle in async context
            # For now, return pending response immediately
            result = {
                "task_id": f"task_{int(__import__('time').time())}",
                "status": "pending",
                "user_intent": user_intent,
                "approval_level": approval_level,
                "session_id": session_id or "unknown",
                "created_at": __import__('time').time()
            }

            slog.log_event("computer_use_task_started_via_api", {
                "task_id": result["task_id"],
                "intent": user_intent[:50],
                "approval_level": approval_level
            })

            return result

        except Exception as e:
            slog.log_event("computer_use_start_error", {
                "error": str(e)
            }, level="error")

            return {
                "success": False,
                "error": str(e)
            }

    async def get_task_status(self, task_id: str) -> Dict[str, Any]:
        """
        Get Computer Use task status

        GET /api/v1/computer_use/controlplane/tasks/{task_id}

        Returns:
            {
                "task_id": "...",
                "status": "running|completed|failed|cancelled",
                "session_id": "...",
                "created_at": ...,
                "completed_at": ...,
                "steps_executed": 5
            }
        """
        try:
            status = await self.integration.get_task_status(task_id)
            return status

        except Exception as e:
            slog.log_event("computer_use_status_error", {
                "task_id": task_id,
                "error": str(e)
            }, level="error")

            return {
                "success": False,
                "error": str(e)
            }

    async def list_tasks(self, limit: int = 20) -> Dict[str, Any]:
        """
        List Computer Use tasks

        GET /api/v1/computer_use/controlplane/tasks?limit=20

        Returns:
            {
                "tasks": [...],
                "total": 42
            }
        """
        try:
            result = await self.integration.list_active_tasks(limit=limit)
            return {
                "success": True,
                **result
            }

        except Exception as e:
            slog.log_event("computer_use_list_error", {
                "error": str(e)
            }, level="error")

            return {
                "success": False,
                "error": str(e)
            }

    async def cancel_task(self, task_id: str) -> Dict[str, Any]:
        """
        Cancel a Computer Use task

        POST /api/v1/computer_use/controlplane/tasks/{task_id}/cancel

        Returns:
            {"success": true, "task_id": "...", "status": "cancelled"}
        """
        try:
            success = await self.integration.cancel_task(task_id)

            if success:
                slog.log_event("computer_use_task_cancelled_via_api", {
                    "task_id": task_id
                })

                return {
                    "success": True,
                    "task_id": task_id,
                    "status": "cancelled"
                }
            else:
                return {
                    "success": False,
                    "error": f"Task {task_id} not found"
                }

        except Exception as e:
            slog.log_event("computer_use_cancel_error", {
                "task_id": task_id,
                "error": str(e)
            }, level="error")

            return {
                "success": False,
                "error": str(e)
            }

    def should_route(self, action_type: str) -> bool:
        """Check if action should be routed to Computer Use"""
        return self.integration.should_route_to_computer_use(action_type)


# Singleton instance
_api: Optional[ComputerUseControlPlaneAPI] = None


def get_computer_use_controlplane_api() -> ComputerUseControlPlaneAPI:
    """Get or create ComputerUseControlPlaneAPI singleton"""
    global _api
    if _api is None:
        _api = ComputerUseControlPlaneAPI()
    return _api
