"""
core/multi_llm_engine.py
─────────────────────────────────────────────────────────────────────────────
Multi-LLM Concurrent Execution Engine.

Provides:
  - Race mode: run same prompt on N models simultaneously, pick fastest/best
  - Parallel task decomposition: split sub-tasks across different models
  - Live metrics streaming to dashboard via WebSocket
  - Model health monitoring with auto-disable
  - Request queuing with priority and rate limiting
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("multi_llm_engine")


# ─── Data Structures ───────────────────────────────────────────────────────

class ExecutionStrategy(str, Enum):
    RACE = "race"              # First successful response wins
    PARALLEL = "parallel"      # All run, results merged
    ROUND_ROBIN = "round_robin"  # Distribute sequentially
    CHEAPEST = "cheapest"      # Pick lowest-cost provider
    FASTEST = "fastest"        # Pick historically fastest provider


@dataclass
class ModelSlot:
    provider: str
    model: str
    enabled: bool = True
    priority: int = 50
    max_concurrent: int = 5
    current_load: int = 0
    # Rolling metrics
    total_calls: int = 0
    total_success: int = 0
    total_failures: int = 0
    total_tokens: int = 0
    latencies: deque = field(default_factory=lambda: deque(maxlen=100))
    last_error: str = ""
    last_used: float = 0.0
    circuit_open: bool = False
    consecutive_failures: int = 0

    @property
    def id(self) -> str:
        return f"{self.provider}:{self.model}"

    @property
    def success_rate(self) -> float:
        total = self.total_success + self.total_failures
        return (self.total_success / total * 100) if total > 0 else 100.0

    @property
    def avg_latency_ms(self) -> float:
        if not self.latencies:
            return 0.0
        return sum(self.latencies) / len(self.latencies) * 1000

    @property
    def p95_latency_ms(self) -> float:
        if not self.latencies:
            return 0.0
        sorted_lats = sorted(self.latencies)
        idx = int(len(sorted_lats) * 0.95)
        return sorted_lats[min(idx, len(sorted_lats) - 1)] * 1000

    @property
    def is_available(self) -> bool:
        return self.enabled and not self.circuit_open and self.current_load < self.max_concurrent

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "provider": self.provider,
            "model": self.model,
            "enabled": self.enabled,
            "priority": self.priority,
            "current_load": self.current_load,
            "max_concurrent": self.max_concurrent,
            "total_calls": self.total_calls,
            "success_rate": round(self.success_rate, 1),
            "avg_latency_ms": round(self.avg_latency_ms, 1),
            "p95_latency_ms": round(self.p95_latency_ms, 1),
            "circuit_open": self.circuit_open,
            "last_error": self.last_error,
            "last_used": self.last_used,
            "total_tokens": self.total_tokens,
        }


@dataclass
class ExecutionResult:
    request_id: str
    provider: str
    model: str
    response: str
    latency_ms: float
    tokens_used: int
    success: bool
    error: str = ""
    strategy: str = "single"


@dataclass
class RaceResult:
    request_id: str
    winner: ExecutionResult | None
    all_results: list[ExecutionResult]
    strategy: str
    total_time_ms: float


# ─── Event Types ───────────────────────────────────────────────────────────

@dataclass
class LLMEvent:
    event_type: str   # "request_start", "request_end", "model_health", "race_result"
    timestamp: float
    data: dict

    def to_dict(self) -> dict:
        return {"type": self.event_type, "ts": self.timestamp, "data": self.data}


# ─── Main Engine ───────────────────────────────────────────────────────────

class MultiLLMEngine:
    """Manages concurrent LLM execution with live metrics and dashboard streaming."""

    def __init__(self):
        self.slots: Dict[str, ModelSlot] = {}
        self._event_listeners: list[Callable] = []
        self._request_log: deque = deque(maxlen=500)
        self._active_requests: Dict[str, dict] = {}
        self._task_queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self._initialized = False

    def initialize(self, orchestrator=None):
        """Load model slots from orchestrator registry."""
        if orchestrator is None:
            try:
                from core.model_orchestrator import model_orchestrator
                orchestrator = model_orchestrator
            except Exception:
                pass

        if orchestrator:
            for entry in getattr(orchestrator, "registry", []):
                provider = str(entry.get("type") or entry.get("provider") or "").strip().lower()
                model = str(entry.get("model") or "").strip()
                if provider and model:
                    slot_id = f"{provider}:{model}"
                    if slot_id not in self.slots:
                        self.slots[slot_id] = ModelSlot(
                            provider=provider,
                            model=model,
                            enabled=entry.get("enabled", True),
                            priority=entry.get("priority", 50),
                        )

            # Also add from providers dict
            for pname, pcfg in getattr(orchestrator, "providers", {}).items():
                model = str(pcfg.get("model") or "").strip()
                if model:
                    slot_id = f"{pname}:{model}"
                    if slot_id not in self.slots:
                        self.slots[slot_id] = ModelSlot(
                            provider=pname,
                            model=model,
                            enabled=True,
                            priority=pcfg.get("priority", 50),
                        )

        self._initialized = True
        logger.info(f"MultiLLMEngine initialized with {len(self.slots)} model slots")

    def add_event_listener(self, callback: Callable):
        """Register a callback for live events (dashboard WebSocket push)."""
        self._event_listeners.append(callback)

    def remove_event_listener(self, callback: Callable):
        if callback in self._event_listeners:
            self._event_listeners.remove(callback)

    async def _emit_event(self, event: LLMEvent):
        """Push event to all listeners (dashboard, logs, etc.)."""
        for listener in self._event_listeners:
            try:
                if asyncio.iscoroutinefunction(listener):
                    await listener(event)
                else:
                    listener(event)
            except Exception:
                pass

    # ─── Core Execution ────────────────────────────────────────────────

    async def execute_single(
        self,
        llm_client,
        prompt: str,
        provider: str,
        model: str,
        role: str = "inference",
        system_prompt: str | None = None,
        user_id: str = "local",
        temperature: float | None = None,
    ) -> ExecutionResult:
        """Execute a single LLM call with tracking."""
        request_id = f"req_{uuid.uuid4().hex[:8]}"
        slot_id = f"{provider}:{model}"
        slot = self.slots.get(slot_id)

        if slot:
            slot.current_load += 1

        await self._emit_event(LLMEvent(
            "request_start", time.time(),
            {"request_id": request_id, "provider": provider, "model": model, "role": role}
        ))

        start = time.perf_counter()
        try:
            cfg = {"type": provider, "provider": provider, "model": model}
            response = await llm_client.generate(
                prompt,
                system_prompt=system_prompt,
                model_config=cfg,
                role=role,
                user_id=user_id,
                temperature=temperature,
                strict_model_config=True,
                disable_collaboration=True,
            )
            elapsed = time.perf_counter() - start
            tokens_est = (len(prompt) + len(response)) // 4

            result = ExecutionResult(
                request_id=request_id,
                provider=provider,
                model=model,
                response=response,
                latency_ms=elapsed * 1000,
                tokens_used=tokens_est,
                success=True,
            )

            if slot:
                slot.total_calls += 1
                slot.total_success += 1
                slot.total_tokens += tokens_est
                slot.latencies.append(elapsed)
                slot.last_used = time.time()
                slot.consecutive_failures = 0

            await self._emit_event(LLMEvent(
                "request_end", time.time(),
                {"request_id": request_id, "provider": provider, "model": model,
                 "success": True, "latency_ms": round(elapsed * 1000, 1), "tokens": tokens_est}
            ))
            return result

        except Exception as exc:
            elapsed = time.perf_counter() - start
            result = ExecutionResult(
                request_id=request_id,
                provider=provider,
                model=model,
                response="",
                latency_ms=elapsed * 1000,
                tokens_used=0,
                success=False,
                error=str(exc),
            )

            if slot:
                slot.total_calls += 1
                slot.total_failures += 1
                slot.last_error = str(exc)[:200]
                slot.consecutive_failures += 1
                # Auto circuit-break after 3 consecutive failures
                if slot.consecutive_failures >= 3:
                    slot.circuit_open = True
                    logger.warning(f"Circuit breaker OPEN for {slot_id} after {slot.consecutive_failures} failures")

            await self._emit_event(LLMEvent(
                "request_end", time.time(),
                {"request_id": request_id, "provider": provider, "model": model,
                 "success": False, "error": str(exc)[:100], "latency_ms": round(elapsed * 1000, 1)}
            ))
            return result
        finally:
            if slot:
                slot.current_load = max(0, slot.current_load - 1)

    # ─── Race Mode ─────────────────────────────────────────────────────

    async def race(
        self,
        llm_client,
        prompt: str,
        role: str = "inference",
        system_prompt: str | None = None,
        user_id: str = "local",
        temperature: float | None = None,
        max_models: int = 3,
        timeout_s: float = 30.0,
    ) -> RaceResult:
        """
        Run same prompt on multiple models simultaneously.
        Returns the first successful response (fastest wins).
        """
        request_id = f"race_{uuid.uuid4().hex[:8]}"
        candidates = self._pick_race_candidates(max_models)

        if not candidates:
            return RaceResult(
                request_id=request_id, winner=None,
                all_results=[], strategy="race", total_time_ms=0
            )

        await self._emit_event(LLMEvent(
            "race_start", time.time(),
            {"request_id": request_id, "candidates": [s.id for s in candidates], "prompt_preview": prompt[:80]}
        ))

        start = time.perf_counter()
        tasks = []
        for slot in candidates:
            tasks.append(
                self.execute_single(
                    llm_client, prompt, slot.provider, slot.model,
                    role=role, system_prompt=system_prompt,
                    user_id=user_id, temperature=temperature,
                )
            )

        # Use asyncio.as_completed for true race behavior
        all_results: list[ExecutionResult] = []
        winner: ExecutionResult | None = None

        done_tasks = asyncio.as_completed(tasks, timeout=timeout_s)
        for coro in done_tasks:
            try:
                result = await coro
                all_results.append(result)
                if result.success and winner is None:
                    winner = result
                    # Don't break — let others finish for metrics
            except asyncio.TimeoutError:
                break
            except Exception:
                pass

        total_ms = (time.perf_counter() - start) * 1000

        race_result = RaceResult(
            request_id=request_id,
            winner=winner,
            all_results=all_results,
            strategy="race",
            total_time_ms=round(total_ms, 1),
        )

        await self._emit_event(LLMEvent(
            "race_end", time.time(),
            {
                "request_id": request_id,
                "winner": winner.provider + "/" + winner.model if winner else None,
                "winner_latency_ms": round(winner.latency_ms, 1) if winner else None,
                "total_participants": len(candidates),
                "successful": sum(1 for r in all_results if r.success),
                "total_time_ms": round(total_ms, 1),
            }
        ))

        self._request_log.append({
            "id": request_id, "strategy": "race", "ts": time.time(),
            "winner": winner.provider + "/" + winner.model if winner else None,
            "latency_ms": round(total_ms, 1),
            "models": len(candidates),
        })

        return race_result

    def _pick_race_candidates(self, max_models: int) -> list[ModelSlot]:
        """Pick best N available models for race."""
        available = [s for s in self.slots.values() if s.is_available]
        # Sort by: priority (lower=better), success_rate (higher=better), avg_latency (lower=better)
        available.sort(key=lambda s: (s.priority, -s.success_rate, s.avg_latency_ms))
        return available[:max_models]

    # ─── Parallel Task Decomposition ───────────────────────────────────

    async def parallel_execute(
        self,
        llm_client,
        tasks: list[dict],
        role: str = "inference",
        user_id: str = "local",
        timeout_s: float = 60.0,
    ) -> list[ExecutionResult]:
        """
        Execute multiple different prompts across available models in parallel.
        Each task: {"prompt": str, "system_prompt": str|None, "preferred_model": str|None}
        """
        available = [s for s in self.slots.values() if s.is_available]
        if not available:
            return []

        results: list[ExecutionResult] = []
        coros = []

        for i, task in enumerate(tasks):
            # Round-robin assign to available models
            slot = available[i % len(available)]
            coros.append(
                self.execute_single(
                    llm_client,
                    task["prompt"],
                    slot.provider,
                    slot.model,
                    role=role,
                    system_prompt=task.get("system_prompt"),
                    user_id=user_id,
                )
            )

        try:
            results = await asyncio.wait_for(
                asyncio.gather(*coros, return_exceptions=True),
                timeout=timeout_s,
            )
            # Filter out exceptions
            clean_results = []
            for r in results:
                if isinstance(r, ExecutionResult):
                    clean_results.append(r)
                elif isinstance(r, Exception):
                    clean_results.append(ExecutionResult(
                        request_id=f"err_{uuid.uuid4().hex[:6]}",
                        provider="unknown", model="unknown",
                        response="", latency_ms=0, tokens_used=0,
                        success=False, error=str(r),
                    ))
            return clean_results
        except asyncio.TimeoutError:
            return results if results else []

    # ─── Metrics & Health ──────────────────────────────────────────────

    def get_live_metrics(self) -> dict:
        """Return current state of all model slots for dashboard."""
        slots_data = []
        for slot in self.slots.values():
            slots_data.append(slot.to_dict())
        # Sort by priority
        slots_data.sort(key=lambda s: s.get("priority", 50))

        total_calls = sum(s.total_calls for s in self.slots.values())
        total_success = sum(s.total_success for s in self.slots.values())
        total_tokens = sum(s.total_tokens for s in self.slots.values())

        return {
            "models": slots_data,
            "summary": {
                "total_models": len(self.slots),
                "available_models": sum(1 for s in self.slots.values() if s.is_available),
                "total_calls": total_calls,
                "overall_success_rate": round(total_success / total_calls * 100, 1) if total_calls > 0 else 100.0,
                "total_tokens": total_tokens,
                "active_requests": sum(s.current_load for s in self.slots.values()),
            },
            "recent_requests": list(self._request_log)[-20:],
        }

    def get_model_health(self, slot_id: str) -> dict | None:
        slot = self.slots.get(slot_id)
        if not slot:
            return None
        return slot.to_dict()

    def reset_circuit_breaker(self, slot_id: str) -> bool:
        slot = self.slots.get(slot_id)
        if not slot:
            return False
        slot.circuit_open = False
        slot.consecutive_failures = 0
        logger.info(f"Circuit breaker reset for {slot_id}")
        return True

    def toggle_model(self, slot_id: str, enabled: bool) -> bool:
        slot = self.slots.get(slot_id)
        if not slot:
            return False
        slot.enabled = enabled
        logger.info(f"Model {slot_id} {'enabled' if enabled else 'disabled'}")
        return True

    def set_model_priority(self, slot_id: str, priority: int) -> bool:
        slot = self.slots.get(slot_id)
        if not slot:
            return False
        slot.priority = max(1, min(100, priority))
        return True

    # ─── Multitask Runner ────────────────────────────────────────────

    async def multitask_run(
        self,
        llm_client,
        sub_tasks: list[dict],
        user_id: str = "local",
        timeout_s: float = 120.0,
    ) -> dict:
        """
        Run multiple sub-tasks in parallel across available models.
        Each sub_task: {"id": str, "prompt": str, "role": str, "system_prompt": str|None}
        Returns: {"results": [...], "total_time_ms": float, "success_count": int}
        """
        if not sub_tasks:
            return {"results": [], "total_time_ms": 0, "success_count": 0}

        request_id = f"mt_{uuid.uuid4().hex[:8]}"
        available = [s for s in self.slots.values() if s.is_available]
        if not available:
            return {"results": [], "total_time_ms": 0, "success_count": 0, "error": "no_models_available"}

        await self._emit_event(LLMEvent(
            "multitask_start", time.time(),
            {"request_id": request_id, "task_count": len(sub_tasks)}
        ))

        start = time.perf_counter()
        coros = []

        for i, task in enumerate(sub_tasks):
            slot = available[i % len(available)]
            task_id = task.get("id", f"subtask_{i}")
            coros.append(
                self._run_subtask(
                    llm_client, task_id, task["prompt"],
                    slot.provider, slot.model,
                    role=task.get("role", "inference"),
                    system_prompt=task.get("system_prompt"),
                    user_id=user_id,
                )
            )

        try:
            results = await asyncio.wait_for(
                asyncio.gather(*coros, return_exceptions=True),
                timeout=timeout_s,
            )
        except asyncio.TimeoutError:
            results = []

        total_ms = (time.perf_counter() - start) * 1000
        clean_results = []
        for r in (results or []):
            if isinstance(r, dict):
                clean_results.append(r)
            elif isinstance(r, Exception):
                clean_results.append({"task_id": "unknown", "success": False, "error": str(r)})

        success_count = sum(1 for r in clean_results if r.get("success"))

        await self._emit_event(LLMEvent(
            "multitask_end", time.time(),
            {"request_id": request_id, "total": len(sub_tasks),
             "success": success_count, "total_time_ms": round(total_ms, 1)}
        ))

        self._request_log.append({
            "id": request_id, "strategy": "multitask", "ts": time.time(),
            "tasks": len(sub_tasks), "success": success_count,
            "latency_ms": round(total_ms, 1),
        })

        return {
            "request_id": request_id,
            "results": clean_results,
            "total_time_ms": round(total_ms, 1),
            "success_count": success_count,
            "total_tasks": len(sub_tasks),
        }

    async def _run_subtask(
        self, llm_client, task_id: str, prompt: str,
        provider: str, model: str,
        role: str = "inference",
        system_prompt: str | None = None,
        user_id: str = "local",
    ) -> dict:
        result = await self.execute_single(
            llm_client, prompt, provider, model,
            role=role, system_prompt=system_prompt, user_id=user_id,
        )
        return {
            "task_id": task_id,
            "provider": result.provider,
            "model": result.model,
            "success": result.success,
            "response": result.response[:1000] if result.success else "",
            "error": result.error if not result.success else "",
            "latency_ms": round(result.latency_ms, 1),
            "tokens": result.tokens_used,
        }


# ─── Singleton ─────────────────────────────────────────────────────────────

_engine: Optional[MultiLLMEngine] = None


def get_multi_llm_engine() -> MultiLLMEngine:
    global _engine
    if _engine is None:
        _engine = MultiLLMEngine()
    return _engine
