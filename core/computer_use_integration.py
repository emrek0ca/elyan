"""Computer Use Tool Integration with ControlPlane

Bridges Computer Use Tool with main agent execution loop.
Handles routing, task scheduling, and approval workflow.
"""

import asyncio
from typing import Optional, Dict, Any
from dataclasses import dataclass

from core.observability.logger import get_structured_logger
from core.accuracy_speed_runtime import get_accuracy_speed_runtime
from elyan.computer_use.engine import get_computer_use_engine

slog = get_structured_logger("computer_use_integration")


@dataclass
class ComputerUseRequest:
    """Request to execute a computer use task"""
    user_intent: str
    approval_level: str = "CONFIRM"
    session_id: Optional[str] = None
    task_id: Optional[str] = None
    timeout_seconds: int = 300


@dataclass
class ComputerUseResult:
    """Result from computer use task execution"""
    success: bool
    task_id: str
    status: str  # completed, failed, cancelled, max_steps_reached
    steps_executed: int
    evidence_dir: Optional[str] = None
    error: Optional[str] = None
    result: Optional[str] = None
    terminal_reason: Optional[str] = None
    retry_count: int = 0
    fallback_used: bool = False


class ComputerUseIntegration:
    """Integrates Computer Use Tool with ControlPlane"""

    def __init__(self):
        """Initialize Computer Use integration"""
        self.tool = get_computer_use_engine()
        self.runtime = get_accuracy_speed_runtime()
        self._active_tasks: Dict[str, Dict[str, Any]] = {}

        slog.log_event("computer_use_integration_init", {
            "max_steps": self.tool.max_steps
        })

    async def execute_task(
        self,
        request: ComputerUseRequest,
        initial_screenshot: Optional[bytes] = None
    ) -> ComputerUseResult:
        """
        Execute a computer use task via ControlPlane

        Args:
            request: ComputerUseRequest with intent and approval level
            initial_screenshot: Optional initial screenshot bytes

        Returns:
            ComputerUseResult with execution status and evidence
        """
        try:
            # Track task in active tasks
            task_id = request.task_id or f"task_{int(__import__('time').time())}"
            session_id = request.session_id or f"session_{task_id}"

            self._active_tasks[task_id] = {
                "status": "pending",
                "intent": request.user_intent,
                "approval_level": request.approval_level,
                "created_at": __import__('time').time(),
                "session_id": session_id,
                "timeout_seconds": int(request.timeout_seconds or 300),
                "fallback_active": False,
            }

            slog.log_event("computer_use_task_started", {
                "task_id": task_id,
                "intent": request.user_intent[:50],
                "approval_level": request.approval_level,
                "session_id": session_id
            })

            # Execute via tool
            task_result = await asyncio.wait_for(
                self.tool.execute_task(
                    user_intent=request.user_intent,
                    initial_screenshot=initial_screenshot,
                    session_id=session_id,
                    approval_level=request.approval_level
                ),
                timeout=max(10, int(request.timeout_seconds or 300)),
            )

            # Update active tasks
            self._active_tasks[task_id]["status"] = task_result.get("status", "failed")
            self._active_tasks[task_id]["completed_at"] = __import__('time').time()
            self._active_tasks[task_id]["terminal_reason"] = task_result.get("terminal_reason")
            self._active_tasks[task_id]["fallback_active"] = bool(task_result.get("fallback_used"))

            # Map tool result to integration result
            result = ComputerUseResult(
                success=task_result.get("status") == "completed",
                task_id=task_id,
                status=task_result.get("status", "failed"),
                steps_executed=len(task_result.get("steps", [])),
                evidence_dir=task_result.get("evidence_dir"),
                error=task_result.get("error"),
                result=task_result.get("result"),
                terminal_reason=task_result.get("terminal_reason"),
                retry_count=int(task_result.get("retry_count", 0) or 0),
                fallback_used=bool(task_result.get("fallback_used")),
            )
            self.runtime.record_execution(
                lane="vision_lane",
                latency_ms=float((task_result.get("completed_at") or 0.0) - float(task_result.get("created_at") or task_result.get("completed_at") or 0.0)) * 1000.0,
                success=bool(result.success),
                fallback_active=bool(result.fallback_used),
                verification_state="strong",
            )

            slog.log_event("computer_use_task_completed", {
                "task_id": task_id,
                "success": result.success,
                "status": result.status,
                "steps": result.steps_executed
            })

            return result

        except asyncio.TimeoutError:
            self._active_tasks[request.task_id or "unknown"] = {
                "status": "failed",
                "intent": request.user_intent,
                "approval_level": request.approval_level,
                "session_id": request.session_id,
                "completed_at": __import__("time").time(),
                "terminal_reason": "failed:integration_timeout",
                "fallback_active": False,
            }
            return ComputerUseResult(
                success=False,
                task_id=request.task_id or "unknown",
                status="failed",
                steps_executed=0,
                error="integration_timeout",
                terminal_reason="failed:integration_timeout",
            )
        except Exception as e:
            slog.log_event("computer_use_integration_error", {
                "task_id": request.task_id,
                "error": str(e)
            }, level="error")

            return ComputerUseResult(
                success=False,
                task_id=request.task_id or "unknown",
                status="failed",
                steps_executed=0,
                error=str(e),
                terminal_reason="failed:integration_exception",
            )

    async def get_task_status(self, task_id: str) -> Dict[str, Any]:
        """Get status of active computer use task"""
        if task_id not in self._active_tasks:
            return {"error": f"Task {task_id} not found"}

        task = self._active_tasks[task_id]
        return {
            "task_id": task_id,
            "status": task.get("status"),
            "intent": task.get("intent"),
            "approval_level": task.get("approval_level"),
            "created_at": task.get("created_at"),
            "completed_at": task.get("completed_at"),
            "session_id": task.get("session_id"),
            "terminal_reason": task.get("terminal_reason"),
            "fallback_active": bool(task.get("fallback_active")),
        }

    async def list_active_tasks(self, limit: int = 20) -> Dict[str, Any]:
        """List active computer use tasks"""
        tasks = list(self._active_tasks.items())[-limit:]
        return {
            "tasks": [
                {
                    "task_id": task_id,
                    "status": task.get("status"),
                    "intent": task.get("intent")[:50],
                    "created_at": task.get("created_at"),
                    "fallback_active": bool(task.get("fallback_active")),
                }
                for task_id, task in tasks
            ],
            "total": len(self._active_tasks)
        }

    async def cancel_task(self, task_id: str) -> bool:
        """Cancel an active computer use task (best-effort)"""
        if task_id in self._active_tasks:
            self._active_tasks[task_id]["status"] = "cancelled"
            slog.log_event("computer_use_task_cancelled", {"task_id": task_id})
            return True
        return False

    def should_route_to_computer_use(self, action_type: str) -> bool:
        """Determine if action should be routed to Computer Use Tool"""
        computer_use_actions = {
            "computer_use",
            "screen_control",
            "ui_automation",
            "visual_task"
        }
        return action_type.lower() in computer_use_actions

    async def get_health_status(self) -> Dict[str, Any]:
        tool_health = await self.tool.get_health_status()
        active = [
            {"task_id": task_id, "status": row.get("status"), "session_id": row.get("session_id")}
            for task_id, row in list(self._active_tasks.items())[-10:]
        ]
        return {
            "status": str(tool_health.get("status") or "degraded"),
            "ready": bool(tool_health.get("ready")),
            "fallback_active": bool(tool_health.get("fallback_active")),
            "current_lane": "vision_lane",
            "verification_state": "strong",
            "average_latency_bucket": self.runtime.get_status().get("average_latency_bucket"),
            "active_tasks": active,
            "active_task_count": len(self._active_tasks),
            "components": dict(tool_health.get("components") or {}),
            "timeout_budget_s": tool_health.get("timeout_budget_s"),
            "max_retries": tool_health.get("max_retries"),
            "last_successful_run": tool_health.get("last_successful_run"),
        }


# Singleton instance
_integration: Optional[ComputerUseIntegration] = None


def get_computer_use_integration() -> ComputerUseIntegration:
    """Get or create ComputerUseIntegration singleton"""
    global _integration
    if _integration is None:
        _integration = ComputerUseIntegration()
    return _integration
