"""
core/multi_agent/parallel_executor.py
───────────────────────────────────────────────────────────────────────────────
Parallel Agent Executor

Runs multiple specialist tasks concurrently using asyncio.TaskGroup.
Integrates with:
  - AgentMessageBus for inter-agent communication
  - AgentTaskTracker for lifecycle tracking
  - OrchestratorBridge for metrics recording

Design:
  - DAG-aware: respects precondition dependencies between steps
  - Bounded concurrency via asyncio.Semaphore
  - Graceful partial failure: collects results from completed tasks
  - Timeout per task with configurable default
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable

from utils.logger import get_logger

logger = get_logger("parallel_executor")

_DEFAULT_CONCURRENCY = 4
_DEFAULT_TASK_TIMEOUT_S = 120


@dataclass(slots=True)
class ParallelTask:
    """A unit of work for parallel execution."""
    task_id: str
    owner: str  # specialist key
    coro_factory: Callable[[], Awaitable[Any]]  # 0-arg async callable
    depends_on: list[str] = field(default_factory=list)
    timeout_s: float = _DEFAULT_TASK_TIMEOUT_S


@dataclass(slots=True)
class TaskResult:
    """Result of a parallel task execution."""
    task_id: str
    owner: str
    success: bool
    result: Any = None
    error: str = ""
    duration_s: float = 0.0


class ParallelExecutor:
    """Execute multiple specialist tasks concurrently with dependency awareness."""

    def __init__(self, max_concurrency: int = _DEFAULT_CONCURRENCY) -> None:
        self._semaphore = asyncio.Semaphore(max_concurrency)

    async def execute(self, tasks: list[ParallelTask]) -> list[TaskResult]:
        """Execute tasks respecting dependencies. Returns results in input order."""
        if not tasks:
            return []

        task_map = {t.task_id: t for t in tasks}
        results: dict[str, TaskResult] = {}
        completed_events: dict[str, asyncio.Event] = {
            t.task_id: asyncio.Event() for t in tasks
        }

        async def _run_one(pt: ParallelTask) -> TaskResult:
            # Wait for dependencies
            for dep_id in pt.depends_on:
                if dep_id in completed_events:
                    await completed_events[dep_id].wait()

            async with self._semaphore:
                t0 = time.time()
                try:
                    result = await asyncio.wait_for(
                        pt.coro_factory(),
                        timeout=pt.timeout_s,
                    )
                    tr = TaskResult(
                        task_id=pt.task_id,
                        owner=pt.owner,
                        success=True,
                        result=result,
                        duration_s=round(time.time() - t0, 3),
                    )
                except asyncio.TimeoutError:
                    tr = TaskResult(
                        task_id=pt.task_id,
                        owner=pt.owner,
                        success=False,
                        error="timeout",
                        duration_s=round(time.time() - t0, 3),
                    )
                except Exception as exc:
                    tr = TaskResult(
                        task_id=pt.task_id,
                        owner=pt.owner,
                        success=False,
                        error=str(exc)[:200],
                        duration_s=round(time.time() - t0, 3),
                    )

            results[pt.task_id] = tr
            completed_events[pt.task_id].set()
            return tr

        # Launch all tasks concurrently — dependency waiting is internal
        coros = [_run_one(t) for t in tasks]
        await asyncio.gather(*coros, return_exceptions=True)

        # Return in input order
        return [results.get(t.task_id, TaskResult(
            task_id=t.task_id, owner=t.owner, success=False, error="not_started",
        )) for t in tasks]

    async def execute_simple(
        self,
        coros: list[tuple[str, Callable[[], Awaitable[Any]]]],
        timeout_s: float = _DEFAULT_TASK_TIMEOUT_S,
    ) -> list[TaskResult]:
        """Simplified execution — no dependencies, just parallel tasks.

        Args:
            coros: list of (task_id, async_factory) tuples
            timeout_s: timeout per task
        """
        tasks = [
            ParallelTask(task_id=tid, owner=tid, coro_factory=fn, timeout_s=timeout_s)
            for tid, fn in coros
        ]
        return await self.execute(tasks)


__all__ = ["ParallelExecutor", "ParallelTask", "TaskResult"]
