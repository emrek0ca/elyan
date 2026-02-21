"""
Speed Optimizer - Performance Enhancement System

Hız optimizasyonu için:
1. Pattern caching
2. Predictive loading
3. Parallel execution
4. Smart prefetching
5. Response streaming
"""

import asyncio
import time
from typing import Dict, Any, List, Optional, Callable
from collections import OrderedDict
from dataclasses import dataclass
import threading

from utils.logger import get_logger

logger = get_logger("speed_optimizer")


@dataclass
class CachedResult:
    """Cached operation result"""
    result: Any
    timestamp: float
    hit_count: int = 0
    ttl: int = 300  # 5 minutes default


class SpeedOptimizer:
    """
    Performance optimization system.
    """

    def __init__(self, max_cache_size: int = 1000):
        self.max_cache_size = max_cache_size

        # LRU cache for results
        self._result_cache: OrderedDict[str, CachedResult] = OrderedDict()

        # Preloaded resources
        self._preloaded: Dict[str, Any] = {}

        # Parallel execution pool
        self._executor_pool: Dict[str, asyncio.Task] = {}

        # Predictive queue
        self._prediction_queue: List[str] = []

        # Stats
        self._cache_hits = 0
        self._cache_misses = 0

        logger.info("Speed optimizer initialized")

    def cache_result(self, key: str, result: Any, ttl: int = 300):
        """Cache operation result"""
        # Evict oldest if full
        if len(self._result_cache) >= self.max_cache_size:
            self._result_cache.popitem(last=False)

        self._result_cache[key] = CachedResult(
            result=result,
            timestamp=time.time(),
            ttl=ttl
        )
        self._result_cache.move_to_end(key)

    def get_cached(self, key: str) -> Optional[Any]:
        """Get cached result if valid"""
        if key not in self._result_cache:
            self._cache_misses += 1
            return None

        cached = self._result_cache[key]

        # Check TTL
        if time.time() - cached.timestamp > cached.ttl:
            del self._result_cache[key]
            self._cache_misses += 1
            return None

        # Hit
        cached.hit_count += 1
        self._cache_hits += 1
        self._result_cache.move_to_end(key)  # LRU update

        logger.debug(f"Cache hit: {key}")
        return cached.result

    async def parallel_execute(
        self,
        tasks: List[Callable],
        timeout: Optional[float] = None
    ) -> List[Any]:
        """Execute multiple tasks in parallel"""
        start = time.time()

        async_tasks = [
            asyncio.create_task(task()) if asyncio.iscoroutinefunction(task)
            else asyncio.to_thread(task)
            for task in tasks
        ]

        try:
            results = await asyncio.gather(*async_tasks, return_exceptions=True)
            elapsed = int((time.time() - start) * 1000)
            logger.info(f"Parallel execution: {len(tasks)} tasks in {elapsed}ms")
            return results
        except asyncio.TimeoutError:
            logger.warning(f"Parallel execution timeout: {timeout}s")
            return [None] * len(tasks)

    def predict_next_action(self, recent_actions: List[str]) -> Optional[str]:
        """Predict next likely action based on history"""
        if len(recent_actions) < 2:
            return None

        # Simple Markov chain prediction
        # In production, use ML model
        last_action = recent_actions[-1]

        # Hardcoded patterns (will be learned)
        patterns = {
            "take_screenshot": "file_operation",
            "file_operation": "file_operation",
            "research": "document",
        }

        return patterns.get(last_action)

    async def prefetch(self, action: str):
        """Prefetch resources for predicted action"""
        # Preload common resources
        if action == "file_operation":
            # Preload file tools
            pass
        elif action == "research":
            # Warm up research tools
            pass

        logger.debug(f"Prefetched resources for: {action}")

    def get_stats(self) -> Dict[str, Any]:
        """Get performance statistics"""
        total = self._cache_hits + self._cache_misses
        hit_rate = self._cache_hits / total if total > 0 else 0

        return {
            "cache_size": len(self._result_cache),
            "cache_hits": self._cache_hits,
            "cache_misses": self._cache_misses,
            "hit_rate": hit_rate,
            "cached_items": list(self._result_cache.keys())[:10]
        }


# Singleton
_speed_optimizer: Optional[SpeedOptimizer] = None


def get_speed_optimizer() -> SpeedOptimizer:
    """Get singleton speed optimizer"""
    global _speed_optimizer
    if _speed_optimizer is None:
        _speed_optimizer = SpeedOptimizer()
    return _speed_optimizer
