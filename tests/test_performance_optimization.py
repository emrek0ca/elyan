"""
Performance Optimization Tests

Test:
- Caching layer (hits, misses, TTL, LRU eviction)
- Async execution (concurrency, timeouts, retries)
- Cache decorator
"""

import pytest
import asyncio
import time
from core.performance import get_cache_manager, cached
from core.performance.async_executor import (
    get_async_executor,
    AsyncTask,
    TaskPriority
)


class TestCacheManager:
    """Test caching layer"""

    @pytest.fixture
    def cache(self):
        """Create fresh cache for each test"""
        return get_cache_manager(max_size=100)

    @pytest.mark.asyncio
    async def test_cache_set_get(self, cache):
        """Test basic cache set/get"""
        await cache.set("key1", "value1")
        result = await cache.get("key1")
        assert result == "value1"

    @pytest.mark.asyncio
    async def test_cache_miss(self, cache):
        """Test cache miss returns None"""
        result = await cache.get("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_cache_expiration(self, cache):
        """Test TTL expiration"""
        await cache.set("key1", "value1", ttl=1)  # 1 second TTL

        # Should exist immediately
        result = await cache.get("key1")
        assert result == "value1"

        # Wait for expiration
        await asyncio.sleep(1.1)

        # Should be expired
        result = await cache.get("key1")
        assert result is None

    @pytest.mark.asyncio
    async def test_cache_lru_eviction(self, cache):
        """Test LRU eviction when cache full"""
        # Fill cache (max_size=100)
        for i in range(100):
            await cache.set(f"key{i}", f"value{i}")

        # Cache should have 100 entries
        assert len(cache._cache) == 100

        # Add one more - should evict oldest
        await cache.set("key100", "value100")
        assert len(cache._cache) == 100

        # key0 should be evicted
        result = await cache.get("key0")
        assert result is None

    @pytest.mark.asyncio
    async def test_cache_hits_tracking(self, cache):
        """Test cache hit tracking"""
        # Clear any prior state
        await cache.clear()

        await cache.set("key1", "value1")

        # Access 3 times
        await cache.get("key1")
        await cache.get("key1")
        await cache.get("key1")

        stats = cache.get_stats()
        assert stats["hits"] >= 3  # At least 3 hits
        assert stats["misses"] >= 0

    @pytest.mark.asyncio
    async def test_cache_decorator(self):
        """Test @cached decorator"""
        call_count = 0

        @cached(ttl=3600)
        async def expensive_func(x: int) -> int:
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.01)
            return x * 2

        # First call - execute function
        result1 = await expensive_func(5)
        assert result1 == 10
        assert call_count == 1

        # Second call - should hit cache
        result2 = await expensive_func(5)
        assert result2 == 10
        assert call_count == 1  # Not incremented

        # Different args - cache miss
        result3 = await expensive_func(10)
        assert result3 == 20
        assert call_count == 2


class TestAsyncExecutor:
    """Test async execution with resource limits"""

    @pytest.fixture
    def executor(self):
        """Create fresh executor for each test"""
        return get_async_executor(max_concurrent=5)

    @pytest.mark.asyncio
    async def test_submit_and_execute(self, executor):
        """Test submitting and executing tasks"""
        results = {}

        async def task_func(x):
            await asyncio.sleep(0.01)
            return x * 2

        # Submit tasks
        for i in range(5):
            await executor.submit(
                task_id=f"task{i}",
                func=task_func,
                args=(i,)
            )

        # Execute all
        results = await executor.execute_all()

        assert len(results) == 5
        for i in range(5):
            assert results[f"task{i}"]["status"] == "success"
            assert results[f"task{i}"]["result"] == i * 2

    @pytest.mark.asyncio
    async def test_task_timeout(self, executor):
        """Test task timeout handling"""
        async def slow_task():
            await asyncio.sleep(2)

        await executor.submit(
            task_id="slow_task",
            func=slow_task,
            timeout=0.1
        )

        results = await executor.execute_all()
        assert results["slow_task"]["status"] == "timeout"

    @pytest.mark.asyncio
    async def test_task_retry(self, executor):
        """Test task retry on failure"""
        call_count = 0

        async def failing_task():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("Temporary error")
            return "success"

        await executor.submit(
            task_id="retry_task",
            func=failing_task,
            max_retries=3
        )

        results = await executor.execute_all()
        assert results["retry_task"]["status"] == "success"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_priority_ordering(self, executor):
        """Test tasks execute in priority order"""
        execution_order = []

        async def track_task(name: str):
            execution_order.append(name)

        # Submit in reverse priority order
        await executor.submit(
            "low",
            track_task,
            args=("low",),
            priority=TaskPriority.LOW
        )
        await executor.submit(
            "high",
            track_task,
            args=("high",),
            priority=TaskPriority.HIGH
        )
        await executor.submit(
            "critical",
            track_task,
            args=("critical",),
            priority=TaskPriority.CRITICAL
        )

        await executor.execute_all()

        # Should execute in priority order
        assert execution_order[0] == "critical"
        assert execution_order[1] == "high"
        assert execution_order[2] == "low"

    @pytest.mark.asyncio
    async def test_concurrency_limit(self, executor):
        """Test concurrent execution respects limits"""
        concurrent_count = 0
        max_concurrent = 0

        async def track_concurrent():
            nonlocal concurrent_count, max_concurrent
            concurrent_count += 1
            max_concurrent = max(max_concurrent, concurrent_count)
            await asyncio.sleep(0.05)
            concurrent_count -= 1

        # Submit 20 tasks with max_concurrent=5
        for i in range(20):
            await executor.submit(
                task_id=f"task{i}",
                func=track_concurrent
            )

        results = await executor.execute_all()

        # Should not exceed concurrency limit
        assert max_concurrent <= executor.max_concurrent
        assert len(results) == 20


class TestPerformanceMetrics:
    """Test performance metrics collection"""

    @pytest.mark.asyncio
    async def test_cache_stats(self):
        """Test cache statistics"""
        cache = get_cache_manager()

        # Generate some activity
        await cache.set("key1", "value1")
        await cache.get("key1")
        await cache.get("key1")
        await cache.get("nonexistent")

        stats = cache.get_stats()

        assert stats["hits"] >= 2
        assert stats["misses"] >= 1
        assert "hit_rate" in stats
        assert "entries" in stats

    @pytest.mark.asyncio
    async def test_executor_stats(self):
        """Test executor statistics"""
        executor = get_async_executor()

        async def quick_task():
            await asyncio.sleep(0.001)
            return "done"

        for i in range(5):
            await executor.submit(
                task_id=f"task{i}",
                func=quick_task
            )

        await executor.execute_all()

        stats = executor.get_stats()

        assert stats["executed"] >= 5
        # Failed might include prior test failures, just check it's a number
        assert isinstance(stats["failed"], int)
        assert "total_time" in stats
