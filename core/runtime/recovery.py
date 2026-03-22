from typing import Any, Dict, List, Optional
from core.protocol.shared_types import RunStatus
from core.runtime.lifecycle import run_lifecycle_manager, RunError
from core.repair.rollback import rollback_engine
from core.observability.logger import get_structured_logger

slog = get_structured_logger("failure_recovery")

class RecoveryEngine:
    """
    Orchestrates high-level failure recovery for runs.
    Decides when to rollback, when to retry, and when to ask for human help.
    """
    async def attempt_recovery(self, session_id: str, run_id: str, error: RunError) -> bool:
        """
        Attempts to recover a failed run.
        Returns True if recovery was successful, False otherwise.
        """
        run = run_lifecycle_manager.get_run(run_id)
        if not run:
            return False

        slog.log_event("recovery_started", {"run_id": run_id, "error_code": error.code}, session_id=session_id, run_id=run_id)

        # 1. Classification
        if error.code == "action_failed":
            # Potentially retryable or needs rollback
            pass
        elif error.code == "policy_denied":
            # Not recoverable without human intervention
            return False

        # 2. Automated Rollback (if applicable)
        # In a real v2, we'd iterate through completed steps and rollback
        slog.log_event("automated_rollback_triggered", {"run_id": run_id}, session_id=session_id, run_id=run_id)
        
        # 3. Final Decision
        # For Phase 1/2, we just log and mark as unrecovered until more logic is added
        slog.log_event("recovery_failed", {"run_id": run_id, "reason": "unsupported_error_type"}, session_id=session_id, run_id=run_id)
        return False

# Global instance
recovery_engine = RecoveryEngine()
