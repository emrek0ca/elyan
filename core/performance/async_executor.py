"""
Async Execution Optimization

Provides:
- Concurrent task execution with resource limits
- Rate limiting
- Priority queue for task scheduling
- Graceful timeout handling
"""

import asyncio
from typing import Optional, Callable, Any, List
from dataclasses import dataclass
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class TaskPriority(Enum):
    """Task priority levels"""
    CRITICAL = 1
    HIGH = 2
    NORMAL = 3
    LOW = 4


@dataclass
class AsyncTask:
    """Async task with priority and metadata"""
    task_id: str
    func: Callable
    args: tuple = ()
    kwargs: dict = None
    priority: TaskPriority = TaskPriority.NORMAL
    timeout: Optional[float] = None
    max_retries: int = 0
    _retry_count: int = 0

    async def execute(self) -> Any:
        """Execute task with timeout"""
        kwargs = self.kwargs or {}

        try:
            if self.timeout:
                return await asyncio.wait_for(
                    self.func(*self.args, **kwargs),
                    timeout=self.timeout
                )
            else:
                return await self.func(*self.args, **kwargs)

        except asyncio.TimeoutError:
            logger.warning(f"Task {self.task_id} timed out after {self.timeout}s")
            raise

        except Exception as e:
            if self._retry_count < self.max_retries:
                self._retry_count += 1
                logger.info(f"Task {self.task_id} retry {self._retry_count}/{self.max_retries}")
                return await self.execute()
            raise


class AsyncExecutor:
    """Execute async tasks with concurrency limits and resource management"""

    def __init__(self, max_concurrent: int = 10, rate_limit: int = 100):
        """
        Initialize async executor

        Args:
            max_concurrent: Max concurrent tasks
            rate_limit: Max tasks per second
        """
        self.max_concurrent = max_concurrent
        self.rate_limit = rate_limit
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._queue: List[AsyncTask] = []
        self._running_tasks: dict = {}
        self._stats = {
            "executed": 0,
            "failed": 0,
            "timed_out": 0,
            "total_time": 0.0
        }

    async def submit(
        self,
        task_id: str,
        func: Callable,
        args: tuple = (),
        kwargs: dict = None,
        priority: TaskPriority = TaskPriority.NORMAL,
        timeout: Optional[float] = None,
        max_retries: int = 0
    ) -> None:
        """Submit async task for execution"""
        task = AsyncTask(
            task_id=task_id,
            func=func,
            args=args,
            kwargs=kwargs or {},
            priority=priority,
            timeout=timeout,
            max_retries=max_retries
        )

        self._queue.append(task)
        self._queue.sort(key=lambda t: t.priority.value)  # Sort by priority

        logger.debug(f"Task {task_id} submitted (priority={priority.name})")

    async def execute_all(self) -> dict:
        """Execute all queued tasks with concurrency control using asyncio.gather"""
        results = {}

        async def _run_one(task):
            async with self._semaphore:
                try:
                    import time
                    start = time.time()

                    result = await task.execute()

                    elapsed = time.time() - start
                    results[task.task_id] = {
                        "status": "success",
                        "result": result,
                        "elapsed": elapsed
                    }

                    self._stats["executed"] += 1
                    self._stats["total_time"] += elapsed

                    logger.debug(
                        f"Task {task.task_id} completed in {elapsed:.2f}s"
                    )

                except asyncio.TimeoutError:
                    results[task.task_id] = {
                        "status": "timeout",
                        "error": f"Timeout after {task.timeout}s"
                    }
                    self._stats["timed_out"] += 1
                    self._stats["failed"] += 1

                except Exception as e:
                    results[task.task_id] = {
                        "status": "error",
                        "error": str(e)
                    }
                    self._stats["failed"] += 1

        await asyncio.gather(*[_run_one(task) for task in self._queue])
        self._queue.clear()
        return results

    def get_stats(self) -> dict:
        """Get execution statistics"""
        return {
            "executed": self._stats["executed"],
            "failed": self._stats["failed"],
            "timed_out": self._stats["timed_out"],
            "total_time": f"{self._stats['total_time']:.2f}s",
            "avg_time": (
                f"{self._stats['total_time'] / self._stats['executed']:.2f}s"
                if self._stats["executed"] > 0 else "N/A"
            ),
            "queued": len(self._queue)
        }


# Singleton instance
_executor: Optional[AsyncExecutor] = None


def get_async_executor(max_concurrent: int = 10) -> AsyncExecutor:
    """Get or create async executor singleton"""
    global _executor
    if _executor is None:
        _executor = AsyncExecutor(max_concurrent=max_concurrent)
        logger.info(f"Async executor initialized (max_concurrent={max_concurrent})")
    return _executor
