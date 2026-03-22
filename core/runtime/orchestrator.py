import asyncio
from typing import Any, Dict, List, Optional
from core.protocol.shared_types import RunStatus, VerificationStatus
from core.runtime.lifecycle import run_lifecycle_manager, RunError
from core.runtime.execution_hub import RemoteExecutionHub
from core.policy_engine.engine import policy_engine, PolicyDecision
from core.verifier.engine import verification_engine
from core.observability.logger import get_structured_logger

slog = get_structured_logger("run_orchestrator")

class TaskOrchestrator:
    """
    Manages the high-level execution loop for a run:
    Planner -> Policy -> Executor -> Validator -> Result
    """
    def __init__(self, gateway_server):
        self.gateway = gateway_server
        self.execution_hub = gateway_server.execution_hub

    async def execute_run(self, session_id: str, run_id: str, goal: str):
        """
        Coordinates the multi-step execution of a task.
        """
        from core.runtime.checkpoints import checkpoint_manager, RunCheckpoint
        
        # Check for existing checkpoint to resume
        checkpoint = checkpoint_manager.load_checkpoint(run_id)
        start_step_idx = checkpoint.last_completed_step if checkpoint else 0
        
        run_lifecycle_manager.update_status(run_id, RunStatus.EXECUTING)
        slog.log_event("execution_started", {"goal": goal, "resuming": bool(checkpoint)}, session_id=session_id, run_id=run_id)

        try:
            # 1. Planning (Simplified for Phase 1/2)
            steps = [
                {"tool": "filesystem.list_directory", "params": {"path": "~"}},
                {"tool": "terminal.execute", "params": {"command": "echo 'Step 2 completed'"}},
                {"tool": "terminal.execute", "params": {"command": "echo 'Step 3 completed'"}}
            ]

            retry_budget = 3
            for idx, step in enumerate(steps):
                if idx < start_step_idx:
                    continue # Skip already completed steps
                    
                tool_name = step["tool"]
                params = step["params"]
                
                success_step = False
                attempts = 0
                
                while not success_step and attempts < retry_budget:
                    attempts += 1
                    try:
                        # 2. Policy Check
                        decision, reason = policy_engine.evaluate_action(
                            capability=tool_name.split(".")[0],
                            action=tool_name.split(".")[-1],
                            params=params,
                            risk_level=step.get("risk_level", RiskLevel.READ_ONLY)
                        )

                        if decision == PolicyDecision.DENY:
                            raise RuntimeError(f"Action denied by policy: {reason}")
                        
                        if decision == PolicyDecision.REQUIRE_APPROVAL:
                            run_lifecycle_manager.update_status(run_id, RunStatus.WAITING_FOR_APPROVAL)
                            from core.security.approval_engine import approval_engine
                            approved = await approval_engine.request_approval(
                                session_id=session_id,
                                run_id=run_id,
                                action_type=tool_name,
                                payload=params,
                                risk_level=step.get("risk_level", RiskLevel.WRITE_SENSITIVE),
                                reason=reason
                            )
                            
                            if not approved:
                                raise RuntimeError(f"Action denied by user: {reason}")
                            
                            run_lifecycle_manager.update_status(run_id, RunStatus.EXECUTING)

                        # 3. Execution
                        result = await self.execution_hub.execute_action(tool_name, params, session_id, run_id)
                        
                        # 4. Verification
                        verification = await verification_engine.verify_action(
                            capability=tool_name.split(".")[0],
                            action=tool_name.split(".")[-1],
                            params=params,
                            result=result
                        )

                        if verification["status"] == VerificationStatus.FAILED:
                            slog.log_event("verification_failed", {"tool": tool_name, "attempt": attempts, "reason": verification.get("reason")}, level="warning")
                            if attempts >= retry_budget:
                                raise RuntimeError(f"Step verification failed after {attempts} attempts: {verification.get('reason')}")
                            await asyncio.sleep(attempts * 2) # Exponential backoff
                            continue

                        success_step = True

                    except Exception as e:
                        slog.log_event("step_error", {"tool": tool_name, "attempt": attempts, "error": str(e)}, level="warning")
                        if attempts >= retry_budget:
                            raise e
                        await asyncio.sleep(attempts * 2)

            run_lifecycle_manager.update_status(run_id, RunStatus.COMPLETED)
            slog.log_event("execution_completed", {"success": True}, session_id=session_id, run_id=run_id)

        except Exception as e:
            logger.error(f"Run {run_id} failed: {e}")
            run_lifecycle_manager.update_status(
                run_id, 
                RunStatus.FAILED, 
                error=RunError(code="orchestration_error", message=str(e))
            )
            slog.log_event("execution_failed", {"error": str(e)}, level="error", session_id=session_id, run_id=run_id)

# Note: This will be used by the SessionManager instead of the legacy executor
