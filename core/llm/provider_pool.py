from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable


@dataclass(slots=True)
class _ProviderState:
    consecutive_failures: int = 0
    cooldown_until: float = 0.0
    cooldown_seconds: float = 0.0
    last_error: str = ""
    last_failure_at: float = 0.0
    last_success_at: float = 0.0


class ProviderPool:
    """Tracks provider/model health and applies cooldown after repeated failures."""

    def __init__(
        self,
        *,
        base_cooldown_seconds: float = 15.0,
        max_cooldown_seconds: float = 300.0,
        failure_threshold: int = 2,
        time_fn: Callable[[], float] | None = None,
    ) -> None:
        self.base_cooldown_seconds = max(1.0, float(base_cooldown_seconds or 15.0))
        self.max_cooldown_seconds = max(self.base_cooldown_seconds, float(max_cooldown_seconds or 300.0))
        self.failure_threshold = max(1, int(failure_threshold or 2))
        self._time_fn = time_fn or time.monotonic
        self._states: dict[tuple[str, str], _ProviderState] = {}

    @staticmethod
    def _key(provider: str, model: str) -> tuple[str, str]:
        return (str(provider or "").strip().lower(), str(model or "").strip().lower())

    def _state(self, provider: str, model: str) -> _ProviderState:
        key = self._key(provider, model)
        state = self._states.get(key)
        if state is None:
            state = _ProviderState()
            self._states[key] = state
        return state

    def can_attempt(self, provider: str, model: str) -> bool:
        state = self._state(provider, model)
        return self._time_fn() >= float(state.cooldown_until or 0.0)

    def record_outcome(self, provider: str, model: str, success: bool, error_text: str = "") -> None:
        state = self._state(provider, model)
        now = self._time_fn()
        if success:
            state.consecutive_failures = 0
            state.cooldown_until = 0.0
            state.cooldown_seconds = 0.0
            state.last_error = ""
            state.last_success_at = now
            return

        state.consecutive_failures += 1
        state.last_error = str(error_text or "").strip()
        state.last_failure_at = now
        if state.consecutive_failures < self.failure_threshold:
            return

        exponent = max(0, state.consecutive_failures - self.failure_threshold)
        cooldown_seconds = min(self.max_cooldown_seconds, self.base_cooldown_seconds * (2 ** exponent))
        state.cooldown_seconds = float(cooldown_seconds)
        state.cooldown_until = now + float(cooldown_seconds)

    def get_provider_state(self, provider: str, model: str) -> dict[str, float | int | str | bool]:
        state = self._state(provider, model)
        now = self._time_fn()
        remaining = max(0.0, float(state.cooldown_until or 0.0) - now)
        return {
            "provider": str(provider or "").strip().lower(),
            "model": str(model or "").strip(),
            "consecutive_failures": int(state.consecutive_failures or 0),
            "cooldown_active": remaining > 0,
            "cooldown_seconds": float(state.cooldown_seconds or 0.0),
            "cooldown_seconds_remaining": remaining,
            "last_error": str(state.last_error or ""),
            "last_failure_at": float(state.last_failure_at or 0.0),
            "last_success_at": float(state.last_success_at or 0.0),
        }


__all__ = ["ProviderPool"]
