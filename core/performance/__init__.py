"""
Performance Optimization Package

Modules:
- cache_manager: LRU cache with TTL for LLM, routing, session results
- async_executor: Concurrent execution with resource limits
- memory_consolidator: Pattern chunking, Q-learning optimization
- metrics_tracker: Performance metrics collection
"""

from .cache_manager import CacheManager, get_cache_manager, cached

__all__ = [
    "CacheManager",
    "get_cache_manager",
    "cached",
]
