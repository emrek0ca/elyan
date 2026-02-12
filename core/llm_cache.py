"""LLM Response Cache - Cache frequent queries for faster responses"""

import hashlib
import time
from typing import Any
from collections import OrderedDict
from utils.logger import get_logger

logger = get_logger("llm_cache")

# Cache configuration
MAX_CACHE_SIZE = 100  # Maximum number of cached responses
CACHE_TTL = 300  # Time to live in seconds (5 minutes)


class LLMCache:
    """Simple LRU cache for LLM responses with TTL"""

    def __init__(self, max_size: int = MAX_CACHE_SIZE, ttl: int = CACHE_TTL):
        self.max_size = max_size
        self.ttl = ttl
        self._cache: OrderedDict[str, dict] = OrderedDict()
        self._hits = 0
        self._misses = 0

    def _hash_key(self, text: str) -> str:
        """Create a hash key from the input text"""
        # Normalize text: lowercase and remove extra whitespace
        normalized = " ".join(text.lower().split())
        return hashlib.md5(normalized.encode()).hexdigest()

    def get(self, text: str) -> dict | None:
        """Get cached response for the given input"""
        key = self._hash_key(text)

        if key not in self._cache:
            self._misses += 1
            return None

        entry = self._cache[key]

        # Check if expired
        if time.time() - entry["timestamp"] > self.ttl:
            del self._cache[key]
            self._misses += 1
            return None

        # Move to end (most recently used)
        self._cache.move_to_end(key)
        self._hits += 1

        logger.debug(f"Cache hit for: {text[:30]}...")
        return entry["response"]

    def set(self, text: str, response: dict) -> None:
        """Cache a response for the given input"""
        # Don't cache chat responses or errors
        if response.get("action") == "chat" or not response.get("action"):
            return

        key = self._hash_key(text)

        # Remove oldest if at capacity
        if len(self._cache) >= self.max_size:
            self._cache.popitem(last=False)

        self._cache[key] = {
            "response": response,
            "timestamp": time.time()
        }

        logger.debug(f"Cached response for: {text[:30]}...")

    def invalidate(self, text: str = None) -> None:
        """Invalidate cache entry or entire cache"""
        if text:
            key = self._hash_key(text)
            if key in self._cache:
                del self._cache[key]
        else:
            self._cache.clear()
            logger.info("Cache cleared")

    def get_stats(self) -> dict:
        """Get cache statistics"""
        total = self._hits + self._misses
        hit_rate = (self._hits / total * 100) if total > 0 else 0

        return {
            "size": len(self._cache),
            "max_size": self.max_size,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(hit_rate, 2),
            "ttl": self.ttl
        }

    def cleanup_expired(self) -> int:
        """Remove expired entries and return count of removed items"""
        now = time.time()
        expired_keys = [
            key for key, entry in self._cache.items()
            if now - entry["timestamp"] > self.ttl
        ]

        for key in expired_keys:
            del self._cache[key]

        if expired_keys:
            logger.debug(f"Cleaned up {len(expired_keys)} expired cache entries")

        return len(expired_keys)


# Global cache instance
_cache_instance = None


def get_cache() -> LLMCache:
    """Get the global cache instance"""
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = LLMCache()
    return _cache_instance
