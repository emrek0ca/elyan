"""P0 — Deadline + cancellation token zinciri.

Tek bir CancellationToken, runner → executor → registry → adapter → subprocess
zincirinde contextvar ile taşınır. Kurallar:

- Token iptal/timeout olduktan sonra hiçbir YENİ yan etki başlatılamaz:
  `guard_side_effect()` fail-closed hata verir.
- Aynı token bir kez iptal edilir; sebep ilk yazanın kalır (fence).
- Deadline monotonic saatle ölçülür; duvar saati oynamalarından etkilenmez.
"""

from __future__ import annotations

import contextvars
import threading
import time
from typing import Any


class CancelledError(RuntimeError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason or "execution_cancelled")
        self.code = "EXECUTION_CANCELLED" if reason != "deadline_exceeded" else "TASK_EXECUTION_TIMEOUT"
        self.reason = reason or "execution_cancelled"


class CancellationToken:
    """İptal + deadline taşıyan, thread-safe, tek yönlü (geri alınamaz) token."""

    def __init__(self, *, deadline_seconds: float | None = None, parent: "CancellationToken | None" = None) -> None:
        self._lock = threading.Lock()
        self._reason = ""
        self._parent = parent
        self._deadline_at = (
            time.monotonic() + max(0.0, float(deadline_seconds))
            if deadline_seconds is not None
            else None
        )

    # ------------------------------------------------------------------ durum

    def cancel(self, reason: str = "execution_cancelled") -> bool:
        """İlk iptal kazanır; sonrakiler no-op (False döner)."""
        normalized = " ".join(str(reason or "execution_cancelled").split())[:120] or "execution_cancelled"
        with self._lock:
            if self._reason:
                return False
            self._reason = normalized
            return True

    @property
    def deadline_at(self) -> float | None:
        return self._deadline_at

    def time_remaining(self) -> float | None:
        if self._deadline_at is None:
            return None
        return max(0.0, self._deadline_at - time.monotonic())

    def cancellation_reason(self) -> str:
        """İptal sebebi; deadline aşıldıysa 'deadline_exceeded'. Boş = aktif."""
        with self._lock:
            if self._reason:
                return self._reason
        if self._parent is not None:
            parent_reason = self._parent.cancellation_reason()
            if parent_reason:
                return parent_reason
        if self._deadline_at is not None and time.monotonic() >= self._deadline_at:
            return "deadline_exceeded"
        return ""

    def cancelled(self) -> bool:
        return bool(self.cancellation_reason())

    # ------------------------------------------------------------------ kapılar

    def raise_if_cancelled(self) -> None:
        reason = self.cancellation_reason()
        if reason:
            raise CancelledError(reason)

    def guard_side_effect(self) -> None:
        """Timeout/iptal SONRASI hiçbir yeni yan etki başlatılamaz (fail-closed)."""
        self.raise_if_cancelled()

    def sleep(self, seconds: float) -> bool:
        """İptal edilebilir bekleme; iptal olduysa False döner (erken uyanır)."""
        deadline = time.monotonic() + max(0.0, float(seconds))
        while time.monotonic() < deadline:
            if self.cancelled():
                return False
            time.sleep(min(0.1, max(0.0, deadline - time.monotonic())))
        return not self.cancelled()

    def child(self, *, deadline_seconds: float | None = None) -> "CancellationToken":
        """Alt kapsam: ebeveyn iptali alta yansır; alt iptal ebeveyni etkilemez."""
        return CancellationToken(deadline_seconds=deadline_seconds, parent=self)


_CURRENT_TOKEN: contextvars.ContextVar[CancellationToken | None] = contextvars.ContextVar(
    "elyan_cancellation_token", default=None
)


def current_token() -> CancellationToken | None:
    return _CURRENT_TOKEN.get()


def current_cancellation_reason() -> str:
    token = _CURRENT_TOKEN.get()
    return token.cancellation_reason() if token is not None else ""


class token_scope:
    """`with token_scope(token):` — zincirin altındaki her katman current_token()
    ile aynı token'ı görür (registry/adapter/subprocess)."""

    def __init__(self, token: CancellationToken) -> None:
        self._token = token
        self._reset: contextvars.Token[Any] | None = None

    def __enter__(self) -> CancellationToken:
        self._reset = _CURRENT_TOKEN.set(self._token)
        return self._token

    def __exit__(self, *_exc: Any) -> None:
        if self._reset is not None:
            try:
                _CURRENT_TOKEN.reset(self._reset)
            except (ValueError, LookupError):
                pass
