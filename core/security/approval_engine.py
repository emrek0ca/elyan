import asyncio
import uuid
import time
import json
import os
from typing import Any, Dict, List, Optional, Callable
from pathlib import Path
from core.persistence import get_runtime_database
from core.protocol.shared_types import RiskLevel
from core.observability.logger import get_structured_logger
from core.storage_paths import resolve_elyan_data_dir

slog = get_structured_logger("approval_engine")


def _create_future() -> asyncio.Future:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
    return loop.create_future()

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
        self.future = _create_future()
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

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "ApprovalRequest":
        """Rehydrate persisted pending request."""
        risk_raw = str(payload.get("risk_level") or RiskLevel.WRITE_SAFE.value)
        try:
            risk = RiskLevel(risk_raw)
        except Exception:
            risk = RiskLevel.WRITE_SAFE
        req = cls(
            request_id=str(payload.get("request_id") or f"appr_{uuid.uuid4().hex[:8]}"),
            session_id=str(payload.get("session_id") or "unknown"),
            run_id=str(payload.get("run_id") or ""),
            action_type=str(payload.get("action_type") or "unknown"),
            payload=payload.get("payload") if isinstance(payload.get("payload"), dict) else {},
            risk_level=risk,
            reason=str(payload.get("reason") or ""),
        )
        req.status = str(payload.get("status") or "pending")
        created_at = payload.get("created_at")
        try:
            req.created_at = float(created_at) if created_at is not None else time.time()
        except Exception:
            req.created_at = time.time()
        req.priority = req._calculate_priority()
        return req

class ApprovalEngine:
    """
    Manages pending human approval requests for sensitive actions.
    """
    def __init__(self):
        self._pending: Dict[str, ApprovalRequest] = {}
        self._pending_store_path = resolve_elyan_data_dir() / "approvals" / "pending.json"
        self._pending_store_path.parent.mkdir(parents=True, exist_ok=True)
        self._repository = get_runtime_database().approvals
        self._permission_grants = get_runtime_database().permission_grants
        persist_mode = os.environ.get("ELYAN_APPROVAL_PERSIST", "1").strip().lower()
        legacy_mode = os.environ.get("ELYAN_APPROVAL_LEGACY_JSON", "0").strip().lower()
        self._persistence_enabled = persist_mode not in {"0", "false", "off"} and (
            persist_mode in {"force", "always"} or "PYTEST_CURRENT_TEST" not in os.environ
        )
        self._legacy_store_enabled = legacy_mode in {"1", "true", "on", "force", "always"}
        if self._persistence_enabled:
            self._restore_pending()

    def _persist_pending(self) -> None:
        """Persist current pending approvals for crash recovery."""
        if not self._persistence_enabled or not self._legacy_store_enabled:
            return
        try:
            payload = [req.to_dict() for req in self._pending.values()]
            tmp = self._pending_store_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self._pending_store_path)
        except Exception as e:
            slog.log_event("approval_persist_error", {"error": str(e)}, level="warning")

    def _restore_pending(self) -> None:
        """Restore pending approvals from disk after restart."""
        try:
            self._repository.ensure_legacy_import(self._pending_store_path)
            raw = self._repository.list_pending()
            restored = 0
            for item in raw:
                if not isinstance(item, dict):
                    continue
                req = ApprovalRequest.from_dict(item)
                if req.status != "pending":
                    continue
                self._pending[req.request_id] = req
                restored += 1
            if restored:
                slog.log_event("approval_restored", {"count": restored})
        except Exception as e:
            slog.log_event("approval_restore_error", {"error": str(e)}, level="warning")

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
        try:
            from core.reasoning.uncertainty_engine import get_uncertainty_engine

            uncertainty = get_uncertainty_engine()
            if not uncertainty.should_ask_approval(action_type):
                slog.log_event(
                    "approval_implicit",
                    {"action": action_type, "reason": "uncertainty_threshold_met"},
                    session_id=session_id,
                    run_id=run_id,
                )
                return True
        except Exception as exc:
            slog.log_event(
                "approval_uncertainty_unavailable",
                {"action": action_type, "error": str(exc)},
                level="debug",
                session_id=session_id,
                run_id=run_id,
            )
        request_id = f"appr_{uuid.uuid4().hex[:8]}"
        request = ApprovalRequest(request_id, session_id, run_id, action_type, payload, risk_level, reason)
        self._pending[request_id] = request
        self._persist_pending()
        if self._persistence_enabled:
            approval_payload = request.to_dict()
            approval_payload["workspace_id"] = str(
                payload.get("workspace_id")
                or payload.get("metadata", {}).get("workspace_id")
                or "local-workspace"
            )
            self._repository.upsert_pending(approval_payload)

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
            self._persist_pending()
            if self._persistence_enabled and request.status == "pending":
                self._repository.mark_timed_out(request_id)

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
            if approved:
                self._issue_scoped_grant(request, resolver_id)
            if not request.future.done():
                request.future.set_result(approved)

            # Remove from pending (async context will also pop in finally)
            self._pending.pop(request_id, None)
            self._persist_pending()
            if self._persistence_enabled:
                self._repository.mark_resolved(request_id, approved=approved, resolver_id=resolver_id)

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

    def _issue_scoped_grant(self, request: ApprovalRequest, resolver_id: str) -> None:
        payload = dict(request.payload or {})
        grant_payload = payload.get("permission_grant") if isinstance(payload.get("permission_grant"), dict) else payload
        scope = str(grant_payload.get("scope") or "").strip()
        resource = str(grant_payload.get("resource") or "").strip()
        allowed_actions = [str(item).strip() for item in list(grant_payload.get("allowed_actions") or []) if str(item).strip()]
        if not scope or not resource or not allowed_actions:
            return
        try:
            self._permission_grants.issue_grant(
                workspace_id=str(
                    grant_payload.get("workspace_id")
                    or payload.get("workspace_id")
                    or payload.get("metadata", {}).get("workspace_id")
                    or "local-workspace"
                ),
                device_id=str(grant_payload.get("device_id") or "local-device"),
                scope=scope,
                resource=resource,
                allowed_actions=allowed_actions,
                ttl_seconds=max(0, int(grant_payload.get("ttl_seconds") or 0)),
                issued_by=str(resolver_id or "desktop_operator"),
                revocable=bool(grant_payload.get("revocable", True)),
                metadata={
                    "approval_request_id": request.request_id,
                    "action_type": request.action_type,
                },
            )
        except Exception as exc:
            slog.log_event(
                "approval_grant_issue_failed",
                {"request_id": request.request_id, "error": str(exc)},
                level="warning",
            )

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
