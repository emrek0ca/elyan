"""LLM Response Cache — with bypass keywords and min-token threshold.

FIX BUG-PERF-001:
- Short/empty responses are NOT cached (min token threshold)
- Bypass keywords cause cache to be skipped entirely
- Cache invalidation on explicit retry requests
"""

import hashlib
import re
import time
from typing import Any, Optional
from collections import OrderedDict
from typing import Dict
from utils.logger import get_logger

logger = get_logger("llm_cache")

# Cache configuration
MAX_CACHE_SIZE = 100
CACHE_TTL = 300  # 5 minutes

# BUG-PERF-001: Minimum response length to be worth caching
MIN_CACHE_RESPONSE_CHARS = 50

# BUG-PERF-001: Keywords that bypass cache entirely (user wants fresh response)
BYPASS_KEYWORDS = frozenset([
    "tekrar dene", "retry", "yenile", "refresh", "again",
    "yeniden", "tekrar", "farklı", "different", "başka",
    "güncelle", "update", "son", "latest", "şimdi", "now",
    "bugün", "today", "anlık", "realtime",
])

# BUG-PERF-002: Pre-compiled regex for bypass detection (module-level, compiled once)
_BYPASS_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in BYPASS_KEYWORDS) + r")\b",
    re.IGNORECASE | re.UNICODE
)


def should_bypass_cache(text: str) -> bool:
    """Check if the request should bypass cache."""
    return bool(_BYPASS_PATTERN.search(text))


class LLMCache:
    """LRU cache for LLM responses with TTL, bypass keywords, and min-token threshold."""

    def __init__(self, max_size: int = MAX_CACHE_SIZE, ttl: int = CACHE_TTL):
        self.max_size = max_size
        self.ttl = ttl
        self._cache: OrderedDict[str, dict] = OrderedDict()
        self._hits = 0
        self._misses = 0
        self._bypasses = 0

    def _hash_key(self, text: str) -> str:
        """Create a hash key from the input text."""
        normalized = " ".join(text.lower().split())
        return hashlib.sha256(normalized.encode()).hexdigest()

    def get(self, text: str) -> Optional[dict]:
        """
        Get cached response. Returns None if:
        - Not in cache
        - Expired
        - Bypass keyword detected
        """
        # BUG-PERF-001: Bypass check
        if should_bypass_cache(text):
            self._bypasses += 1
            logger.debug(f"Cache bypassed for: {text[:40]}...")
            return None

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

        self._cache.move_to_end(key)
        self._hits += 1
        logger.debug(f"Cache hit for: {text[:30]}...")
        return entry["response"]

    def set(self, text: str, response: Any) -> None:
        """
        Cache a response. Skips caching if:
        - Response is too short (likely error/empty)
        - Response action is 'chat' (conversational, not cacheable)
        - Bypass keyword in request
        """
        # Don't cache if bypass keyword in request
        if should_bypass_cache(text):
            return

        # Backward compatible: some call sites/tests pass plain string responses.
        if isinstance(response, dict):
            # Don't cache chat/empty action payloads
            if response.get("action") == "chat" or not response.get("action"):
                return
            response_text = str(response.get("result", "") or response.get("message", "") or "")
        else:
            response_text = str(response or "")

        # BUG-PERF-001: Don't cache short/invalid responses
        if len(response_text) < MIN_CACHE_RESPONSE_CHARS:
            logger.debug(f"Skipping cache for short response ({len(response_text)} chars)")
            return

        key = self._hash_key(text)

        if len(self._cache) >= self.max_size:
            self._cache.popitem(last=False)

        self._cache[key] = {
            "response": response,
            "timestamp": time.time()
        }
        logger.debug(f"Cached response for: {text[:30]}...")

    def invalidate(self, text: str = None) -> None:
        """Invalidate cache entry or entire cache."""
        if text:
            key = self._hash_key(text)
            self._cache.pop(key, None)
        else:
            self._cache.clear()
            logger.info("Cache cleared")

    def get_stats(self) -> dict:
        """Get cache statistics."""
        total = self._hits + self._misses
        hit_rate = (self._hits / total * 100) if total > 0 else 0
        return {
            "size": len(self._cache),
            "max_size": self.max_size,
            "hits": self._hits,
            "misses": self._misses,
            "bypasses": self._bypasses,
            "hit_rate": round(hit_rate, 2),
            "ttl": self.ttl,
            "min_cache_chars": MIN_CACHE_RESPONSE_CHARS,
        }

    def cleanup_expired(self) -> int:
        """Remove expired entries and return count of removed items."""
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
_cache_instance: Optional[LLMCache] = None


def get_cache() -> LLMCache:
    """Get the global cache instance."""
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = LLMCache()
    return _cache_instance
