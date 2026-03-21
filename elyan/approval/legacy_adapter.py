from __future__ import annotations

import asyncio
import inspect
import sys
import warnings
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Optional

from .gate import check_approval
from .matrix import ApprovalLevel, ApprovalMatrix, get_approval_matrix


class RiskLevel(Enum):
    SAFE = "safe"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class ApprovalRequest:
    id: str
    operation: str
    risk_level: RiskLevel
    description: str
    params: dict[str, Any]
    user_id: int
    timestamp: str
    status: str = "pending"
    response: Optional[str] = None
    response_time: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def action(self) -> str:
        return self.operation

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "operation": self.operation,
            "action": self.action,
            "risk_level": self.risk_level.value,
            "description": self.description,
            "params": dict(self.params),
            "user_id": self.user_id,
            "timestamp": self.timestamp,
            "status": self.status,
            "response": self.response,
            "response_time": self.response_time,
            "metadata": dict(self.metadata or {}),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ApprovalRequest":
        raw = dict(payload or {})
        risk = str(raw.get("risk_level") or "low").strip().lower() or "low"
        try:
            risk_level = RiskLevel(risk)
        except Exception:
            risk_level = RiskLevel.LOW
        return cls(
            id=str(raw.get("id") or raw.get("approval_id") or ""),
            operation=str(raw.get("operation") or raw.get("action") or ""),
            risk_level=risk_level,
            description=str(raw.get("description") or ""),
            params=dict(raw.get("params") or {}),
            user_id=int(raw.get("user_id") or 0),
            timestamp=str(raw.get("timestamp") or raw.get("created_at") or ""),
            status=str(raw.get("status") or "pending"),
            response=raw.get("response"),
            response_time=raw.get("response_time"),
            metadata=dict(raw.get("metadata") or {}),
        )


def _clean_text(value: Any) -> str:
    return str(value or "").strip().lower()


async def _invoke_callback(callback: Callable[..., Any], request: ApprovalRequest) -> Any:
    result = callback(request)
    if inspect.isawaitable(result):
        return await result
    return result


def _risk_from_level(operation: str, matrix: ApprovalMatrix) -> RiskLevel:
    op = _clean_text(operation)
    if op in {"shutdown_system", "restart_system"}:
        return RiskLevel.CRITICAL
    if op in {"sleep_system", "lock_screen"}:
        return RiskLevel.HIGH
    if matrix.required_level >= ApprovalLevel.MANUAL:
        return RiskLevel.CRITICAL
    if matrix.required_level >= ApprovalLevel.TWO_FA:
        return RiskLevel.CRITICAL
    if matrix.required_level >= ApprovalLevel.SCREEN:
        return RiskLevel.HIGH
    if matrix.required_level >= ApprovalLevel.CONFIRM:
        return RiskLevel.MEDIUM
    if matrix.destructive:
        return RiskLevel.HIGH
    return RiskLevel.SAFE


