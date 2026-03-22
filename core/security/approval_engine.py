import asyncio
import uuid
import time
from typing import Any, Dict, List, Optional, Callable
from core.protocol.shared_types import RiskLevel
from core.observability.logger import get_structured_logger

slog = get_structured_logger("approval_engine")

class ApprovalRequest:
    def __init__(
        self, 
        request_id: str,
        session_id: str,
        run_id: str,
        action_type: str,
        payload: Dict[str, Any],
        risk_level: RiskLevel,
        reason: str
    ):
        self.request_id = request_id
        self.session_id = session_id
        self.run_id = run_id
        self.action_type = action_type
        self.payload = payload
        self.risk_level = risk_level
        self.reason = reason
        self.status = "pending"
        self.created_at = time.time()
        self.future = asyncio.get_event_loop().create_future()

class ApprovalEngine:
    """
    Manages pending human approval requests for sensitive actions.
    """
    def __init__(self):
        self._pending: Dict[str, ApprovalRequest] = {}

    async def request_approval(
        self, 
        session_id: str, 
        run_id: str, 
        action_type: str, 
        payload: Dict[str, Any], 
        risk_level: RiskLevel,
        reason: str
    ) -> bool:
        """
        Creates a new approval request and waits for resolution.
        """
        request_id = f"appr_{uuid.uuid4().hex[:8]}"
        request = ApprovalRequest(request_id, session_id, run_id, action_type, payload, risk_level, reason)
        self._pending[request_id] = request
        
        slog.log_event("approval_requested", {
            "request_id": request_id,
            "action": action_type,
            "risk": risk_level.value,
            "reason": reason
        }, session_id=session_id, run_id=run_id)

        # Notify via Gateway (This would call a broadcast method in v2)
        # For now, we assume the UI or Channel will poll or receive this via event
        
        try:
            # Wait for user input (timeout after 10 mins)
            approved = await asyncio.wait_for(request.future, timeout=600.0)
            return approved
        except asyncio.TimeoutError:
            slog.log_event("approval_timeout", {"request_id": request_id}, level="warning", session_id=session_id, run_id=run_id)
            return False
        finally:
            self._pending.pop(request_id, None)

    def resolve_approval(self, request_id: str, approved: bool, resolver_id: str):
        """Called when a user approves/denies via UI or Channel."""
        request = self._pending.get(request_id)
        if request:
            request.status = "approved" if approved else "denied"
            if not request.future.done():
                request.future.set_result(approved)
            slog.log_event("approval_resolved", {
                "request_id": request_id, 
                "approved": approved,
                "resolver": resolver_id
            }, session_id=request.session_id, run_id=request.run_id)

# Global instance
approval_engine = ApprovalEngine()
