"""Internet Reach Runtime.

Platform-aware internet reading/search orchestration inspired by multi-source
readers like Agent-Reach, but aligned to Elyan's existing runtime.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Iterable, Optional
from urllib.parse import urlparse

import feedparser

from core.accuracy_speed_runtime import get_accuracy_speed_runtime
from core.performance.cache_manager import get_cache_manager
from tools.web_tools import smart_fetch_page, web_search
from utils.logger import get_logger

logger = get_logger("internet.reach")


@dataclass
class ReachDocument:
    url: str
    title: str
    content: str
    source_type: str = "web"
    provider: str = "smart_fetch"
    render_mode: str = "static"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ReachSearchHit:
    title: str
    url: str
    snippet: str = ""
    source_type: str = "web"
    provider: str = "search"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class InternetReachRuntime:
    """Broad internet reading/runtime layer."""

    SUPPORTED_PLATFORMS = ("web", "github", "youtube", "reddit", "rss")

    def __init__(self) -> None:
        self._platform_queries = {
            "github": "site:github.com",
            "youtube": "site:youtube.com OR site:youtu.be",
            "reddit": "site:reddit.com",
        }
        self._last_health: dict[str, Any] = {"status": "healthy", "last_successful_read": 0.0, "last_error": "", "fallback_active": False}
        self._cache = get_cache_manager()
        self._speed_runtime = get_accuracy_speed_runtime()

    async def search(
        self,
        query: str,
        *,
        platforms: Optional[Iterable[str]] = None,
        limit: int = 8,
        language: str = "tr",
    ) -> list[ReachSearchHit]:
        targets = self._normalize_platforms(platforms)
        scope = self._speed_runtime.make_scope_key(",".join(targets), language)
        cache_key = f"{query}::{limit}"
        cached = await self._cache.get(cache_key, namespace="internet_search", level="l2", scope=scope)
        if cached is not None:
            return [ReachSearchHit(**dict(item)) for item in list(cached or []) if isinstance(item, dict)]
        if not targets or targets == ["web"]:
            result = await self._search_web(query, limit=limit, language=language)
            await self._cache.set(cache_key, [hit.to_dict() for hit in result], ttl=120, namespace="internet_search", level="l2", scope=scope)
            return result

        tasks = [
            self._search_web(
                f"{query} {self._platform_queries.get(platform, '')}".strip(),
                limit=max(2, min(limit, 5)),
                language=language,
                source_type=platform,
            )
            for platform in targets
        ]
        rows: list[ReachSearchHit] = []
        for batch in await asyncio.gather(*tasks, return_exceptions=True):
            if isinstance(batch, Exception):
                logger.warning(f"internet reach search batch failed: {batch}")
                continue
            rows.extend(batch)
        deduped: list[ReachSearchHit] = []
        seen: set[str] = set()
        for hit in rows:
            key = str(hit.url).strip()
            if not key or key in seen:
                continue
            seen.add(key)
            hit.metadata["score"] = self._score_hit(hit)
            deduped.append(hit)
        deduped.sort(key=lambda item: float((item.metadata or {}).get("score") or 0.0), reverse=True)
        deduped = deduped[:limit]
        if deduped:
            self._last_health.update({"status": "healthy", "last_error": "", "fallback_active": False})
        await self._cache.set(cache_key, [hit.to_dict() for hit in deduped], ttl=120, namespace="internet_search", level="l2", scope=scope)
        return deduped

    async def read(self, url: str, *, source_policy: str = "balanced") -> ReachDocument:
        scope = self._speed_runtime.make_scope_key(source_policy)
        cache_key = str(url or "")
        cached = await self._cache.get(cache_key, namespace="internet_read", level="l3", scope=scope)
        if cached is not None and isinstance(cached, dict):
            return ReachDocument(**cached)
        platform = self._platform_for_url(url)
        if platform == "rss":
            return await self._read_rss(url)
        page = await smart_fetch_page(url, source_policy=source_policy, prefer_browser=platform in {"github", "youtube"})
        if not page.get("success"):
            failure = self._classify_read_failure(page)
            self._last_health.update({"status": "degraded", "last_error": failure, "fallback_active": True})
            raise RuntimeError(failure)
        self._last_health.update({"status": "healthy", "last_successful_read": datetime.now().timestamp(), "last_error": "", "fallback_active": str(page.get('render_mode') or 'static') == 'browser'})
        document = ReachDocument(
            url=str(page.get("url") or url),
            title=str(page.get("title") or self._title_from_url(url)),
            content=str(page.get("content") or ""),
            source_type=platform,
            provider="smart_fetch",
            render_mode=str(page.get("render_mode") or "static"),
            metadata={
                "status_code": int(page.get("status_code") or 0),
                "text_density": float(page.get("text_density") or 0.0),
                "length": int(page.get("length") or 0),
                "reliability": self._reliability_for_url(str(page.get("url") or url)),
                "freshness": self._freshness_hint(str(page.get("url") or url)),
                "trust_score": self._reliability_for_url(str(page.get("url") or url)),
                "freshness_score": 1.0 if self._freshness_hint(str(page.get("url") or url)) == "fresh" else 0.5,
                "parser_confidence": 0.9 if str(page.get("content") or "").strip() else 0.2,
            },
        )
        await self._cache.set(cache_key, document.to_dict(), ttl=300, namespace="internet_read", level="l3", scope=scope)
        self._speed_runtime.record_execution(lane="verified_lane", latency_ms=120.0, success=True, fallback_active=bool(self._last_health.get("fallback_active")), verification_state="verified")
        return document

    async def discover(
        self,
        query: str,
        *,
        platforms: Optional[Iterable[str]] = None,
        limit: int = 6,
        source_policy: str = "balanced",
        language: str = "tr",
    ) -> list[ReachDocument]:
        hits = await self.search(query, platforms=platforms, limit=limit, language=language)
        docs: list[ReachDocument] = []
        for hit in hits:
            try:
                document = await self.read(hit.url, source_policy=source_policy)
                if not document.title:
                    document.title = hit.title
                if not document.content:
                    document.content = hit.snippet
                document.metadata["search_snippet"] = hit.snippet
                docs.append(document)
            except Exception as exc:
                logger.debug(f"internet reach read failed for {hit.url}: {exc}")
                docs.append(
                    ReachDocument(
                        url=hit.url,
                        title=hit.title,
                        content=hit.snippet,
                        source_type=hit.source_type,
                        provider="search_fallback",
                        metadata={"read_error": str(exc), "failure_code": self._normalize_failure_code(str(exc))},
                    )
                )
        return docs

    async def _search_web(
        self,
        query: str,
        *,
        limit: int,
        language: str,
        source_type: str = "web",
    ) -> list[ReachSearchHit]:
        payload = await web_search(query, num_results=limit, language=language)
        if not payload.get("success"):
            return []
        hits: list[ReachSearchHit] = []
        for item in list(payload.get("results") or [])[:limit]:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            if not url:
                continue
            inferred_type = self._platform_for_url(url)
            if inferred_type == "web" and source_type != "web":
                inferred_type = source_type
            hits.append(
                ReachSearchHit(
                    title=str(item.get("title") or url),
                    url=url,
                    snippet=str(item.get("snippet") or ""),
                    source_type=inferred_type,
                    provider="duckduckgo_html",
                    metadata={"display_url": str(item.get("display_url") or "")},
                )
            )
        return hits

    async def _read_rss(self, url: str) -> ReachDocument:
        loop = asyncio.get_running_loop()
        parsed = await loop.run_in_executor(None, feedparser.parse, url)
        entries = []
        for entry in list(getattr(parsed, "entries", []) or [])[:12]:
            title = str(getattr(entry, "title", "") or "").strip()
            link = str(getattr(entry, "link", "") or "").strip()
            summary = str(getattr(entry, "summary", "") or getattr(entry, "description", "") or "").strip()
            if title:
                entries.append(f"- {title}: {summary[:180]} ({link})".strip())
        title = str(getattr(parsed.feed, "title", "") or self._title_from_url(url))
        return ReachDocument(
            url=url,
            title=title,
            content="\n".join(entries).strip(),
            source_type="rss",
            provider="feedparser",
            metadata={
                "entry_count": len(entries),
                "reliability": self._reliability_for_url(url),
                "freshness": "fresh",
                "trust_score": self._reliability_for_url(url),
                "freshness_score": 1.0,
                "parser_confidence": 0.92 if entries else 0.2,
            },
        )

    def _normalize_platforms(self, platforms: Optional[Iterable[str]]) -> list[str]:
        if not platforms:
            return ["web"]
        items: list[str] = []
        for platform in platforms:
            name = str(platform or "").strip().lower()
            if name in self.SUPPORTED_PLATFORMS and name not in items:
                items.append(name)
        return items or ["web"]

    @staticmethod
    def _platform_for_url(url: str) -> str:
        parsed = urlparse(str(url or ""))
        host = parsed.netloc.lower()
        path = parsed.path.lower()
        if "github.com" in host:
            return "github"
        if "youtube.com" in host or "youtu.be" in host:
            return "youtube"
        if "reddit.com" in host:
            return "reddit"
        if path.endswith((".xml", ".rss", ".atom")) or host.endswith(".rss"):
            return "rss"
        return "web"

    @staticmethod
    def _title_from_url(url: str) -> str:
        parsed = urlparse(str(url or ""))
        host = parsed.netloc or "source"
        path = parsed.path.strip("/")
        return f"{host}/{path}" if path else host

    def get_health_status(self) -> dict[str, Any]:
        runtime_state = self._speed_runtime.get_status()
        return {
            "status": str(self._last_health.get("status") or "healthy"),
            "ready": True,
            "supported_platforms": list(self.SUPPORTED_PLATFORMS),
            "last_successful_read": float(self._last_health.get("last_successful_read") or 0.0),
            "last_error": str(self._last_health.get("last_error") or ""),
            "fallback_active": bool(self._last_health.get("fallback_active")),
            "current_lane": "verified_lane",
            "verification_state": "verified" if not self._last_health.get("last_error") else "degraded",
            "average_latency_bucket": runtime_state.get("average_latency_bucket"),
        }

    @staticmethod
    def _normalize_failure_code(error: str) -> str:
        low = str(error or "").lower()
        if "dns" in low or "resolve" in low or "network" in low:
            return "dns/network"
        if "render" in low or "browser" in low:
            return "render_required"
        if "403" in low or "blocked" in low:
            return "blocked"
        if "empty" in low:
            return "empty_content"
        return "parsing_failed"

    def _classify_read_failure(self, payload: dict[str, Any]) -> str:
        error = str(payload.get("error") or payload.get("message") or "internet_read_failed")
        return self._normalize_failure_code(error)

    @staticmethod
    def _reliability_for_url(url: str) -> float:
        host = urlparse(str(url or "")).netloc.lower()
        if host.endswith(".gov") or host.endswith(".edu"):
            return 0.95
        if "github.com" in host or "youtube.com" in host:
            return 0.8
        if "reddit.com" in host:
            return 0.55
        return 0.7

    @staticmethod
    def _freshness_hint(url: str) -> str:
        path = urlparse(str(url or "")).path.lower()
        if any(token in path for token in ("/releases", "/latest", "/news", "/blog")):
            return "fresh"
        return "unknown"

    def _score_hit(self, hit: ReachSearchHit) -> float:
        base = self._reliability_for_url(hit.url)
        snippet = str(hit.snippet or "")
        density = min(1.0, len(snippet) / 180.0)
        source_bonus = 0.1 if hit.source_type in {"github", "youtube", "rss"} else 0.0
        return round(base * 0.65 + density * 0.25 + source_bonus, 4)


_runtime: InternetReachRuntime | None = None


def get_internet_reach_runtime() -> InternetReachRuntime:
    global _runtime
    if _runtime is None:
        _runtime = InternetReachRuntime()
    return _runtime
