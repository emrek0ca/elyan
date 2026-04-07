from __future__ import annotations

import asyncio
import time

from core.resilience import circuit_breaker as circuit_module
from core.resilience.circuit_breaker import CircuitBreaker, CircuitBreakerRegistry, CircuitOpenError


def test_closed_to_open_after_threshold():
    breaker = CircuitBreaker("tool", failure_threshold=2, success_threshold=1, timeout_seconds=0.01)
    breaker.record_failure()
    breaker.record_failure()
    assert breaker.state.value == "OPEN"


def test_open_rejects_calls():
    breaker = CircuitBreaker("tool", failure_threshold=1, success_threshold=1, timeout_seconds=60)
    breaker.record_failure()

    async def run():
        try:
            await breaker.call(lambda: 1)
        except CircuitOpenError:
            return True
        return False

    assert asyncio.run(run()) is True


def test_half_open_after_timeout():
    breaker = CircuitBreaker("tool", failure_threshold=1, success_threshold=1, timeout_seconds=0.01)
    breaker.record_failure()
    time.sleep(0.02)
    assert breaker.can_execute() is True
    assert breaker.state.value == "HALF_OPEN"


def test_successful_half_open_closes():
    breaker = CircuitBreaker("tool", failure_threshold=1, success_threshold=1, timeout_seconds=0.01)
    breaker.record_failure()
    time.sleep(0.02)
    asyncio.run(breaker.call(lambda: 1))
    assert breaker.state.value == "CLOSED"


def test_failed_half_open_stays_open():
    breaker = CircuitBreaker("tool", failure_threshold=1, success_threshold=2, timeout_seconds=0.01)
    breaker.record_failure()
    time.sleep(0.02)

    async def run():
        try:
            await breaker.call(lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        except RuntimeError:
            pass

    asyncio.run(run())
    assert breaker.state.value == "OPEN"


def test_failure_count_decrements_on_success():
    breaker = CircuitBreaker("tool", failure_threshold=5, success_threshold=1, timeout_seconds=1)
    breaker.record_failure()
    breaker.record_success()
    assert breaker.failure_count == 0


def test_registry_creates_per_tool_breaker():
    circuit_module.CircuitBreakerRegistry._instance = None
    registry = CircuitBreakerRegistry()
    a = registry.get_or_create("a")
    b = registry.get_or_create("b")
    assert a is not b


def test_health_report_reflects_states():
    circuit_module.CircuitBreakerRegistry._instance = None
    registry = CircuitBreakerRegistry()
    breaker = registry.get_or_create("a")
    breaker.record_failure()
    report = registry.get_health_report()
    assert report["a"]["state"] in {"CLOSED", "OPEN"}