class ApprovalManager:
    def __init__(self, default_timeout: int = 300):
        self.default_timeout = int(default_timeout or 300)
        self.pending_requests: dict[str, ApprovalRequest] = {}
        self.approval_history: list[ApprovalRequest] = []
        self.approval_callback: Optional[Callable[..., Any]] = None
        self.auto_approve_low_risk = True
        self.trusted_users: set[int] = set()
        self._request_counter = 0

    def set_approval_callback(self, callback: Callable[..., Any]):
        self.approval_callback = callback

    def _next_request_id(self, user_id: int) -> str:
        self._request_counter += 1
        return f"req_{user_id}_{int(datetime.now().timestamp() * 1000)}_{self._request_counter:04d}"

    def _can_auto_approve(self, risk_level: RiskLevel, user_id: int) -> bool:
        if risk_level == RiskLevel.SAFE:
            return True
        if risk_level == RiskLevel.LOW and self.auto_approve_low_risk:
            return True
        if user_id in self.trusted_users and risk_level in {RiskLevel.LOW, RiskLevel.MEDIUM}:
            return True
        return False

    def classify_operation_risk(self, operation: str, params: dict[str, Any]) -> RiskLevel:
        payload = dict(params or {})
        op = _clean_text(operation)
        matrix = get_approval_matrix(
            op,
            {
                "type": op,
                "description": str(payload.get("description") or payload.get("command") or payload.get("path") or op),
                "command": str(payload.get("command") or payload.get("cmd") or payload.get("code") or ""),
                "destructive": bool(payload.get("destructive", False)),
                "needs_network": bool(payload.get("needs_network", False)),
                "requires_2fa": bool(payload.get("requires_2fa", False)),
                "requires_screen": bool(payload.get("requires_screen", False)),
                "manual_only": bool(payload.get("manual_only", False)),
                "approval_required": bool(payload.get("approval_required", False)),
                "approval_level": payload.get("approval_level"),
                "integration_type": str(payload.get("integration_type") or payload.get("skill_type") or ""),
            },
        )
        return _risk_from_level(op, matrix)

    async def request_approval(
        self,
        operation: str,
        risk_level: RiskLevel,
        description: str,
        params: dict[str, Any],
        user_id: int,
        timeout: int = None,
    ) -> dict[str, Any]:
        if self._can_auto_approve(risk_level, user_id):
            return {"approved": True, "auto_approved": True, "reason": "Low risk operation or trusted user"}

        request = ApprovalRequest(
            id=self._next_request_id(user_id),
            operation=str(operation or ""),
            risk_level=risk_level,
            description=str(description or ""),
            params=dict(params or {}),
            user_id=int(user_id or 0),
            timestamp=datetime.now().isoformat(),
        )

        stale_ids = [rid for rid, req in self.pending_requests.items() if req.user_id == request.user_id]
        for stale_id in stale_ids:
            stale_req = self.pending_requests.pop(stale_id, None)
            if stale_req is not None:
                stale_req.status = "expired"
                self.approval_history.append(stale_req)

        self.pending_requests[request.id] = request

        if not self.approval_callback:
            self.pending_requests.pop(request.id, None)
            request.status = "denied"
            self.approval_history.append(request)
            return {"approved": False, "reason": "Approval system not configured"}

        approved = False
        try:
            approved = bool(
                await asyncio.wait_for(
                    _invoke_callback(self.approval_callback, request),
                    timeout=timeout or self.default_timeout,
                )
            )
            request.status = "approved" if approved else "denied"
            request.response_time = datetime.now().isoformat()
        except asyncio.TimeoutError:
            request.status = "expired"
            approved = False
        except Exception:
            request.status = "error"
            approved = False
        finally:
            self.pending_requests.pop(request.id, None)
            self.approval_history.append(request)

        return {
            "approved": approved,
            "request_id": request.id,
            "status": request.status,
            "auto_approved": False,
        }

    def resolve(self, request_id: str, approved: bool) -> bool:
        request = self.pending_requests.pop(str(request_id or ""), None)
        if request is None:
            return False
        request.status = "approved" if approved else "denied"
        request.response_time = datetime.now().isoformat()
        self.approval_history.append(request)
        return True

    def add_trusted_user(self, user_id: int):
        self.trusted_users.add(int(user_id or 0))

    def remove_trusted_user(self, user_id: int):
        self.trusted_users.discard(int(user_id or 0))

    def get_approval_history(self, user_id: int = None, limit: int = 50) -> list[dict[str, Any]]:
        history = self.approval_history
        if user_id:
            history = [r for r in history if r.user_id == user_id]
        return [r.to_dict() for r in history[-max(1, int(limit or 50)) :]]


_approval_manager: Optional[ApprovalManager] = None


def get_approval_manager() -> ApprovalManager:
    global _approval_manager
    if _approval_manager is None:
        _approval_manager = ApprovalManager()
    return _approval_manager


async def require_approval(operation: str, description: str, params: dict[str, Any], user_id: int) -> bool:
    manager = get_approval_manager()
    risk_level = manager.classify_operation_risk(operation, params)
    result = await manager.request_approval(
        operation=operation,
        risk_level=risk_level,
        description=description,
        params=params,
        user_id=user_id,
    )
    return bool(result.get("approved", False))


def classify_risk(operation: str, params: dict[str, Any]) -> str:
    return get_approval_manager().classify_operation_risk(operation, params).value


def legacy_approve_action(skill_name: str, action: dict, user_context: dict = None) -> bool:
    warnings.warn(
        "security.approval.legacy_approve_action deprecated. Use elyan.approval.gate.check_approval() instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return bool(asyncio.run(check_approval(skill_name, action, user_context or {})))
    raise RuntimeError("legacy_approve_action is synchronous; use await check_approval() inside async code")


def patch_legacy_imports():
    module = sys.modules[__name__]
    sys.modules["security.approval"] = module
    sys.modules["elyan.security.approval"] = module
    return module


approval_manager = get_approval_manager()

__all__ = [
    "ApprovalManager",
    "ApprovalRequest",
    "RiskLevel",
    "approval_manager",
    "classify_risk",
    "get_approval_manager",
    "legacy_approve_action",
    "patch_legacy_imports",
    "require_approval",
]
