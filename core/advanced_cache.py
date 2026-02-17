"""
Advanced Caching Strategy
Multi-tier caching, distributed cache, cache warming, smart invalidation
"""

import time
import hashlib
import pickle
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass
from enum import Enum
from collections import OrderedDict
import asyncio

from utils.logger import get_logger

logger = get_logger("advanced_cache")


class CacheTier(Enum):
    """Cache tier levels"""
    L1_MEMORY = "l1_memory"  # In-memory, fastest
    L2_REDIS = "l2_redis"  # Redis, fast
    L3_DISK = "l3_disk"  # Disk, slower but persistent


class EvictionPolicy(Enum):
    """Cache eviction policies"""
    LRU = "lru"  # Least Recently Used
    LFU = "lfu"  # Least Frequently Used
    FIFO = "fifo"  # First In First Out
    TTL = "ttl"  # Time To Live


@dataclass
class CacheEntry:
    """Cache entry with metadata"""
    key: str
    value: Any
    ttl: int
    created_at: float
    accessed_at: float
    access_count: int = 0
    tier: CacheTier = CacheTier.L1_MEMORY
    tags: List[str] = None

    def __post_init__(self):
        if self.tags is None:
            self.tags = []

    def is_expired(self) -> bool:
        """Check if entry is expired"""
        if self.ttl == 0:  # No expiration
            return False
        return time.time() - self.created_at > self.ttl


