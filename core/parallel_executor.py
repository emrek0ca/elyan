"""
Parallel Task Executor for elyan Bot
====================================
Executes independent tasks concurrently with dependency awareness,
resource management, and comprehensive progress tracking.

Features:
- Asyncio-based concurrent execution
- Dependency graph analysis
- Task batching and prioritization
- Resource limits per task
- Timeout enforcement
- Progress tracking and reporting
- Failure isolation (one failure doesn't cascade)
- Load balancing across worker pool
"""

import asyncio
import time
import logging
import traceback
from typing import Dict, List, Set, Tuple, Any, Optional, Callable, Coroutine
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict
import threading

logger = logging.getLogger(__name__)


class TaskStatus(Enum):
    """Task execution status."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"


@dataclass
class TaskMetrics:
    """Metrics for a single task execution."""
    task_id: str
    status: TaskStatus = TaskStatus.PENDING
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    duration: float = 0.0
    retries: int = 0
    error: Optional[str] = None
    memory_used: float = 0.0

    @property
    def is_complete(self) -> bool:
        """Check if task is complete (success or failure)."""
        return self.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED)


@dataclass
class ExecutionTask:
    """Represents a single task in the execution plan."""
    task_id: str
    func: Callable[..., Coroutine[Any, Any, Any]]
    args: Tuple = ()
    kwargs: Dict[str, Any] = field(default_factory=dict)
    dependencies: List[str] = field(default_factory=list)
    priority: int = 0  # Higher = more important
    timeout: Optional[float] = None
    max_retries: int = 0
    resource_limits: Dict[str, float] = field(default_factory=dict)

    async def execute(self) -> Any:
        """Execute the task function."""
        return await self.func(*self.args, **self.kwargs)


class DependencyGraph:
    """Analyzes task dependencies and identifies parallelizable groups."""

    def __init__(self):
        self.tasks: Dict[str, ExecutionTask] = {}
        self.graph: Dict[str, Set[str]] = defaultdict(set)  # task_id -> dependent tasks
        self.reverse_graph: Dict[str, Set[str]] = defaultdict(set)  # task_id -> dependencies

    def add_task(self, task: ExecutionTask) -> None:
        """Add a task to the dependency graph."""
        self.tasks[task.task_id] = task
        for dep in task.dependencies:
            self.graph[dep].add(task.task_id)
            self.reverse_graph[task.task_id].add(dep)

    def get_parallel_groups(self) -> List[List[str]]:
        """
        Identify groups of tasks that can be executed in parallel.
        Returns list of task ID groups (each group executes sequentially,
        but groups execute in parallel).
        """
        visited: Set[str] = set()
        groups: List[List[str]] = []

        # Topological sort with parallelization
        in_degree = {task_id: len(self.reverse_graph[task_id])
                     for task_id in self.tasks}
        queue = [task_id for task_id in self.tasks if in_degree[task_id] == 0]

        while queue:
            # Current group of tasks that can run in parallel
            current_group = sorted(queue, key=lambda t: -self.tasks[t].priority)
            groups.append(current_group)

            # Process next level
            next_queue = []
            for task_id in current_group:
                visited.add(task_id)
                for dependent in self.graph[task_id]:
                    in_degree[dependent] -= 1
                    if in_degree[dependent] == 0:
                        next_queue.append(dependent)

            queue = next_queue

        return groups

    def validate(self) -> Tuple[bool, str]:
        """Check for circular dependencies."""
        visited: Set[str] = set()
        rec_stack: Set[str] = set()

        def has_cycle(node: str) -> bool:
            visited.add(node)
            rec_stack.add(node)

            for neighbor in self.reverse_graph.get(node, set()):
                if neighbor not in visited:
                    if has_cycle(neighbor):
                        return True
                elif neighbor in rec_stack:
                    return True

            rec_stack.remove(node)
            return False

        for task_id in self.tasks:
            if task_id not in visited:
                if has_cycle(task_id):
                    return False, f"Circular dependency detected involving {task_id}"

        return True, "No circular dependencies found"


class ParallelExecutor:
    """
    Executes tasks with dependencies in parallel where possible.

    Usage:
        executor = ParallelExecutor(max_concurrent=4)
        executor.add_task("task1", my_func1, args=(a, b))
        executor.add_task("task2", my_func2, args=(c,), dependencies=["task1"])
        results = executor.execute()
    """

    def __init__(
        self,
        max_concurrent: int = 4,
        timeout_per_task: Optional[float] = None,
        timeout_total: Optional[float] = None,
        allow_partial_failure: bool = True
    ):
        self.max_concurrent = max(1, max_concurrent)
        self.timeout_per_task = timeout_per_task
        self.timeout_total = timeout_total
        self.allow_partial_failure = allow_partial_failure

        self.graph = DependencyGraph()
        self.metrics: Dict[str, TaskMetrics] = {}
        self.results: Dict[str, Any] = {}
        self.start_time: Optional[float] = None
        self._lock = threading.Lock()

    def add_task(
        self,
        task_id: str,
        func: Callable[..., Coroutine[Any, Any, Any]],
        args: Tuple = (),
        kwargs: Dict[str, Any] = None,
        dependencies: List[str] = None,
        priority: int = 0,
        timeout: Optional[float] = None,
        max_retries: int = 0
    ) -> None:
        """Add a task to the execution plan."""
        if task_id in self.graph.tasks:
            raise ValueError(f"Task {task_id} already exists")

        task = ExecutionTask(
            task_id=task_id,
            func=func,
            args=args,
            kwargs=kwargs or {},
            dependencies=dependencies or [],
            priority=priority,
            timeout=timeout or self.timeout_per_task,
            max_retries=max_retries
        )

        self.graph.add_task(task)
        self.metrics[task_id] = TaskMetrics(task_id=task_id)

    def get_task(self, task_id: str) -> ExecutionTask:
        """Retrieve a task by ID."""
        if task_id not in self.graph.tasks:
            raise KeyError(f"Task {task_id} not found")
        return self.graph.tasks[task_id]

    async def _execute_with_retry(
        self,
        task: ExecutionTask,
        semaphore: asyncio.Semaphore
    ) -> Tuple[str, Any, Optional[str]]:
        """Execute a task with retry logic and timeout."""
        task_id = task.task_id
        metrics = self.metrics[task_id]

        for attempt in range(task.max_retries + 1):
            try:
                metrics.status = TaskStatus.RUNNING
                metrics.start_time = time.time()

                # Wait for semaphore to control concurrency
                async with semaphore:
                    if task.timeout:
                        result = await asyncio.wait_for(
                            task.execute(),
                            timeout=task.timeout
                        )
                    else:
                        result = await task.execute()

                metrics.status = TaskStatus.COMPLETED
                metrics.end_time = time.time()
                metrics.duration = metrics.end_time - metrics.start_time

                logger.info(
                    f"Task {task_id} completed in {metrics.duration:.2f}s "
                    f"(attempt {attempt + 1}/{task.max_retries + 1})"
                )

                return task_id, result, None

            except asyncio.TimeoutError:
                metrics.retries = attempt + 1
                error_msg = f"Task {task_id} timeout after {task.timeout}s"
                if attempt < task.max_retries:
                    logger.warning(f"{error_msg}, retrying... (attempt {attempt + 2})")
                    await asyncio.sleep(0.1 * (2 ** attempt))  # Exponential backoff
                else:
                    metrics.status = TaskStatus.FAILED
                    metrics.error = error_msg
                    metrics.end_time = time.time()
                    metrics.duration = metrics.end_time - metrics.start_time
                    return task_id, None, error_msg

            except Exception as e:
                error_msg = f"{type(e).__name__}: {str(e)}"
                metrics.retries = attempt + 1

                if attempt < task.max_retries:
                    logger.warning(
                        f"Task {task_id} failed: {error_msg}, "
                        f"retrying... (attempt {attempt + 2})"
                    )
                    await asyncio.sleep(0.1 * (2 ** attempt))
                else:
                    metrics.status = TaskStatus.FAILED
                    metrics.error = error_msg
                    metrics.end_time = time.time()
                    metrics.duration = metrics.end_time - metrics.start_time
                    logger.error(f"Task {task_id} failed: {error_msg}")
                    return task_id, None, error_msg

        return task_id, None, "Max retries exceeded"

    async def _execute_group(
        self,
        task_ids: List[str],
        semaphore: asyncio.Semaphore,
        completed_tasks: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute a group of independent tasks in parallel."""
        tasks = [
            self._execute_with_retry(self.graph.tasks[task_id], semaphore)
            for task_id in task_ids
        ]

        results = {}
        for task_id, result, error in await asyncio.gather(*tasks, return_exceptions=False):
            if error:
                if not self.allow_partial_failure:
                    raise RuntimeError(f"Task {task_id} failed: {error}")
                results[task_id] = None
            else:
                results[task_id] = result

        return results

    async def execute_async(self) -> Dict[str, Any]:
        """
        Execute all tasks respecting dependencies.
        Returns dict of task_id -> result.
        """
        # Validate graph
        valid, message = self.graph.validate()
        if not valid:
            raise ValueError(message)

        self.start_time = time.time()
        semaphore = asyncio.Semaphore(self.max_concurrent)
        completed_tasks: Dict[str, Any] = {}

        # Get execution groups (tasks that can run in parallel)
        groups = self.graph.get_parallel_groups()

        try:
            for group_idx, group in enumerate(groups):
                logger.info(f"Executing group {group_idx + 1}/{len(groups)} ({len(group)} tasks)")

                # Check timeout
                if self.timeout_total:
                    elapsed = time.time() - self.start_time
                    if elapsed > self.timeout_total:
                        raise TimeoutError(f"Total execution timeout exceeded: {elapsed}s > {self.timeout_total}s")

                # Execute group
                group_results = await self._execute_group(group, semaphore, completed_tasks)
                completed_tasks.update(group_results)
                self.results.update(group_results)

        except Exception as e:
            logger.error(f"Execution failed: {e}")
            if not self.allow_partial_failure:
                raise

        return self.results

    def execute(self) -> Dict[str, Any]:
        """Execute all tasks (blocking)."""
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        return loop.run_until_complete(self.execute_async())

    def get_metrics(self, task_id: Optional[str] = None) -> Dict[str, Any]:
        """Get execution metrics."""
        if task_id:
            if task_id not in self.metrics:
                raise KeyError(f"No metrics for task {task_id}")
            m = self.metrics[task_id]
            return {
                "task_id": m.task_id,
                "status": m.status.value,
                "duration": m.duration,
                "retries": m.retries,
                "error": m.error
            }

        # All metrics
        all_metrics = {}
        total_duration = 0
        for task_id, m in self.metrics.items():
            all_metrics[task_id] = {
                "status": m.status.value,
                "duration": m.duration,
                "retries": m.retries,
                "error": m.error
            }
            if m.status == TaskStatus.COMPLETED:
                total_duration = max(total_duration, m.duration)

        return {
            "total_tasks": len(self.metrics),
            "completed": sum(1 for m in self.metrics.values() if m.status == TaskStatus.COMPLETED),
            "failed": sum(1 for m in self.metrics.values() if m.status == TaskStatus.FAILED),
            "total_wall_time": time.time() - self.start_time if self.start_time else 0,
            "critical_path_time": total_duration,
            "tasks": all_metrics
        }

    def get_progress(self) -> Dict[str, Any]:
        """Get execution progress."""
        completed = sum(1 for m in self.metrics.values() if m.is_complete)
        total = len(self.metrics)

        return {
            "completed_tasks": completed,
            "total_tasks": total,
            "percentage": (completed / total * 100) if total > 0 else 0,
            "status_breakdown": {
                "pending": sum(1 for m in self.metrics.values() if m.status == TaskStatus.PENDING),
                "running": sum(1 for m in self.metrics.values() if m.status == TaskStatus.RUNNING),
                "completed": sum(1 for m in self.metrics.values() if m.status == TaskStatus.COMPLETED),
                "failed": sum(1 for m in self.metrics.values() if m.status == TaskStatus.FAILED),
            }
        }

    def estimate_remaining_time(self) -> Optional[float]:
        """Estimate time remaining based on task metrics."""
        if not self.start_time:
            return None

        completed_metrics = [m for m in self.metrics.values() if m.status == TaskStatus.COMPLETED]
        if not completed_metrics:
            return None

        avg_duration = sum(m.duration for m in completed_metrics) / len(completed_metrics)
        remaining_tasks = sum(1 for m in self.metrics.values()
                             if m.status in (TaskStatus.PENDING, TaskStatus.BLOCKED))

        return avg_duration * (remaining_tasks / self.max_concurrent)


def create_executor(
    max_concurrent: int = 4,
    timeout_per_task: Optional[float] = 30.0,
    timeout_total: Optional[float] = 300.0,
    allow_partial_failure: bool = True
) -> ParallelExecutor:
    """Factory function to create a ParallelExecutor."""
    return ParallelExecutor(
        max_concurrent=max_concurrent,
        timeout_per_task=timeout_per_task,
        timeout_total=timeout_total,
        allow_partial_failure=allow_partial_failure
    )
