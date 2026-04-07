"""Tests for ParallelExecutor."""

import asyncio
import pytest
from core.multi_agent.parallel_executor import ParallelExecutor, ParallelTask


@pytest.mark.asyncio
async def test_simple_parallel():
    executor = ParallelExecutor(max_concurrency=4)
    results = await executor.execute_simple([
        ("a", lambda: asyncio.sleep(0.01, result="A")),
        ("b", lambda: asyncio.sleep(0.01, result="B")),
    ])
    assert len(results) == 2
    assert all(r.success for r in results)
    assert results[0].result == "A"
    assert results[1].result == "B"


@pytest.mark.asyncio
async def test_dependency_ordering():
    order = []

    async def step_a():
        order.append("a")
        return "A"

    async def step_b():
        order.append("b")
        return "B"

    executor = ParallelExecutor()
    results = await executor.execute([
        ParallelTask(task_id="a", owner="lead", coro_factory=step_a),
        ParallelTask(task_id="b", owner="builder", coro_factory=step_b, depends_on=["a"]),
    ])

    assert results[0].success and results[1].success
    assert order.index("a") < order.index("b")


@pytest.mark.asyncio
async def test_timeout_handling():
    async def slow():
        await asyncio.sleep(10)

    executor = ParallelExecutor()
    results = await executor.execute([
        ParallelTask(task_id="slow", owner="ops", coro_factory=slow, timeout_s=0.05),
    ])

    assert results[0].success is False
    assert results[0].error == "timeout"


@pytest.mark.asyncio
async def test_exception_handling():
    async def failing():
        raise ValueError("test error")

    executor = ParallelExecutor()
    results = await executor.execute_simple([("fail", failing)])

    assert results[0].success is False
    assert "test error" in results[0].error


@pytest.mark.asyncio
async def test_semaphore_bounds_concurrency():
    active = []
    max_active = [0]

    async def track():
        active.append(1)
        if len(active) > max_active[0]:
            max_active[0] = len(active)
        await asyncio.sleep(0.02)
        active.pop()

    executor = ParallelExecutor(max_concurrency=2)
    results = await executor.execute_simple([
        (f"t{i}", track) for i in range(6)
    ])

    assert all(r.success for r in results)
    assert max_active[0] <= 2


@pytest.mark.asyncio
async def test_empty_tasks():
    executor = ParallelExecutor()
    results = await executor.execute([])
    assert results == []
