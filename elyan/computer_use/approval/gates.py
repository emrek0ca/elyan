"""Computer Use Approval Gates

Orchestrates approval workflow for Computer Use actions using ApprovalEngine.
"""

import time
from typing import Optional, Dict, Any
from dataclasses import dataclass

from core.observability.logger import get_structured_logger
from core.security.approval_engine import get_approval_engine
from elyan.computer_use.tool import ComputerAction
from elyan.computer_use.approval.risk_mapping import (
    get_action_risk_level,
    should_require_approval
)

slog = get_structured_logger("computer_use_approval")


@dataclass
class ApprovalGateResult:
    """Result of approval gate evaluation"""
    approved: bool
    request_id: Optional[str] = None
    reason: str = ""
    timestamp: float = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = time.time()


class ComputerUseApprovalGate:
    """
    Multi-level approval gate for Computer Use actions.

    Approval levels:
    - AUTO: Only critical actions need approval
    - CONFIRM: Destructive actions need approval (confirmation)
    - SCREEN: Sensitive writes need approval (with screenshot)
    - TWO_FA: All writes need approval (stringent)
    """

    def __init__(
        self,
        session_id: str,
        run_id: str,
        approval_level: str = "CONFIRM"
    ):
        """
        Initialize approval gate.

        Args:
            session_id: Session identifier
            run_id: Run identifier
            approval_level: Approval gating level (AUTO/CONFIRM/SCREEN/TWO_FA)
        """
        self.session_id = session_id
        self.run_id = run_id
        self.approval_level = approval_level
        self.approval_engine = get_approval_engine()

        slog.log_event("approval_gate_init", {
            "session_id": session_id,
            "run_id": run_id,
            "approval_level": approval_level
        })

    async def evaluate_action(
        self,
        action: ComputerAction,
        task_context: str,
        screenshot_bytes: Optional[bytes] = None
    ) -> ApprovalGateResult:
        """
        Evaluate whether action requires approval and get approval if needed.

        Args:
            action: Computer use action to evaluate
            task_context: User intent/task description for context
            screenshot_bytes: Current screenshot for SCREEN-level approval

        Returns:
            ApprovalGateResult with approval status
        """
        # Check if action requires approval
        if not should_require_approval(action.action_type, self.approval_level):
            return ApprovalGateResult(
                approved=True,
                reason="Action does not require approval under current level"
            )

        # Get risk level and reason
        risk_level, risk_reason = get_action_risk_level(action.action_type)

        # Build approval payload
        payload = {
            "action_type": action.action_type,
            "task_context": task_context,
            "risk_reason": risk_reason,
        }

        # Add action-specific details
        if action.x is not None and action.y is not None:
            payload["position"] = {"x": action.x, "y": action.y}
        if action.text is not None:
            # Don't leak sensitive text in logs
            text_preview = action.text[:50] if len(action.text) <= 50 else action.text[:47] + "..."
            payload["text"] = text_preview
        if action.key_combination:
            payload["keys"] = action.key_combination

        # Build approval reason
        approval_reason = f"{action.action_type}: {risk_reason} [Task: {task_context[:30]}...]"

        try:
            # Request approval from ApprovalEngine
            approved = await self.approval_engine.request_approval(
                session_id=self.session_id,
                run_id=self.run_id,
                action_type=f"computer_use.{action.action_type}",
                payload=payload,
                risk_level=risk_level,
                reason=approval_reason
            )

            slog.log_event("action_approval_resolved", {
                "action_type": action.action_type,
                "approved": approved,
                "session_id": self.session_id
            })

            return ApprovalGateResult(
                approved=approved,
                reason="User " + ("approved" if approved else "denied") + " action"
            )

        except Exception as e:
            slog.log_event("approval_gate_error", {
                "action_type": action.action_type,
                "error": str(e)
            }, level="error")

            # On error: deny the action (fail-safe)
            return ApprovalGateResult(
                approved=False,
                reason=f"Approval process error: {str(e)}"
            )


class ApprovalGateFactory:
    """Factory for creating approval gates"""

    _instance: Optional[ComputerUseApprovalGate] = None

    @staticmethod
    def create_gate(
        session_id: str,
        run_id: str,
        approval_level: str = "CONFIRM"
    ) -> ComputerUseApprovalGate:
        """Create a new approval gate instance"""
        return ComputerUseApprovalGate(
            session_id=session_id,
            run_id=run_id,
            approval_level=approval_level
        )

    @staticmethod
    def get_gate(
        session_id: str,
        run_id: str,
        approval_level: str = "CONFIRM"
    ) -> ComputerUseApprovalGate:
        """Get or create singleton gate for session/run"""
        # For now, create new instance per call
        # In production, could cache by (session_id, run_id)
        return ApprovalGateFactory.create_gate(
            session_id=session_id,
            run_id=run_id,
            approval_level=approval_level
        )
