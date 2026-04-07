from __future__ import annotations

from typing import Any

from core.internet import get_internet_reach_runtime
from core.registry import tool


@tool("internet_search", "Search the web, GitHub, YouTube, Reddit or RSS sources through Elyan Internet Reach.")
async def internet_search(query: str, platforms: list[str] | None = None, limit: int = 8, language: str = "tr") -> dict[str, Any]:
    runtime = get_internet_reach_runtime()
    hits = await runtime.search(query, platforms=platforms, limit=limit, language=language)
    return {
        "success": True,
        "status": "success",
        "query": str(query or ""),
        "results": [hit.to_dict() for hit in hits],
        "count": len(hits),
        "health": runtime.get_health_status(),
    }


@tool("internet_read", "Read and normalize a web page or platform URL through Elyan Internet Reach.")
async def internet_read(url: str, source_policy: str = "balanced") -> dict[str, Any]:
    runtime = get_internet_reach_runtime()
    document = await runtime.read(url, source_policy=source_policy)
    return {
        "success": True,
        "status": "success",
        "document": document.to_dict(),
        "health": runtime.get_health_status(),
    }


@tool("internet_discover", "Search and read multiple internet sources in one pass through Elyan Internet Reach.")
async def internet_discover(
    query: str,
    platforms: list[str] | None = None,
    limit: int = 6,
    source_policy: str = "balanced",
    language: str = "tr",
) -> dict[str, Any]:
    runtime = get_internet_reach_runtime()
    documents = await runtime.discover(query, platforms=platforms, limit=limit, source_policy=source_policy, language=language)
    return {
        "success": True,
        "status": "success",
        "query": str(query or ""),
        "documents": [doc.to_dict() for doc in documents],
        "count": len(documents),
        "health": runtime.get_health_status(),
    }


__all__ = ["internet_search", "internet_read", "internet_discover"]
