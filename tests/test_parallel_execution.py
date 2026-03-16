"""
Tests for Parallel Execution System
====================================
"""

import asyncio
import pytest
import time
from unittest.mock import Mock, AsyncMock

from core.parallel_executor import (
    ParallelExecutor,
    ExecutionTask,
    DependencyGraph,
    TaskStatus,
    create_executor
)


class TestExecutionTask:
    """Tests for ExecutionTask."""

    @pytest.mark.asyncio
    async def test_simple_task_execution(self):
        """Test executing a simple async task."""
        async def dummy_task(x, y):
            await asyncio.sleep(0.01)
            return x + y

        task = ExecutionTask(
            task_id="test",
            func=dummy_task,
            args=(1, 2)
        )

        result = await task.execute()
        assert result == 3

    @pytest.mark.asyncio
    async def test_task_with_kwargs(self):
        """Test task execution with keyword arguments."""
        async def dummy_task(x, y=10):
            return x * y

        task = ExecutionTask(
            task_id="test",
            func=dummy_task,
            args=(2,),
            kwargs={"y": 5}
        )

        result = await task.execute()
        assert result == 10


class TestDependencyGraph:
    """Tests for DependencyGraph."""

    def test_add_task(self):
        """Test adding tasks to graph."""
        graph = DependencyGraph()

        async def dummy(): pass

        task = ExecutionTask(
            task_id="task1",
            func=dummy,
            dependencies=[]
        )
        graph.add_task(task)

        assert "task1" in graph.tasks
        assert len(graph.tasks) == 1

    def test_simple_dependency(self):
        """Test simple task dependency."""
        graph = DependencyGraph()

        async def dummy(): pass

        task1 = ExecutionTask(task_id="task1", func=dummy, dependencies=[])
        task2 = ExecutionTask(task_id="task2", func=dummy, dependencies=["task1"])

        graph.add_task(task1)
        graph.add_task(task2)

        # task1 should have task2 as dependent
        assert "task2" in graph.graph["task1"]
        # task2 should have task1 as dependency
        assert "task1" in graph.reverse_graph["task2"]

    def test_get_parallel_groups_no_dependencies(self):
        """Test identifying parallel groups with no dependencies."""
        graph = DependencyGraph()

        async def dummy(): pass

        for i in range(3):
            task = ExecutionTask(task_id=f"task{i}", func=dummy, dependencies=[])
            graph.add_task(task)

        groups = graph.get_parallel_groups()

        # All tasks can run in parallel
        assert len(groups) == 1
        assert len(groups[0]) == 3

    def test_get_parallel_groups_with_dependencies(self):
        """Test identifying parallel groups with dependencies."""
        graph = DependencyGraph()

        async def dummy(): pass

        task1 = ExecutionTask(task_id="task1", func=dummy, dependencies=[])
        task2 = ExecutionTask(task_id="task2", func=dummy, dependencies=["task1"])
        task3 = ExecutionTask(task_id="task3", func=dummy, dependencies=["task1"])

        graph.add_task(task1)
        graph.add_task(task2)
        graph.add_task(task3)

        groups = graph.get_parallel_groups()

        # task1 first, then task2 and task3 in parallel
        assert len(groups) >= 2
        assert "task1" in groups[0]

    def test_circular_dependency_detection(self):
        """Test detection of circular dependencies."""
        graph = DependencyGraph()

        async def dummy(): pass

        task1 = ExecutionTask(task_id="task1", func=dummy, dependencies=["task2"])
        task2 = ExecutionTask(task_id="task2", func=dummy, dependencies=["task1"])

        graph.add_task(task1)
        graph.add_task(task2)

        valid, message = graph.validate()
        assert not valid
        assert "circular" in message.lower()

    def test_validation_success(self):
        """Test successful validation."""
        graph = DependencyGraph()

        async def dummy(): pass

        task1 = ExecutionTask(task_id="task1", func=dummy, dependencies=[])
        task2 = ExecutionTask(task_id="task2", func=dummy, dependencies=["task1"])

        graph.add_task(task1)
        graph.add_task(task2)

        valid, message = graph.validate()
        assert valid


