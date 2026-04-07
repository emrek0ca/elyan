from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.feature_flags import get_feature_flag_registry
from core.observability.logger import get_structured_logger
from core.observability.trace_context import get_trace_context


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return str(value)


@dataclass(frozen=True)
class ExecutionCheck:
    name: str
    allowed: bool
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "name": str(self.name or "").strip().lower(),
            "allowed": bool(self.allowed),
            "reason": str(self.reason or "").strip(),
            "metadata": _json_safe(dict(self.metadata or {})),
        }
        return payload


class ExecutionGuard:
    def __init__(self) -> None:
        self._flags = get_feature_flag_registry()
        self._logger = get_structured_logger("execution_guard")

    def resolve_shadow_flag(
        self,
        *,
        runtime_policy: dict[str, Any] | None = None,
        actor_id: str = "",
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._flags.resolve(
            "execution_guard_shadow",
            runtime_policy=runtime_policy,
            user_id=actor_id,
            context=context,
            default=False,
        )

    def observe_shadow(
        self,
        *,
        action: str,
        phase: str,
        allowed: bool,
        workspace_id: str = "",
        actor_id: str = "",
        session_id: str = "",
        run_id: str = "",
        reason: str = "",
        checks: list[ExecutionCheck] | None = None,
        metadata: dict[str, Any] | None = None,
        runtime_policy: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
        level: str = "info",
    ) -> bool:
        flag_state = self.resolve_shadow_flag(
            runtime_policy=runtime_policy,
            actor_id=actor_id,
            context=context,
        )
        if not flag_state.get("enabled", False):
            return False

        trace_context = get_trace_context()
        self._logger.log_event(
            "execution_guard_shadow",
            {
                "shadow_mode": True,
                "action": str(action or "").strip().lower(),
                "phase": str(phase or "").strip().lower(),
                "allowed": bool(allowed),
                "reason": str(reason or "").strip(),
                "actor_id": str(actor_id or "").strip(),
                "flag_source": str(flag_state.get("source") or "default"),
                "checks": [item.to_dict() for item in (checks or [])],
                "metadata": _json_safe(dict(metadata or {})),
            },
            level=level,
            session_id=session_id or (trace_context.session_id if trace_context else None),
            run_id=run_id or None,
            trace_id=trace_context.trace_id if trace_context else None,
            request_id=trace_context.request_id if trace_context else None,
            workspace_id=workspace_id or (trace_context.workspace_id if trace_context else None),
        )
        return True

    def observe_capability_runtime(
        self,
        *,
        capability: str,
        action: str,
        success: bool,
        workspace_id: str = "",
        actor_id: str = "",
        session_id: str = "",
        run_id: str = "",
        reason: str = "",
        verification: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        runtime_policy: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
        level: str = "info",
    ) -> bool:
        verification_payload = dict(verification or {})
        verification_status = str(verification_payload.get("status") or "").strip().lower()
        failed_codes = [str(item).strip() for item in list(verification_payload.get("failed_codes") or []) if str(item).strip()]
        checks = [
            ExecutionCheck(
                name="capability_runtime_result",
                allowed=bool(success),
                reason=str(reason or ""),
                metadata={
                    "capability": str(capability or "").strip().lower(),
                    "action": str(action or "").strip().lower(),
                },
            )
        ]
        if verification_payload:
            checks.append(
                ExecutionCheck(
                    name="capability_runtime_verification",
                    allowed=bool(success and verification_status in {"success", "passed", "partial", "inconclusive"}),
                    reason=str(verification_payload.get("reason") or ""),
                    metadata={
                        "status": verification_status,
                        "failed_codes": failed_codes,
                    },
                )
            )
        return self.observe_shadow(
            action=f"{str(capability or '').strip().lower()}.{str(action or '').strip().lower()}",
            phase="capability_runtime",
            allowed=bool(success),
            workspace_id=workspace_id,
            actor_id=actor_id,
            session_id=session_id,
            run_id=run_id,
            reason=str(reason or ""),
            checks=checks,
            metadata={
                "verification": verification_payload,
                **dict(metadata or {}),
            },
            runtime_policy=runtime_policy,
            context=context,
            level=level,
        )


_execution_guard: ExecutionGuard | None = None


def get_execution_guard() -> ExecutionGuard:
    global _execution_guard
    if _execution_guard is None:
        _execution_guard = ExecutionGuard()
    return _execution_guard


__all__ = ["ExecutionCheck", "ExecutionGuard", "get_execution_guard"]
