from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

from core.capabilities.screen_operator import run_screen_operator
from core.storage_paths import resolve_elyan_data_dir


ScreenOperatorRunner = Callable[..., Awaitable[dict[str, Any]]]


def _default_state_path() -> Path:
    return resolve_elyan_data_dir() / "desktop_host" / "state.json"


class DesktopHost:
    def __init__(
        self,
        *,
        state_path: Path | None = None,
        screen_operator_runner: ScreenOperatorRunner | None = None,
        max_recent_action_logs: int = 20,
        max_verifier_outcomes: int = 20,
        max_target_cache: int = 64,
    ) -> None:
        self.state_path = Path(state_path or _default_state_path())
        self.screen_operator_runner = screen_operator_runner or run_screen_operator
        self.max_recent_action_logs = max(1, int(max_recent_action_logs or 20))
        self.max_verifier_outcomes = max(1, int(max_verifier_outcomes or 20))
        self.max_target_cache = max(1, int(max_target_cache or 64))
        self._lock = asyncio.Lock()

    def _empty_state(self) -> dict[str, Any]:
        return {
            "version": 1,
            "updated_at": 0.0,
            "frontmost_app": "",
            "active_window": {},
            "last_screenshot": "",
            "last_ui_state": {},
            "current_task_state": {},
            "target_cache": {},
            "recent_action_logs": [],
            "verifier_outcomes": [],
            "last_instruction": "",
            "last_mode": "",
            "last_status": "",
        }

    def _trim_tail(self, items: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
        cleaned = [dict(item) for item in items if isinstance(item, dict)]
        return cleaned[-limit:]

    def _trim_target_cache(self, cache: dict[str, Any]) -> dict[str, Any]:
        items = [(str(key), dict(value)) for key, value in list(cache.items()) if str(key).strip() and isinstance(value, dict)]
        trimmed = items[-self.max_target_cache :]
        return {key: value for key, value in trimmed}

    def _coerce_state(self, raw: Any) -> dict[str, Any]:
        base = self._empty_state()
        if not isinstance(raw, dict):
            return base
        state = dict(base)
        state["updated_at"] = float(raw.get("updated_at") or 0.0)
        state["frontmost_app"] = str(raw.get("frontmost_app") or "").strip()
        state["active_window"] = dict(raw.get("active_window") or {}) if isinstance(raw.get("active_window"), dict) else {}
        state["last_screenshot"] = str(raw.get("last_screenshot") or "").strip()
        state["last_ui_state"] = dict(raw.get("last_ui_state") or {}) if isinstance(raw.get("last_ui_state"), dict) else {}
        state["current_task_state"] = dict(raw.get("current_task_state") or {}) if isinstance(raw.get("current_task_state"), dict) else {}
        state["target_cache"] = self._trim_target_cache(dict(raw.get("target_cache") or {}) if isinstance(raw.get("target_cache"), dict) else {})
        state["recent_action_logs"] = self._trim_tail(list(raw.get("recent_action_logs") or []), self.max_recent_action_logs)
        state["verifier_outcomes"] = self._trim_tail(list(raw.get("verifier_outcomes") or []), self.max_verifier_outcomes)
        state["last_instruction"] = str(raw.get("last_instruction") or "").strip()
        state["last_mode"] = str(raw.get("last_mode") or "").strip()
        state["last_status"] = str(raw.get("last_status") or "").strip()
        return state

    def _load_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return self._empty_state()
        try:
            return self._coerce_state(json.loads(self.state_path.read_text(encoding="utf-8")))
        except Exception:
            return self._empty_state()

    def _write_state(self, state: dict[str, Any]) -> None:
        payload = self._coerce_state(state)
        payload["updated_at"] = float(time.time())
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _compose_task_state(self, stored: dict[str, Any], override: dict[str, Any] | None = None) -> dict[str, Any]:
        override_state = override if isinstance(override, dict) else {}
        composed = dict(stored.get("current_task_state") or {})
        composed["last_ui_state"] = dict(override_state.get("last_ui_state") or stored.get("last_ui_state") or composed.get("last_ui_state") or {})
        composed["ui_state"] = dict(override_state.get("ui_state") or composed.get("ui_state") or composed.get("last_ui_state") or {})
        target_cache = dict(stored.get("target_cache") or {})
        target_cache.update(dict(composed.get("last_target_cache") or {}))
        target_cache.update(dict(override_state.get("last_target_cache") or {}))
        composed["last_target_cache"] = self._trim_target_cache(target_cache)
        composed["recent_action_logs"] = self._trim_tail(
            list(stored.get("recent_action_logs") or []) + list(override_state.get("recent_action_logs") or []),
            self.max_recent_action_logs,
        )
        composed["verifier_outcomes"] = self._trim_tail(
            list(stored.get("verifier_outcomes") or []) + list(override_state.get("verifier_outcomes") or []),
            self.max_verifier_outcomes,
        )
        return composed

    def _merge_result(self, stored: dict[str, Any], result: dict[str, Any], *, instruction: str, mode: str) -> dict[str, Any]:
        merged = self._coerce_state(stored)
        result_payload = result if isinstance(result, dict) else {}
        ui_state = result_payload.get("ui_state") if isinstance(result_payload.get("ui_state"), dict) else {}
        task_state = result_payload.get("task_state") if isinstance(result_payload.get("task_state"), dict) else {}
        if not ui_state:
            ui_state = task_state.get("last_ui_state") if isinstance(task_state.get("last_ui_state"), dict) else {}
        if not ui_state:
            ui_state = task_state.get("ui_state") if isinstance(task_state.get("ui_state"), dict) else {}
        target_cache = dict(merged.get("target_cache") or {})
        target_cache.update(dict(task_state.get("last_target_cache") or {}))
        action_logs = self._trim_tail(list(merged.get("recent_action_logs") or []) + list(result_payload.get("action_logs") or []), self.max_recent_action_logs)
        verifier_outcomes = self._trim_tail(list(merged.get("verifier_outcomes") or []) + list(result_payload.get("verifier_outcomes") or []), self.max_verifier_outcomes)
        screenshots = [str(path).strip() for path in list(result_payload.get("screenshots") or []) if str(path).strip()]

        merged["frontmost_app"] = str(ui_state.get("frontmost_app") or merged.get("frontmost_app") or "").strip()
        merged["active_window"] = dict(ui_state.get("active_window") or merged.get("active_window") or {})
        merged["last_screenshot"] = screenshots[-1] if screenshots else str(merged.get("last_screenshot") or "")
        merged["last_ui_state"] = dict(ui_state or merged.get("last_ui_state") or {})
        merged["current_task_state"] = self._compose_task_state(
            {
                **merged,
                "target_cache": target_cache,
                "recent_action_logs": action_logs,
                "verifier_outcomes": verifier_outcomes,
            },
            task_state,
        )
        merged["current_task_state"]["last_ui_state"] = dict(merged["last_ui_state"])
        merged["current_task_state"]["ui_state"] = dict(merged["last_ui_state"])
        merged["target_cache"] = self._trim_target_cache(target_cache)
        merged["recent_action_logs"] = action_logs
        merged["verifier_outcomes"] = verifier_outcomes
        merged["last_instruction"] = str(instruction or "").strip()
        merged["last_mode"] = str(mode or "").strip()
        merged["last_status"] = str(result_payload.get("status") or ("success" if result_payload.get("success") else "failed")).strip()
        return merged

    def _state_summary(self, state: dict[str, Any]) -> dict[str, Any]:
        return {
            "frontmost_app": str(state.get("frontmost_app") or "").strip(),
            "active_window": dict(state.get("active_window") or {}),
            "last_screenshot": str(state.get("last_screenshot") or "").strip(),
            "target_cache_size": len(dict(state.get("target_cache") or {})),
            "recent_action_log_count": len(list(state.get("recent_action_logs") or [])),
            "verifier_outcome_count": len(list(state.get("verifier_outcomes") or [])),
            "updated_at": float(state.get("updated_at") or 0.0),
            "last_instruction": str(state.get("last_instruction") or "").strip(),
            "last_mode": str(state.get("last_mode") or "").strip(),
            "last_status": str(state.get("last_status") or "").strip(),
        }

    async def get_live_state(self) -> dict[str, Any]:
        async with self._lock:
            return self._load_state()

    async def clear_live_state(self) -> dict[str, Any]:
        async with self._lock:
            cleared = self._empty_state()
            self._write_state(cleared)
            return cleared

    async def run_screen_operator(
        self,
        *,
        instruction: str,
        mode: str = "inspect",
        region: dict[str, Any] | None = None,
        final_screenshot: bool = True,
        max_actions: int = 4,
        max_retries_per_action: int = 2,
        services: Any = None,
        task_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        async with self._lock:
            stored = self._load_state()
            composed_task_state = self._compose_task_state(stored, task_state)
            result = await self.screen_operator_runner(
                instruction=instruction,
                mode=mode,
                region=region,
                final_screenshot=final_screenshot,
                max_actions=max_actions,
                max_retries_per_action=max_retries_per_action,
                services=services,
                task_state=composed_task_state,
            )
            next_state = self._merge_result(stored, result, instruction=instruction, mode=mode)
            self._write_state(next_state)
        response = dict(result or {})
        response["desktop_host_state"] = self._state_summary(next_state)
        return response


_DESKTOP_HOST: DesktopHost | None = None


def get_desktop_host() -> DesktopHost:
    global _DESKTOP_HOST
    if _DESKTOP_HOST is None:
        _DESKTOP_HOST = DesktopHost()
    return _DESKTOP_HOST


__all__ = ["DesktopHost", "get_desktop_host"]