class TestParallelExecutor:
    """Tests for ParallelExecutor."""

    @pytest.mark.asyncio
    async def test_simple_execution(self):
        """Test simple task execution."""
        async def task1():
            await asyncio.sleep(0.01)
            return "result1"

        executor = create_executor(max_concurrent=2)
        executor.add_task("t1", task1)

        results = await executor.execute_async()

        assert "t1" in results
        assert results["t1"] == "result1"

    @pytest.mark.asyncio
    async def test_parallel_execution(self):
        """Test parallel execution of independent tasks."""
        call_times = []

        async def task(task_id):
            call_times.append((task_id, time.time()))
            await asyncio.sleep(0.05)
            return f"result_{task_id}"

        executor = create_executor(max_concurrent=3)
        executor.add_task("t1", task, args=("t1",))
        executor.add_task("t2", task, args=("t2",))
        executor.add_task("t3", task, args=("t3",))

        start = time.time()
        results = await executor.execute_async()
        elapsed = time.time() - start

        # All tasks should complete
        assert len(results) == 3
        # Parallel execution should be faster than sequential (3 * 0.05 = 0.15)
        assert elapsed < 0.12

    @pytest.mark.asyncio
    async def test_task_dependencies(self):
        """Test tasks with dependencies."""
        execution_order = []

        async def task1():
            execution_order.append("t1")
            await asyncio.sleep(0.01)
            return "result1"

        async def task2():
            execution_order.append("t2")
            return "result2"

        executor = create_executor()
        executor.add_task("t1", task1)
        executor.add_task("t2", task2, dependencies=["t1"])

        results = await executor.execute_async()

        # task1 should execute before task2
        assert execution_order.index("t1") < execution_order.index("t2")
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_task_timeout(self):
        """Test task timeout handling."""
        async def slow_task():
            await asyncio.sleep(1.0)
            return "result"

        executor = create_executor(timeout_per_task=0.1)
        executor.add_task("slow", slow_task)

        results = await executor.execute_async()

        # Task should timeout
        assert results["slow"] is None
        metrics = executor.get_metrics("slow")
        assert metrics["status"] == "failed"
        assert "timeout" in metrics["error"].lower()

    @pytest.mark.asyncio
    async def test_task_retry(self):
        """Test task retry logic."""
        call_count = [0]

        async def flaky_task():
            call_count[0] += 1
            if call_count[0] < 2:
                raise ValueError("Temporary failure")
            return "success"

        executor = create_executor()
        executor.add_task("flaky", flaky_task, max_retries=2)

        results = await executor.execute_async()

        # Task should succeed after retry
        assert results["flaky"] == "success"
        metrics = executor.get_metrics("flaky")
        assert metrics["retries"] >= 1

    @pytest.mark.asyncio
    async def test_metrics_collection(self):
        """Test metrics collection."""
        async def task1():
            await asyncio.sleep(0.02)
            return "result"

        executor = create_executor()
        executor.add_task("t1", task1)

        await executor.execute_async()

        metrics = executor.get_metrics()
        assert metrics["total_tasks"] == 1
        assert metrics["completed"] == 1

    @pytest.mark.asyncio
    async def test_progress_tracking(self):
        """Test progress tracking."""
        async def task():
            await asyncio.sleep(0.01)
            return "result"

        executor = create_executor()
        for i in range(5):
            executor.add_task(f"t{i}", task)

        # Check initial progress
        progress = executor.get_progress()
        assert progress["total_tasks"] == 5
        assert progress["completed_tasks"] == 0

        # Execute
        await executor.execute_async()

        # Check final progress
        progress = executor.get_progress()
        assert progress["completed_tasks"] == 5
        assert progress["percentage"] == 100.0

    @pytest.mark.asyncio
    async def test_error_handling_allow_partial(self):
        """Test error handling with allow_partial_failure=True."""
        async def failing_task():
            raise ValueError("Task failed")

        async def successful_task():
            return "success"

        executor = create_executor(allow_partial_failure=True)
        executor.add_task("fail", failing_task)
        executor.add_task("success", successful_task)

        results = await executor.execute_async()

        # Both results should be present
        assert "fail" in results
        assert "success" in results
        assert results["success"] == "success"

    @pytest.mark.asyncio
    async def test_error_handling_strict(self):
        """Test error handling with allow_partial_failure=False."""
        async def failing_task():
            raise ValueError("Task failed")

        executor = create_executor(allow_partial_failure=False)
        executor.add_task("fail", failing_task)

        with pytest.raises(RuntimeError):
            await executor.execute_async()

    @pytest.mark.asyncio
    async def test_total_timeout(self):
        """Test total execution timeout."""
        async def task():
            await asyncio.sleep(0.1)
            return "result"

        executor = create_executor(timeout_total=0.05)
        for i in range(5):
            executor.add_task(f"t{i}", task)

        with pytest.raises(TimeoutError):
            await executor.execute_async()

    @pytest.mark.asyncio
    async def test_max_concurrent_limit(self):
        """Test that max_concurrent is respected."""
        concurrent_count = [0]
        max_concurrent_seen = [0]

        async def task():
            concurrent_count[0] += 1
            max_concurrent_seen[0] = max(max_concurrent_seen[0], concurrent_count[0])
            await asyncio.sleep(0.02)
            concurrent_count[0] -= 1

        executor = create_executor(max_concurrent=2)
        for i in range(6):
            executor.add_task(f"t{i}", task)

        await executor.execute_async()

        # Max concurrent should not exceed limit
        assert max_concurrent_seen[0] <= 2

    def test_factory_function(self):
        """Test factory function."""
        executor = create_executor(
            max_concurrent=8,
            timeout_per_task=30.0,
            timeout_total=300.0
        )

        assert executor.max_concurrent == 8
        assert executor.timeout_per_task == 30.0
        assert executor.timeout_total == 300.0

    @pytest.mark.asyncio
    async def test_estimated_remaining_time(self):
        """Test estimated remaining time calculation."""
        async def task():
            await asyncio.sleep(0.02)
            return "result"

        executor = create_executor()
        for i in range(5):
            executor.add_task(f"t{i}", task)

        # Start execution in background
        task_handle = asyncio.create_task(executor.execute_async())

        # Allow some tasks to complete
        await asyncio.sleep(0.05)

        # Get estimate
        estimate = executor.estimate_remaining_time()
        assert estimate is not None
        assert estimate > 0

        await task_handle

    @pytest.mark.asyncio
    async def test_complex_dependency_graph(self):
        """Test complex dependency graph execution."""
        execution_order = []

        async def task(task_id):
            execution_order.append(task_id)
            await asyncio.sleep(0.01)
            return f"result_{task_id}"

        executor = create_executor(max_concurrent=3)

        # Create complex graph:
        # t1 -> t2 -> t4
        # t1 -> t3 -> t4
        executor.add_task("t1", task, args=("t1",))
        executor.add_task("t2", task, args=("t2",), dependencies=["t1"])
        executor.add_task("t3", task, args=("t3",), dependencies=["t1"])
        executor.add_task("t4", task, args=("t4",), dependencies=["t2", "t3"])

        results = await executor.execute_async()

        # Verify all tasks completed
        assert len(results) == 4

        # Verify order constraints
        assert execution_order.index("t1") < execution_order.index("t2")
        assert execution_order.index("t1") < execution_order.index("t3")
        assert execution_order.index("t2") < execution_order.index("t4")
        assert execution_order.index("t3") < execution_order.index("t4")


