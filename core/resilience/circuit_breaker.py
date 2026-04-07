from __future__ import annotations

import inspect
import time
from enum import Enum
from threading import RLock
from typing import Any, Callable, Dict, Optional

from utils.logger import get_logger

logger = get_logger("circuit_breaker")


class CircuitOpenError(RuntimeError):
    pass


class State(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitBreaker:
    def __init__(
        self,
        name: str = "",
        failure_threshold: int = 5,
        success_threshold: int = 2,
        timeout_seconds: float = 30.0,
    ):
        self.name = str(name or "")
        self.failure_threshold = int(failure_threshold)
        self.success_threshold = int(success_threshold)
        self.timeout_seconds = float(timeout_seconds)
        self.state = State.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time: Optional[float] = None
        self._lock = RLock()

    def _maybe_transition(self) -> None:
        if self.state == State.OPEN and self.last_failure_time is not None:
            if (time.time() - self.last_failure_time) >= self.timeout_seconds:
                self.state = State.HALF_OPEN
                self.success_count = 0
                logger.info("circuit_breaker_half_open", extra={"breaker_name": self.name})

    async def call(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        with self._lock:
            self._maybe_transition()
            if self.state == State.OPEN:
                raise CircuitOpenError(f"Circuit open: {self.name}")
        try:
            result = func(*args, **kwargs)
            if inspect.isawaitable(result):
                result = await result
            self._on_success()
            return result
        except Exception:
            self._on_failure()
            raise

    def _on_success(self) -> None:
        with self._lock:
            if self.state == State.HALF_OPEN:
                self.success_count += 1
                if self.success_count >= self.success_threshold:
                    self.state = State.CLOSED
                    self.failure_count = 0
                    self.success_count = 0
                    logger.info("circuit_breaker_closed", extra={"breaker_name": self.name})
            elif self.state == State.CLOSED and self.failure_count > 0:
                self.failure_count = max(0, self.failure_count - 1)

    def _on_failure(self) -> None:
        with self._lock:
            self.failure_count += 1
            self.last_failure_time = time.time()
            if self.failure_count >= self.failure_threshold:
                self.state = State.OPEN
                self.success_count = 0
                logger.warning("circuit_breaker_open", extra={"breaker_name": self.name, "failure_count": self.failure_count})
            elif self.state == State.HALF_OPEN:
                self.state = State.OPEN
                logger.warning("circuit_breaker_reopen", extra={"breaker_name": self.name})

    def can_execute(self) -> bool:
        with self._lock:
            self._maybe_transition()
            return self.state != State.OPEN

    def record_success(self) -> None:
        self._on_success()

    def record_failure(self) -> None:
        self._on_failure()

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "name": self.name,
                "state": self.state.value,
                "failure_count": self.failure_count,
                "success_count": self.success_count,
                "last_failure_time": self.last_failure_time,
            }


class CircuitBreakerRegistry:
    _instance: Optional["CircuitBreakerRegistry"] = None
    _instance_lock = RLock()

    def __new__(cls):
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._breakers = {}
                cls._instance._lock = RLock()
            return cls._instance

    def get_or_create(
        self,
        tool_name: str,
        failure_threshold: int = 5,
        success_threshold: int = 2,
        timeout_seconds: float = 30.0,
    ) -> CircuitBreaker:
        key = str(tool_name or "").strip()
        with self._lock:
            breaker = self._breakers.get(key)
            if breaker is None:
                breaker = CircuitBreaker(
                    name=key,
                    failure_threshold=failure_threshold,
                    success_threshold=success_threshold,
                    timeout_seconds=timeout_seconds,
                )
                self._breakers[key] = breaker
            return breaker

    def get_health_report(self) -> Dict[str, Any]:
        with self._lock:
            return {
                name: {
                    "state": breaker.state.value,
                    "failure_count": breaker.failure_count,
                    "last_failure_time": breaker.last_failure_time,
                }
                for name, breaker in self._breakers.items()
            }

class ProviderResilienceManager:
    def __init__(self):
        self.breakers: Dict[str, CircuitBreaker] = {}

    def get_breaker(self, provider: str) -> CircuitBreaker:
        if provider not in self.breakers:
            self.breakers[provider] = CircuitBreaker(name=provider)
        return self.breakers[provider]

    def can_call(self, provider: str) -> bool:
        return self.get_breaker(provider).can_execute()

    def record_success(self, provider: str):
        self.get_breaker(provider).record_success()

    def record_failure(self, provider: str):
        self.get_breaker(provider).record_failure()

    def get_all_states(self) -> Dict[str, str]:
        return {p: b.state.value for p, b in self.breakers.items()}


resilience_manager = ProviderResilienceManager()

_circuit_registry: Optional[CircuitBreakerRegistry] = None


def get_circuit_breaker_registry() -> CircuitBreakerRegistry:
    global _circuit_registry
    if _circuit_registry is None:
        _circuit_registry = CircuitBreakerRegistry()
    return _circuit_registry
