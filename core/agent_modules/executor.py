"""
Agent Executor — Tool execution and orchestration module.

Handles: tool dispatch, error recovery, parallel execution, timeout management.
"""

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from core.agent import Agent

logger = logging.getLogger(__name__)


class AgentExecutor:
    """
    Executes planned tasks using available tools.

    Responsibilities:
    - Dispatch tools from plan steps
    - Handle errors with recovery strategies
    - Support parallel execution where possible
    - Track execution metrics
    """

    def __init__(self, agent: "Agent"):
        self.agent = agent
        self.max_parallel = 3
        self.default_timeout = 30.0

    async def execute_plan(
        self,
        plan: Dict[str, Any],
        user_id: str = "local",
    ) -> Dict[str, Any]:
        """
        Execute a multi-step plan.

        Returns execution result with step outcomes.
        """
        steps = plan.get("steps", [])
        if not steps:
            return {"success": False, "error": "Empty plan", "results": []}

        results = []
        completed_ids = set()

        for step in steps:
            step_id = step.get("id", "unknown")
            depends_on = step.get("depends_on", [])

            # Check dependencies
            unmet = [d for d in depends_on if d not in completed_ids]
            if unmet:
                results.append({
                    "step_id": step_id,
                    "success": False,
                    "error": f"Unmet dependencies: {unmet}",
                })
                continue

            # Execute step
            result = await self._execute_step(step, user_id)
            results.append(result)

            if result.get("success"):
                completed_ids.add(step_id)
            elif not step.get("optional", False):
                # Critical step failed — try recovery
                recovery = await self._recover(step, result, user_id)
                if recovery.get("success"):
                    completed_ids.add(step_id)
                    results.append(recovery)
                else:
                    break  # Stop on unrecoverable failure

        all_success = all(r.get("success") for r in results)
        return {
            "success": all_success,
            "results": results,
            "completed_steps": len(completed_ids),
            "total_steps": len(steps),
        }

    async def _execute_step(
        self, step: Dict[str, Any], user_id: str
    ) -> Dict[str, Any]:
        """Execute a single plan step."""
        action = step.get("action", "")
        params = step.get("params", {})
        step_id = step.get("id", "unknown")

        t0 = time.perf_counter()
        try:
            result = await self.agent._execute_tool(action, params, user_id=user_id)
            duration = (time.perf_counter() - t0) * 1000

            success = False
            if isinstance(result, dict):
                success = result.get("success", True)
            elif isinstance(result, str) and result:
                success = True

            return {
                "step_id": step_id,
                "action": action,
                "success": success,
                "result": result,
                "duration_ms": round(duration, 1),
            }
        except Exception as e:
            duration = (time.perf_counter() - t0) * 1000
            return {
                "step_id": step_id,
                "action": action,
                "success": False,
                "error": str(e),
                "duration_ms": round(duration, 1),
            }

    async def _recover(
        self,
        step: Dict[str, Any],
        failed_result: Dict[str, Any],
        user_id: str,
    ) -> Dict[str, Any]:
        """
        Attempt error recovery for a failed step.

        Strategies:
        1. Retry with same params
        2. Modify params (e.g., reduce scope)
        3. Use alternative tool
        """
        error = str(failed_result.get("error", ""))
        action = step.get("action", "")

        # Strategy 1: Simple retry
        logger.info(f"Recovery: retrying step {step.get('id')} after error: {error[:100]}")
        retry_result = await self._execute_step(step, user_id)
        if retry_result.get("success"):
            retry_result["recovery_strategy"] = "retry"
            return retry_result

        # Strategy 2: Retry with reduced params if timeout
        if "timeout" in error.lower():
            modified_step = dict(step)
            modified_params = dict(step.get("params", {}))
            modified_params["max_results"] = modified_params.get("max_results", 10) // 2
            modified_step["params"] = modified_params

            retry2 = await self._execute_step(modified_step, user_id)
            if retry2.get("success"):
                retry2["recovery_strategy"] = "modify_params"
                return retry2

        return {"success": False, "error": f"Recovery failed for {action}: {error}"}
