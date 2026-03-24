"""Computer Use Approval System

Multi-level approval gating for Computer Use actions.
Integrates with ApprovalEngine for human-in-the-loop control.
"""

from elyan.computer_use.approval.risk_mapping import (
    ActionRiskLevel,
    ACTION_RISK_MAP,
    get_action_risk_level,
    should_require_approval,
)
from elyan.computer_use.approval.gates import (
    ComputerUseApprovalGate,
    ApprovalGateResult,
    ApprovalGateFactory,
)

__all__ = [
    "ActionRiskLevel",
    "ACTION_RISK_MAP",
    "get_action_risk_level",
    "should_require_approval",
    "ComputerUseApprovalGate",
    "ApprovalGateResult",
    "ApprovalGateFactory",
]
