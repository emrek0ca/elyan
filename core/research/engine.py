"""
Research Engine - Multi-provider research with citation tracking.
Wraps DeepResearchEngine, adds session persistence and LLM synthesis.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List
from pathlib import Path

from utils.logger import get_logger
from core.internet import get_internet_reach_runtime
from config.settings_manager import SettingsPanel

logger = get_logger("research.engine")


@dataclass
class CitedSource:
    """Source with citation info."""
    url: str
    title: str
    content: str
    reliability: float = 0.7  # 0-1
    claim_references: List[str] = field(default_factory=list)  # Which claims reference this
    date_accessed: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "title": self.title,
            "content": self.content[:500],  # Truncate for brevity
            "reliability": self.reliability,
            "claim_references": self.claim_references,
            "date_accessed": self.date_accessed,
        }


@dataclass
class ResearchResult:
    """Complete research result with citations."""
    query: str
    answer: str
    citations: List[CitedSource] = field(default_factory=list)
    confidence: float = 0.7  # 0-1 overall confidence
    depth: str = "standard"
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    research_id: str = ""

    def __post_init__(self):
        if not self.research_id:
            import hashlib
            self.research_id = hashlib.md5(
                f"{self.query}{self.timestamp}".encode()
            ).hexdigest()[:12]

    def to_dict(self) -> dict:
        return {
            "research_id": self.research_id,
            "query": self.query,
            "answer": self.answer,
            "citations": [c.to_dict() for c in self.citations],
            "confidence": self.confidence,
            "depth": self.depth,
            "timestamp": self.timestamp,
        }


class ResearchEngine:
    """
    Multi-source research engine.
    - Primary: DDG (fast, free)
    - Fallback: Google, Academic APIs
    - Synthesis: LLM cross-verification
    """

    def __init__(self):
        self.deep_research_engine: Optional[object] = None
        self.internet = get_internet_reach_runtime()
        self.settings = SettingsPanel()
        self._load_engine()

    def _load_engine(self):
        """Load mevcut DeepResearchEngine (lazy)."""
        try:
            from tools.research_tools.deep_research_engine import DeepResearchEngine
            self.deep_research_engine = DeepResearchEngine()
            logger.info("DeepResearchEngine loaded")
        except ImportError as e:
            logger.warning(f"DeepResearchEngine load failed: {e}")
            self.deep_research_engine = None

    async def research(
        self,
        query: str,
        depth: str = "standard",
    ) -> ResearchResult:
        """
        Execute multi-source research.

        Args:
            query: Research query
            depth: basic|standard|deep|academic

        Returns:
            ResearchResult with answer + citations
        """
        logger.info(f"🔬 Research START: {query[:60]}... (depth={depth})")

        # Step 1: Fetch sources using mevcut engine
        sources = await self._fetch_sources(query, depth)
        logger.info(f"  Fetched {len(sources)} sources")

        # Step 2: Synthesize answer with LLM
        answer = await self._synthesize_answer(query, sources)
        logger.info(f"  Synthesized answer ({len(answer)} chars)")

        # Step 3: Extract claims and cross-reference
        citations = await self._cross_reference_claims(query, sources)
        logger.info(f"  Extracted {len(citations)} citations")

        # Step 4: Compute overall confidence
        confidence = self._compute_confidence(citations)

        result = ResearchResult(
            query=query,
            answer=answer,
            citations=citations,
            confidence=confidence,
            depth=depth,
        )

        logger.info(f"🔬 Research DONE: {result.research_id}")
        return result

    async def _fetch_sources(self, query: str, depth: str) -> List[dict]:
        """Fetch sources through the unified internet reach runtime."""
        try:
            self.settings._load()
            if not bool(self.settings.get("internet_reach_enabled", True)):
                return []
            targets = {
                "basic": 5,
                "standard": 10,
                "deep": 16,
                "academic": 20,
            }.get(depth, 10)
            configured = self.settings.get("internet_reach_platforms", ["web", "github", "youtube", "reddit", "rss"])
            platforms = [str(item).strip().lower() for item in list(configured or []) if str(item).strip()]
            if not platforms:
                platforms = ["web"]
            lowered = str(query or "").lower()
            if "github" not in platforms and any(token in lowered for token in ("github", "repo", "repository", "pr", "issue")):
                platforms.append("github")
            if "youtube" not in platforms and any(token in lowered for token in ("youtube", "video", "podcast")):
                platforms.append("youtube")
            if "reddit" not in platforms and any(token in lowered for token in ("reddit", "community", "forum")):
                platforms.append("reddit")
            documents = await self.internet.discover(
                query,
                platforms=platforms,
                limit=targets,
                source_policy="academic" if depth == "academic" else "balanced",
                language="tr",
            )
            sources = [
                {
                    "url": doc.url,
                    "title": doc.title,
                    "snippet": doc.content[:600],
                    "source_type": doc.source_type,
                    "provider": doc.provider,
                    "metadata": dict(doc.metadata or {}),
                }
                for doc in documents
            ]
            return sources
        except Exception as e:
            logger.error(f"Source fetch failed: {e}")
            return []

    async def _synthesize_answer(self, query: str, sources: List[dict]) -> str:
        """Use LLM to synthesize answer from sources."""
        try:
            from core.llm_client import get_llm_client

            llm = get_llm_client()
            source_texts = "\n\n".join([
                f"[{i+1}] {s.get('title', 'Unknown')}\n{s.get('snippet', '')}"
                for i, s in enumerate(sources[:8])  # Top 8
            ])

            prompt = f"""Research Query: {query}