class TestParallelExecutorSpeedup:
    """Tests for verifying parallelization speedup."""

    @pytest.mark.asyncio
    async def test_2x_speedup_for_independent_tasks(self):
        """Verify 2x speedup for independent IO-bound tasks."""
        async def io_task():
            await asyncio.sleep(0.1)
            return "result"

        # Serial execution
        start = time.time()
        for _ in range(2):
            await io_task()
        serial_time = time.time() - start

        # Parallel execution
        executor = create_executor(max_concurrent=2)
        executor.add_task("t1", io_task)
        executor.add_task("t2", io_task)

        start = time.time()
        await executor.execute_async()
        parallel_time = time.time() - start

        # Should see significant speedup
        speedup = serial_time / parallel_time
        assert speedup > 1.5  # At least 1.5x speedup

    @pytest.mark.asyncio
    async def test_performance_with_dependencies(self):
        """Test that dependencies don't block unrelated tasks."""
        results = {"concurrent_tasks": 0, "max_concurrent": 0}

        async def task(task_id, duration):
            results["concurrent_tasks"] += 1
            results["max_concurrent"] = max(results["max_concurrent"], results["concurrent_tasks"])
            await asyncio.sleep(duration)
            results["concurrent_tasks"] -= 1
            return f"result_{task_id}"

        executor = create_executor(max_concurrent=3)

        # t1: 0.05s
        # t2: depends on t1
        # t3, t4, t5: independent
        executor.add_task("t1", task, args=("t1", 0.05))
        executor.add_task("t2", task, args=("t2", 0.01), dependencies=["t1"])
        executor.add_task("t3", task, args=("t3", 0.05))
        executor.add_task("t4", task, args=("t4", 0.05))
        executor.add_task("t5", task, args=("t5", 0.05))

        await executor.execute_async()

        # t1, t3, t4, t5 should run concurrently
        assert results["max_concurrent"] >= 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