class AdvancedCache:
    """
    Advanced Caching Strategy
    - Multi-tier caching (L1, L2, L3)
    - Multiple eviction policies
    - Cache warming
    - Smart invalidation
    - Tag-based invalidation
    - Cache statistics
    - Distributed cache support
    """

    def __init__(
        self,
        l1_max_size: int = 1000,
        l2_max_size: int = 10000,
        default_ttl: int = 3600,
        eviction_policy: EvictionPolicy = EvictionPolicy.LRU
    ):
        # L1 Cache (Memory)
        self.l1_cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self.l1_max_size = l1_max_size

        # L2 Cache (Redis placeholder - would use actual Redis)
        self.l2_cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self.l2_max_size = l2_max_size
        self.l2_available = False

        # L3 Cache (Disk)
        self.l3_cache: Dict[str, str] = {}  # key -> file path
        self.l3_available = False

        self.default_ttl = default_ttl
        self.eviction_policy = eviction_policy

        # Statistics
        self.stats = {
            "l1_hits": 0,
            "l1_misses": 0,
            "l2_hits": 0,
            "l2_misses": 0,
            "l3_hits": 0,
            "l3_misses": 0,
            "evictions": 0,
            "invalidations": 0
        }

        # Access frequency for LFU
        self.access_frequency: Dict[str, int] = {}

        # Tag index
        self.tag_index: Dict[str, List[str]] = {}  # tag -> [keys]

        logger.info("Advanced Cache initialized")

    def get(self, key: str) -> Optional[Any]:
        """Get value from cache (checks all tiers)"""
        # Check L1
        if key in self.l1_cache:
            entry = self.l1_cache[key]

            if entry.is_expired():
                self.delete(key)
                return None

            # Update access metadata
            entry.accessed_at = time.time()
            entry.access_count += 1
            self.access_frequency[key] = self.access_frequency.get(key, 0) + 1

            # Move to end for LRU
            if self.eviction_policy == EvictionPolicy.LRU:
                self.l1_cache.move_to_end(key)

            self.stats["l1_hits"] += 1
            return entry.value

        self.stats["l1_misses"] += 1

        # Check L2
        if self.l2_available and key in self.l2_cache:
            entry = self.l2_cache[key]

            if entry.is_expired():
                self.delete(key)
                return None

            # Promote to L1
            self._promote_to_l1(key, entry)

            self.stats["l2_hits"] += 1
            return entry.value

        if self.l2_available:
            self.stats["l2_misses"] += 1

        # Check L3
        if self.l3_available and key in self.l3_cache:
            try:
                value = self._load_from_disk(key)
                # Promote to L1
                self.set(key, value, tier=CacheTier.L1_MEMORY)
                self.stats["l3_hits"] += 1
                return value
            except:
                pass

        if self.l3_available:
            self.stats["l3_misses"] += 1

        return None

    def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[int] = None,
        tier: CacheTier = CacheTier.L1_MEMORY,
        tags: Optional[List[str]] = None
    ):
        """Set value in cache"""
        ttl = ttl if ttl is not None else self.default_ttl

        entry = CacheEntry(
            key=key,
            value=value,
            ttl=ttl,
            created_at=time.time(),
            accessed_at=time.time(),
            tier=tier,
            tags=tags or []
        )

        # Store in appropriate tier
        if tier == CacheTier.L1_MEMORY:
            self._set_l1(key, entry)
        elif tier == CacheTier.L2_REDIS and self.l2_available:
            self._set_l2(key, entry)
        elif tier == CacheTier.L3_DISK and self.l3_available:
            self._set_l3(key, entry)

        # Update tag index
        for tag in entry.tags:
            if tag not in self.tag_index:
                self.tag_index[tag] = []
            if key not in self.tag_index[tag]:
                self.tag_index[tag].append(key)

    def _set_l1(self, key: str, entry: CacheEntry):
        """Set in L1 cache"""
        # Check if eviction needed
        if len(self.l1_cache) >= self.l1_max_size and key not in self.l1_cache:
            self._evict_l1()

        self.l1_cache[key] = entry

    def _set_l2(self, key: str, entry: CacheEntry):
        """Set in L2 cache"""
        if len(self.l2_cache) >= self.l2_max_size and key not in self.l2_cache:
            self._evict_l2()

        self.l2_cache[key] = entry

    def _set_l3(self, key: str, entry: CacheEntry):
        """Set in L3 cache (disk)"""
        file_path = self._get_disk_path(key)
        try:
            with open(file_path, 'wb') as f:
                pickle.dump(entry.value, f)
            self.l3_cache[key] = file_path
        except Exception as e:
            logger.error(f"L3 cache write error: {e}")

    def _evict_l1(self):
        """Evict from L1 cache based on policy"""
        if not self.l1_cache:
            return

        if self.eviction_policy == EvictionPolicy.LRU:
            # Remove first (oldest)
            key, entry = self.l1_cache.popitem(last=False)

        elif self.eviction_policy == EvictionPolicy.LFU:
            # Remove least frequently used
            key = min(self.access_frequency, key=self.access_frequency.get)
            entry = self.l1_cache.pop(key)
            del self.access_frequency[key]

        elif self.eviction_policy == EvictionPolicy.FIFO:
            # Remove first
            key, entry = self.l1_cache.popitem(last=False)

        elif self.eviction_policy == EvictionPolicy.TTL:
            # Remove oldest by creation time
            key = min(self.l1_cache, key=lambda k: self.l1_cache[k].created_at)
            entry = self.l1_cache.pop(key)

        # Demote to L2 if available
        if self.l2_available:
            self._set_l2(key, entry)

        self.stats["evictions"] += 1
        logger.debug(f"Evicted from L1: {key}")

    def _evict_l2(self):
        """Evict from L2 cache"""
        if self.l2_cache:
            key, _ = self.l2_cache.popitem(last=False)
            self.stats["evictions"] += 1

    def delete(self, key: str):
        """Delete from all cache tiers"""
        deleted = False

        if key in self.l1_cache:
            del self.l1_cache[key]
            deleted = True

        if key in self.l2_cache:
            del self.l2_cache[key]
            deleted = True

        if key in self.l3_cache:
            try:
                import os
                os.remove(self.l3_cache[key])
                del self.l3_cache[key]
                deleted = True
            except:
                pass

        if key in self.access_frequency:
            del self.access_frequency[key]

        if deleted:
            self.stats["invalidations"] += 1

    def invalidate_by_tag(self, tag: str):
        """Invalidate all cache entries with a specific tag"""
        if tag in self.tag_index:
            keys = self.tag_index[tag][:]  # Copy to avoid modification during iteration
            for key in keys:
                self.delete(key)
            del self.tag_index[tag]
            logger.info(f"Invalidated {len(keys)} entries with tag: {tag}")

    def invalidate_by_pattern(self, pattern: str):
        """Invalidate cache entries matching pattern"""
        import re
        regex = re.compile(pattern)

        keys_to_delete = [
            key for key in self.l1_cache.keys()
            if regex.match(key)
        ]

        for key in keys_to_delete:
            self.delete(key)

        logger.info(f"Invalidated {len(keys_to_delete)} entries matching pattern: {pattern}")

    def warm_cache(self, loader: Callable[[str], Any], keys: List[str]):
        """Warm cache with data"""
        logger.info(f"Warming cache with {len(keys)} entries")

        for key in keys:
            try:
                value = loader(key)
                self.set(key, value)
            except Exception as e:
                logger.error(f"Cache warming error for {key}: {e}")

    async def async_warm_cache(
        self,
        loader: Callable[[str], Any],
        keys: List[str],
        batch_size: int = 10
    ):
        """Async cache warming with batching"""
        logger.info(f"Async warming cache with {len(keys)} entries")

        for i in range(0, len(keys), batch_size):
            batch = keys[i:i+batch_size]

            tasks = []
            for key in batch:
                if asyncio.iscoroutinefunction(loader):
                    tasks.append(loader(key))

            if tasks:
                results = await asyncio.gather(*tasks, return_exceptions=True)

                for key, result in zip(batch, results):
                    if not isinstance(result, Exception):
                        self.set(key, result)

    def _promote_to_l1(self, key: str, entry: CacheEntry):
        """Promote entry from L2/L3 to L1"""
        entry.tier = CacheTier.L1_MEMORY
        self._set_l1(key, entry)

    def _get_disk_path(self, key: str) -> str:
        """Get disk path for key"""
        from config.settings import HOME_DIR
        cache_dir = HOME_DIR / ".elyan" / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)

        # Hash key for filename
        key_hash = hashlib.md5(key.encode()).hexdigest()
        return str(cache_dir / f"{key_hash}.cache")

    def _load_from_disk(self, key: str) -> Any:
        """Load value from disk"""
        file_path = self.l3_cache.get(key)
        if not file_path:
            raise KeyError(f"Key not in L3 cache: {key}")

        with open(file_path, 'rb') as f:
            return pickle.load(f)

    def clear(self, tier: Optional[CacheTier] = None):
        """Clear cache"""
        if tier is None or tier == CacheTier.L1_MEMORY:
            self.l1_cache.clear()
            self.access_frequency.clear()

        if tier is None or tier == CacheTier.L2_REDIS:
            self.l2_cache.clear()

        if tier is None or tier == CacheTier.L3_DISK:
            for file_path in self.l3_cache.values():
                try:
                    import os
                    os.remove(file_path)
                except:
                    pass
            self.l3_cache.clear()

        self.tag_index.clear()
        logger.info(f"Cache cleared: {tier.value if tier else 'all tiers'}")

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        l1_hit_rate = (
            self.stats["l1_hits"] / (self.stats["l1_hits"] + self.stats["l1_misses"])
            if (self.stats["l1_hits"] + self.stats["l1_misses"]) > 0
            else 0
        )

        return {
            **self.stats,
            "l1_size": len(self.l1_cache),
            "l1_max_size": self.l1_max_size,
            "l1_hit_rate": f"{l1_hit_rate:.2%}",
            "l2_size": len(self.l2_cache),
            "l3_size": len(self.l3_cache),
            "eviction_policy": self.eviction_policy.value,
            "tags": len(self.tag_index)
        }


# Global instance
_advanced_cache: Optional[AdvancedCache] = None


def get_advanced_cache() -> AdvancedCache:
    """Get or create global advanced cache instance"""
    global _advanced_cache
    if _advanced_cache is None:
        _advanced_cache = AdvancedCache()
    return _advanced_cache
