"""
Smart Caching System
Multi-tier caching for operations with TTL and automatic cleanup
"""

import hashlib
import json
from typing import Dict, Optional, Any, Callable
from datetime import datetime, timedelta
from collections import OrderedDict
from utils.logger import get_logger

logger = get_logger("smart_cache")


class CacheEntry:
    """Single cache entry with TTL"""

    def __init__(self, value: Any, ttl_seconds: int = 3600):
        self.value = value
        self.created_at = datetime.now()
        self.ttl_seconds = ttl_seconds
        self.hit_count = 0
        self.last_accessed = datetime.now()

    def is_expired(self) -> bool:
        """Check if cache entry has expired"""
        elapsed = (datetime.now() - self.created_at).total_seconds()
        return elapsed > self.ttl_seconds

    def touch(self):
        """Update last access time"""
        self.last_accessed = datetime.now()
        self.hit_count += 1

    def age_seconds(self) -> float:
        """Age of cache entry in seconds"""
        return (datetime.now() - self.created_at).total_seconds()


class SmartCache:
    """Multi-tier cache with automatic cleanup and statistics"""

    def __init__(self, max_size: int = 1000, default_ttl: int = 3600):
        self.cache: Dict[str, CacheEntry] = OrderedDict()
        self.max_size = max_size
        self.default_ttl = default_ttl
        self.stats = {
            "hits": 0,
            "misses": 0,
            "evictions": 0,
            "expirations": 0
        }

    def _make_key(self, namespace: str, query: str, **kwargs) -> str:
        """Generate cache key from namespace and parameters"""
        key_data = f"{namespace}:{query}:{json.dumps(kwargs, sort_keys=True, default=str)}"
        return hashlib.sha256(key_data.encode()).hexdigest()

    def get(self, namespace: str, query: str, **kwargs) -> Optional[Any]:
        """Get cached value"""
        key = self._make_key(namespace, query, **kwargs)
        entry = self.cache.get(key)

        if entry is None:
            self.stats["misses"] += 1
            return None

        if entry.is_expired():
            del self.cache[key]
            self.stats["expirations"] += 1
            self.stats["misses"] += 1
            return None

        entry.touch()
        self.stats["hits"] += 1
        return entry.value

    def set(self, namespace: str, query: str, value: Any, ttl_seconds: Optional[int] = None, **kwargs):
        """Set cache value"""
        key = self._make_key(namespace, query, **kwargs)
        ttl = ttl_seconds or self.default_ttl

        self.cache[key] = CacheEntry(value, ttl)

        # Cleanup if exceeding size
        if len(self.cache) > self.max_size:
            self._evict_lru()

    def delete(self, namespace: str, query: str, **kwargs):
        """Delete cache entry"""
        key = self._make_key(namespace, query, **kwargs)
        if key in self.cache:
            del self.cache[key]

    def clear(self, namespace: Optional[str] = None):
        """Clear cache entries"""
        if namespace is None:
            self.cache.clear()
        else:
            to_delete = [k for k in self.cache.keys() if k.startswith(namespace)]
            for k in to_delete:
                del self.cache[k]

    def cleanup_expired(self):
        """Remove expired entries"""
        initial_count = len(self.cache)
        to_delete = [k for k, v in self.cache.items() if v.is_expired()]

        for k in to_delete:
            del self.cache[k]

        removed = initial_count - len(self.cache)
        if removed > 0:
            self.stats["expirations"] += removed
            logger.debug(f"Cleaned up {removed} expired cache entries")

    def _evict_lru(self):
        """Evict least recently used entry"""
        if not self.cache:
            return

        # Find least recently used
        lru_key = min(self.cache.keys(), key=lambda k: self.cache[k].last_accessed)
        del self.cache[lru_key]
        self.stats["evictions"] += 1

    def get_statistics(self) -> Dict[str, Any]:
        """Get cache statistics"""
        total_requests = self.stats["hits"] + self.stats["misses"]
        hit_rate = (self.stats["hits"] / total_requests * 100) if total_requests > 0 else 0

        total_ttl = sum(e.ttl_seconds for e in self.cache.values())
        avg_ttl = total_ttl // max(len(self.cache), 1)

        return {
            "size": len(self.cache),
            "max_size": self.max_size,
            "hits": self.stats["hits"],
            "misses": self.stats["misses"],
            "hit_rate": f"{hit_rate:.1f}%",
            "evictions": self.stats["evictions"],
            "expirations": self.stats["expirations"],
            "average_ttl": avg_ttl,
            "oldest_entry_age": max([e.age_seconds() for e in self.cache.values()]) if self.cache else 0
        }

    def get_hot_items(self, top_k: int = 10) -> list:
        """Get most frequently accessed items"""
        items = sorted(
            self.cache.items(),
            key=lambda x: x[1].hit_count,
            reverse=True
        )
        return [
            {
                "key": k[:16] + "...",
                "hits": v.hit_count,
                "age": v.age_seconds(),
                "ttl_remaining": max(0, v.ttl_seconds - v.age_seconds())
            }
            for k, v in items[:top_k]
        ]


class CacheDecorator:
    """Decorator for caching function results"""

    def __init__(self, cache: SmartCache, namespace: str, ttl_seconds: int = 3600):
        self.cache = cache
        self.namespace = namespace
        self.ttl_seconds = ttl_seconds

    def __call__(self, func: Callable) -> Callable:
        """Wrap function with caching"""
        async def async_wrapper(*args, **kwargs):
            # Use function name and args as cache key
            cache_key = f"{func.__name__}:{str(args)}"
            cached = self.cache.get(self.namespace, cache_key, **kwargs)

            if cached is not None:
                return cached

            result = await func(*args, **kwargs)
            self.cache.set(self.namespace, cache_key, result, self.ttl_seconds, **kwargs)
            return result

        def sync_wrapper(*args, **kwargs):
            cache_key = f"{func.__name__}:{str(args)}"
            cached = self.cache.get(self.namespace, cache_key, **kwargs)

            if cached is not None:
                return cached

            result = func(*args, **kwargs)
            self.cache.set(self.namespace, cache_key, result, self.ttl_seconds, **kwargs)
            return result

        import asyncio
        import inspect

        if inspect.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper


# Global instance
_smart_cache: Optional[SmartCache] = None


def get_smart_cache() -> SmartCache:
    """Get or create smart cache"""
    global _smart_cache
    if _smart_cache is None:
        _smart_cache = SmartCache(max_size=1000, default_ttl=3600)
    return _smart_cache


def cache_research(ttl_seconds: int = 86400):
    """Decorator for caching research operations (24 hour TTL by default)"""
    cache = get_smart_cache()
    return CacheDecorator(cache, "research", ttl_seconds)


def cache_web_search(ttl_seconds: int = 43200):
    """Decorator for caching web searches (12 hour TTL by default)"""
    cache = get_smart_cache()
    return CacheDecorator(cache, "web_search", ttl_seconds)


def cache_document(ttl_seconds: int = 86400):
    """Decorator for caching document operations"""
    cache = get_smart_cache()
    return CacheDecorator(cache, "document", ttl_seconds)
