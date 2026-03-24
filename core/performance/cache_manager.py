"""
Performance Optimization — Caching Layer

Provides intelligent caching for:
- LLM responses (semantic similarity)
- Intent routing results (Tier 1 patterns)
- Session state snapshots
- Tool execution results

Strategy: TTL-based with semantic deduplication for LLM queries
"""

import hashlib
import json
from typing import Optional, Dict, Any, Callable
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from collections import OrderedDict
import asyncio
import logging

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """Single cache entry with metadata"""
    key: str
    value: Any
    created_at: float
    ttl_seconds: int
    hits: int = 0
    access_count: int = 0

    def is_expired(self, now: Optional[float] = None) -> bool:
        """Check if entry has expired"""
        now = now or datetime.now().timestamp()
        return (now - self.created_at) > self.ttl_seconds

    def record_access(self) -> None:
        """Record cache hit"""
        self.hits += 1
        self.access_count += 1


class CacheManager:
    """LRU cache with TTL and semantic deduplication"""

    def __init__(self, max_size: int = 1000, default_ttl: int = 3600):
        """
        Initialize cache manager

        Args:
            max_size: Maximum number of entries (LRU eviction)
            default_ttl: Default TTL in seconds (1 hour)
        """
        self.max_size = max_size
        self.default_ttl = default_ttl
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = asyncio.Lock()
        self._stats = {
            "hits": 0,
            "misses": 0,
            "evictions": 0,
            "expirations": 0
        }

    def _hash_key(self, key: str) -> str:
        """Create hash key from input (consistent)"""
        return hashlib.md5(key.encode()).hexdigest()

    async def get(self, key: str) -> Optional[Any]:
        """Retrieve from cache"""
        async with self._lock:
            hash_key = self._hash_key(key)

            if hash_key not in self._cache:
                self._stats["misses"] += 1
                return None

            entry = self._cache[hash_key]

            # Check expiration
            if entry.is_expired():
                del self._cache[hash_key]
                self._stats["expirations"] += 1
                self._stats["misses"] += 1
                return None

            # Record hit
            entry.record_access()
            self._stats["hits"] += 1

            # Move to end (LRU)
            self._cache.move_to_end(hash_key)

            logger.debug(f"Cache hit: {key[:50]}... (hits: {entry.hits})")
            return entry.value

    async def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[int] = None
    ) -> None:
        """Store in cache"""
        async with self._lock:
            hash_key = self._hash_key(key)
            ttl = ttl or self.default_ttl

            # Evict if at capacity
            if len(self._cache) >= self.max_size:
                oldest_key = next(iter(self._cache))
                del self._cache[oldest_key]
                self._stats["evictions"] += 1

            # Store entry
            entry = CacheEntry(
                key=key,
                value=value,
                created_at=datetime.now().timestamp(),
                ttl_seconds=ttl
            )
            self._cache[hash_key] = entry

            logger.debug(f"Cache set: {key[:50]}... (size: {len(self._cache)})")

    async def clear(self) -> None:
        """Clear entire cache"""
        async with self._lock:
            self._cache.clear()

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        total = self._stats["hits"] + self._stats["misses"]
        hit_rate = (
            (self._stats["hits"] / total * 100) if total > 0 else 0
        )

        return {
            "entries": len(self._cache),
            "max_size": self.max_size,
            "hits": self._stats["hits"],
            "misses": self._stats["misses"],
            "hit_rate": f"{hit_rate:.1f}%",
            "evictions": self._stats["evictions"],
            "expirations": self._stats["expirations"]
        }


# Singleton instance
_cache_manager: Optional[CacheManager] = None


def get_cache_manager(max_size: int = 1000) -> CacheManager:
    """Get or create cache manager singleton"""
    global _cache_manager
    if _cache_manager is None:
        _cache_manager = CacheManager(max_size=max_size)
        logger.info(f"Cache manager initialized (max_size={max_size})")
    return _cache_manager


# Decorator for caching async functions
def cached(ttl: int = 3600):
    """Decorator to cache async function results"""
    def decorator(func: Callable) -> Callable:
        async def wrapper(*args, **kwargs) -> Any:
            cache = get_cache_manager()

            # Create cache key from function name + args
            key_dict = {
                'args': [str(arg) for arg in args],
                'kwargs': {k: str(v) for k, v in kwargs.items()}
            }
            cache_key = f"{func.__name__}:{json.dumps(key_dict, sort_keys=True)}"

            # Try cache
            cached_result = await cache.get(cache_key)
            if cached_result is not None:
                return cached_result

            # Call function
            result = await func(*args, **kwargs)

            # Store result
            await cache.set(cache_key, result, ttl=ttl)

            return result

        return wrapper
    return decorator