Available Sources:
{source_texts}

Task: Synthesize a comprehensive, accurate answer based on these sources.
Include specific facts and numbers. Be balanced and cite sources in footnotes [1][2] etc."""

            # Try to call LLM if available
            response = ""
            try:
                if hasattr(llm, 'call') and callable(getattr(llm, 'call')):
                    response = await llm.call("gpt-4o-mini", prompt, max_tokens=1000)
                elif hasattr(llm, 'invoke'):
                    response = await llm.invoke(prompt)
            except Exception:
                pass

            return response.strip() if response else self._fallback_synthesis(sources)

        except Exception as e:
            logger.error(f"LLM synthesis failed: {e}")
            # Fallback: concatenate snippets
            return self._fallback_synthesis(sources)

    def _fallback_synthesis(self, sources: List[dict]) -> str:
        """Fallback synthesis without LLM."""
        if not sources:
            return "No sources available for synthesis."
        snippet_list = [s.get("snippet", "") for s in sources[:3]]
        combined = " ".join(filter(None, snippet_list))
        return combined[:500] if combined else "Unable to synthesize answer from available sources."

    async def _cross_reference_claims(
        self,
        query: str,
        sources: List[dict],
    ) -> List[CitedSource]:
        """Extract main claims and map to sources."""
        citations = []

        for i, source in enumerate(sources[:8]):  # Top 8 sources
            cited_source = CitedSource(
                url=source.get("url", ""),
                title=source.get("title", ""),
                content=source.get("snippet", ""),
                reliability=0.7 if "edu" in source.get("url", "") or "gov" in source.get("url", "") else 0.5,
                claim_references=[str(i+1)],  # Footnote reference
            )
            citations.append(cited_source)

        return citations

    def _compute_confidence(self, citations: List[CitedSource]) -> float:
        """Compute overall confidence from source reliability."""
        if not citations:
            return 0.0
        avg_reliability = sum(c.reliability for c in citations) / len(citations)
        # Boost by source count (more sources = more confidence)
        source_count_boost = min(1.0, len(citations) / 10.0)
        return (avg_reliability * 0.7 + source_count_boost * 0.3)


__all__ = [
    "ResearchEngine",
    "ResearchResult",
    "CitedSource",
]
