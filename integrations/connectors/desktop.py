from __future__ import annotations

import time
from typing import Any

from tools import system_tools

from core.realtime_actuator import get_realtime_actuator

from ..base import ConnectorResult, ConnectorSnapshot, ConnectorState, BaseConnector


class DesktopConnector(BaseConnector):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._actuator = None
        self._last_snapshot: dict[str, Any] = {}
        self._target = ""

    def _get_actuator(self):
        if self._actuator is None:
            self._actuator = get_realtime_actuator()
        return self._actuator

    async def connect(self, app_name_or_url: str, **kwargs: Any) -> ConnectorResult:
        started = time.perf_counter()
        target = str(app_name_or_url or "").strip()
        self._target = target
        if not target:
            snapshot = await self.snapshot()
            return self._result(
                success=True,
                status="ready",
                message="desktop_ready",
                latency_ms=(time.perf_counter() - started) * 1000.0,
                snapshot=snapshot,
                auth_state=self.auth_account.status,
            )

        if target.startswith(("http://", "https://")) or "." in target:
            result = await system_tools.open_url(target)
        else:
            result = await system_tools.open_app(target)
        snapshot = await self.snapshot()
        success = bool(result.get("success", result.get("status") in {"success", "ok"}))
        status = "ready" if success else "failed"
        return self._result(
            success=success,
            status=status,
            message=str(result.get("message") or result.get("error") or target),
            error=str(result.get("error") or ""),
            latency_ms=(time.perf_counter() - started) * 1000.0,
            evidence=list(result.get("artifacts") or []),
            artifacts=list(result.get("artifacts") or []),
            snapshot=snapshot,
            result=dict(result),
            auth_state=self.auth_account.status if self.auth_account else ConnectorState.NEEDS_INPUT,
        )

    async def execute(self, action: dict[str, Any]) -> ConnectorResult:
        started = time.perf_counter()
        payload = dict(action or {})
        kind = str(payload.get("kind") or payload.get("action") or "").strip().lower()
        if kind in {"open_app", "open_url"}:
            if kind == "open_url":
                result = await system_tools.open_url(str(payload.get("url") or payload.get("target") or payload.get("text") or ""))
            else:
                result = await system_tools.open_app(str(payload.get("app") or payload.get("target") or payload.get("text") or ""))
        elif kind == "type":
            result = await system_tools.type_text(str(payload.get("text") or payload.get("value") or ""), press_enter=bool(payload.get("press_enter", False)))
        elif kind == "press_key":
            result = await system_tools.press_key(str(payload.get("key") or ""), modifiers=list(payload.get("modifiers") or []))
        elif kind == "take_screenshot":
            result = await system_tools.take_screenshot(filename=str(payload.get("filename") or ""))
        elif kind == "capture_region":
            result = await system_tools.capture_region(
                int(payload.get("x", 0) or 0),
                int(payload.get("y", 0) or 0),
                int(payload.get("width", 0) or 0),
                int(payload.get("height", 0) or 0),
                filename=str(payload.get("filename") or ""),
            )
        elif kind == "read_clipboard":
            result = await system_tools.read_clipboard()
        elif kind == "write_clipboard":
            result = await system_tools.write_clipboard(str(payload.get("text") or payload.get("value") or ""))
        elif kind == "get_running_apps":
            result = await system_tools.get_running_apps()
        elif kind == "wait":
            result = {"success": True, "status": "success", "message": "waited"}
        else:
            action_payload = {
                "instruction": str(payload.get("instruction") or payload.get("goal") or payload.get("text") or kind or "desktop action"),
                "mode": str(payload.get("mode") or "inspect_and_control"),
                "region": dict(payload.get("region") or {}) if isinstance(payload.get("region"), dict) else None,
                "final_screenshot": bool(payload.get("final_screenshot", True)),
                "max_actions": int(payload.get("max_actions", 4) or 4),
                "max_retries_per_action": int(payload.get("max_retries_per_action", 2) or 2),
            }
            result = await self._get_actuator().submit_async(action_payload)
        snapshot = await self.snapshot()
        success = bool(result.get("success", result.get("status") in {"success", "ok", "ready"}))
        status = str(result.get("status") or ("success" if success else "failed"))
        fallback_used = bool(result.get("fallback_used") or result.get("source") in {"realtime_actuator", "system_tools"})
        return self._result(
            success=success,
            status=status,
            message=str(result.get("message") or result.get("summary") or ""),
            error=str(result.get("error") or ""),
            fallback_used=fallback_used,
            fallback_reason=str(result.get("fallback_reason") or ""),
            latency_ms=(time.perf_counter() - started) * 1000.0,
            evidence=list(result.get("evidence") or result.get("artifacts") or []),
            artifacts=list(result.get("artifacts") or []),
            snapshot=snapshot,
            result=dict(result),
            retryable=bool(result.get("retryable", False)),
            auth_state=self.auth_account.status if self.auth_account else ConnectorState.NEEDS_INPUT,
        )

    async def snapshot(self) -> ConnectorSnapshot:
        act_snapshot = {}
        try:
            act_snapshot = dict(self._get_actuator().snapshot() or {})
        except Exception:
            act_snapshot = {}
        running = {}
        try:
            running = await system_tools.get_running_apps()
        except Exception:
            running = {}
        metadata = {
            "running_apps": running,
            "target": self._target,
        }
        ui_state = (act_snapshot.get("last_observation") or {}).get("ui_state") if isinstance((act_snapshot.get("last_observation") or {}).get("ui_state"), dict) else {}
        last_action_result = (act_snapshot.get("last_action") or {}).get("result") if isinstance((act_snapshot.get("last_action") or {}).get("result"), dict) else {}
        snapshot = self._snapshot(
            state="ready" if act_snapshot else "idle",
            target=self._target,
            elements=list(ui_state.get("elements") or []),
            artifacts=list(last_action_result.get("artifacts") or []),
            metadata=metadata,
            auth_state=self.auth_account.status if self.auth_account else ConnectorState.NEEDS_INPUT,
        )
        self._last_snapshot = snapshot.model_dump()
        return snapshot
