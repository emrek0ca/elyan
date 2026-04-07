import pytest

from core.performance.cache_manager import CacheManager


@pytest.mark.asyncio
async def test_cache_separates_entries_by_namespace_and_scope():
    cache = CacheManager(max_size=10, default_ttl=60)

    await cache.set("same-key", "search-value", namespace="internet_search", level="l2", scope="session-a")
    await cache.set("same-key", "read-value", namespace="internet_read", level="l3", scope="session-b")

    assert await cache.get("same-key", namespace="internet_search", level="l2", scope="session-a") == "search-value"
    assert await cache.get("same-key", namespace="internet_read", level="l3", scope="session-b") == "read-value"
    assert await cache.get("same-key", namespace="internet_search", level="l2", scope="session-b") is None

    stats = cache.get_stats()
    assert "internet_read" in stats["namespaces"]
    assert "internet_search" in stats["namespaces"]
