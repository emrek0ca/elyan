import asyncio
import uuid
import time
import json
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
        # Priority: CRITICAL=1 (highest), DESTRUCTIVE=2, WRITE_SENSITIVE=3, WRITE_SAFE=4, READ_ONLY=5 (lowest)
        self.priority = self._calculate_priority()

    def _calculate_priority(self) -> int:
        """Calculate priority based on risk level."""
        risk_str = self.risk_level.value if hasattr(self.risk_level, 'value') else str(self.risk_level)
        priority_map = {
            "system_critical": 1,
            "destructive": 2,
            "write_sensitive": 3,
            "write_safe": 4,
            "read_only": 5
        }
        return priority_map.get(risk_str, 5)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API serialization."""
        return {
            "request_id": self.request_id,
            "session_id": self.session_id,
            "run_id": self.run_id,
            "action_type": self.action_type,
            "payload": self.payload,
            "risk_level": self.risk_level.value if hasattr(self.risk_level, 'value') else str(self.risk_level),
            "reason": self.reason,
            "status": self.status,
            "created_at": self.created_at,
            "age_seconds": time.time() - self.created_at,
            "priority": self.priority
        }

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

        # Notify via HTTP + event channels
        await self._notify_pending(request)

        try:
            # Wait for user input (timeout after 10 mins)
            approved = await asyncio.wait_for(request.future, timeout=600.0)
            return approved
        except asyncio.TimeoutError:
            slog.log_event("approval_timeout", {"request_id": request_id}, level="warning", session_id=session_id, run_id=run_id)
            return False
        finally:
            self._pending.pop(request_id, None)

    async def _notify_pending(self, request: ApprovalRequest) -> None:
        """Notify web UI and channels about pending approval."""
        try:
            # Broadcast via event system (WebSocket + subscribers)
            from core.event_broadcaster import broadcast_approval_pending
            risk_level = request.risk_level.value if hasattr(request.risk_level, 'value') else str(request.risk_level)
            await broadcast_approval_pending(
                request_id=request.request_id,
                action_type=request.action_type,
                risk_level=risk_level,
                reason=request.reason
            )
        except Exception as e:
            slog.log_event("approval_notify_error", {
                "request_id": request.request_id,
                "error": str(e)
            }, level="warning")

    def get_pending_approvals(self, sorted_by_priority: bool = True) -> List[Dict[str, Any]]:
        """Get all pending approval requests.

        Args:
            sorted_by_priority: If True, sort by priority (highest first) then by creation time

        Returns:
            List of pending approval requests as dicts
        """
        reqs = list(self._pending.values())
        if sorted_by_priority:
            # Sort by priority (ascending, so 1=highest) then by created_at (ascending=oldest first)
            reqs.sort(key=lambda r: (r.priority, r.created_at))
        return [req.to_dict() for req in reqs]

    def resolve_approval(self, request_id: str, approved: bool, resolver_id: str) -> bool:
        """Called when a user approves/denies via UI or Channel."""
        request = self._pending.get(request_id)
        if request:
            request.status = "approved" if approved else "denied"
            if not request.future.done():
                request.future.set_result(approved)

            # Remove from pending (async context will also pop in finally)
            self._pending.pop(request_id, None)

            slog.log_event("approval_resolved", {
                "request_id": request_id,
                "approved": approved,
                "resolver": resolver_id
            }, session_id=request.session_id, run_id=request.run_id)

            # Broadcast resolution event
            try:
                import asyncio as aio
                from core.event_broadcaster import broadcast_approval_resolved
                # Schedule broadcast in event loop
                loop = aio.get_event_loop()
                loop.create_task(broadcast_approval_resolved(request_id, approved, resolver_id))
            except Exception as e:
                slog.log_event("approval_resolve_broadcast_error", {
                    "request_id": request_id,
                    "error": str(e)
                }, level="warning")

            return True
        return False

    def bulk_resolve(self, request_ids: List[str], approved: bool, resolver_id: str) -> Dict[str, Any]:
        """Resolve multiple approval requests in bulk.

        Args:
            request_ids: List of request IDs to resolve
            approved: Whether to approve or deny all
            resolver_id: ID of the user resolving approvals

        Returns:
            Dict with success count, failure count, and results
        """
        results = {
            "success": 0,
            "failure": 0,
            "resolved_ids": [],
            "failed_ids": []
        }

        for req_id in request_ids:
            if self.resolve_approval(req_id, approved, resolver_id):
                results["success"] += 1
                results["resolved_ids"].append(req_id)
            else:
                results["failure"] += 1
                results["failed_ids"].append(req_id)

        slog.log_event("approval_bulk_resolve", {
            "count": len(request_ids),
            "approved": approved,
            "success": results["success"],
            "failure": results["failure"]
        })

        return results

    def get_approval_metrics(self) -> Dict[str, Any]:
        """Get approval workflow metrics.

        Returns:
            Dict with pending counts, priority distribution, age stats
        """
        pending = list(self._pending.values())
        if not pending:
            return {
                "pending_count": 0,
                "by_priority": {},
                "by_risk_level": {},
                "oldest_age_seconds": 0,
                "newest_age_seconds": 0,
                "avg_age_seconds": 0
            }

        now = time.time()
        ages = [now - req.created_at for req in pending]
        by_risk = {}
        by_priority = {}

        for req in pending:
            risk = req.risk_level.value if hasattr(req.risk_level, 'value') else str(req.risk_level)
            by_risk[risk] = by_risk.get(risk, 0) + 1
            by_priority[req.priority] = by_priority.get(req.priority, 0) + 1

        return {
            "pending_count": len(pending),
            "by_priority": by_priority,
            "by_risk_level": by_risk,
            "oldest_age_seconds": max(ages),
            "newest_age_seconds": min(ages),
            "avg_age_seconds": sum(ages) / len(ages) if ages else 0
        }

# Global instance
_approval_engine: Optional[ApprovalEngine] = None

def get_approval_engine() -> ApprovalEngine:
    """Get or create the approval engine singleton."""
    global _approval_engine
    if _approval_engine is None:
        _approval_engine = ApprovalEngine()
    return _approval_engine

# Backward compatibility
approval_engine = get_approval_engine()
