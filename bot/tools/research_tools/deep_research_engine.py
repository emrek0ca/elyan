"""
Deep Research Engine - Comprehensive Multi-Source Research System
Supports academic-level research with citation management and synthesis
"""

import asyncio
import aiohttp
import re
import json
import hashlib
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path
from dataclasses import dataclass, field
from enum import Enum
from bs4 import BeautifulSoup
from urllib.parse import urlparse, quote_plus
from utils.logger import get_logger

logger = get_logger("deep_research")


class ResearchDepth(Enum):
    QUICK = "quick"           # 3-5 sources, 2 min
    STANDARD = "standard"     # 8-12 sources, 5 min
    COMPREHENSIVE = "comprehensive"  # 15-25 sources, 10 min
    ACADEMIC = "academic"     # 25-40 sources, 15+ min


class CitationStyle(Enum):
    APA = "apa"
    MLA = "mla"
    CHICAGO = "chicago"
    HARVARD = "harvard"
    IEEE = "ieee"


@dataclass
class Source:
    """Represents a research source"""
    url: str
    title: str
    content: str
    author: str = "Unknown"
    date: str = ""
    domain: str = ""
    reliability_score: float = 0.5
    relevance_score: float = 0.5
    snippet: str = ""
    citations: int = 0
    source_type: str = "web"  # web, academic, news, wiki
    accessed_date: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d"))

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "title": self.title,
            "author": self.author,
            "date": self.date,
            "domain": self.domain,
            "reliability_score": self.reliability_score,
            "relevance_score": self.relevance_score,
            "snippet": self.snippet[:500] if self.snippet else "",
            "source_type": self.source_type,
            "accessed_date": self.accessed_date
        }


@dataclass
class Finding:
    """Represents a research finding"""
    content: str
    sources: List[str]  # URLs
    confidence: float
    category: str
    importance: int = 1  # 1-5
    keywords: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "content": self.content,
            "sources": self.sources,
            "confidence": self.confidence,
            "category": self.category,
            "importance": self.importance,
            "keywords": self.keywords
        }


@dataclass
class ResearchResult:
    """Complete research result"""
    topic: str
    depth: ResearchDepth
    sources: List[Source]
    findings: List[Finding]
    summary: str
    key_insights: List[str]
    statistics: Dict[str, Any]
    bibliography: List[str]
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    research_id: str = ""

    def __post_init__(self):
        if not self.research_id:
            self.research_id = hashlib.md5(f"{self.topic}{self.created_at}".encode()).hexdigest()[:12]


class DeepResearchEngine:
    """Advanced research engine with multi-source synthesis"""

    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        self.search_engines = [
            "https://html.duckduckgo.com/html/?q={}",
            "https://www.google.com/search?q={}",
        ]
        self.academic_sources = [
            "scholar.google.com",
            "arxiv.org",
            "researchgate.net",
            "academia.edu",
            "pubmed.ncbi.nlm.nih.gov",
            "jstor.org",
            "sciencedirect.com"
        ]
        self.news_sources = [
            "reuters.com", "bbc.com", "nytimes.com", "theguardian.com",
            "bloomberg.com", "economist.com", "ft.com"
        ]
        self.reliable_domains = [
            "gov", "edu", "org", "wikipedia.org", "britannica.com"
        ]
        self.user_agents = [
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        ]
        self.current_ua_index = 0

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=30)
            self.session = aiohttp.ClientSession(timeout=timeout)
        return self.session

    def _get_user_agent(self) -> str:
        ua = self.user_agents[self.current_ua_index]
        self.current_ua_index = (self.current_ua_index + 1) % len(self.user_agents)
        return ua

    async def research(
        self,
        topic: str,
        depth: ResearchDepth = ResearchDepth.STANDARD,
        language: str = "tr",
        focus_areas: List[str] = None,
        exclude_domains: List[str] = None,
        include_academic: bool = True,
        progress_callback: callable = None
    ) -> ResearchResult:
        """
        Conduct comprehensive research on a topic

        Args:
            topic: Research topic
            depth: Research depth level
            language: Primary language (tr/en)
            focus_areas: Specific areas to focus on
            exclude_domains: Domains to exclude
            include_academic: Include academic sources
            progress_callback: Callback for progress updates
        """
        logger.info(f"Starting {depth.value} research on: {topic}")

        # Determine source count based on depth
        source_counts = {
            ResearchDepth.QUICK: 5,
            ResearchDepth.STANDARD: 12,
            ResearchDepth.COMPREHENSIVE: 25,
            ResearchDepth.ACADEMIC: 40
        }
        target_sources = source_counts[depth]

        # Generate search queries
        queries = self._generate_queries(topic, focus_areas, language)

        if progress_callback:
            await progress_callback(5, "Arama sorguları oluşturuldu")

        # Fetch sources
        sources = await self._fetch_sources(
            queries,
            target_sources,
            exclude_domains or [],
            include_academic,
            progress_callback
        )

        if progress_callback:
            await progress_callback(50, f"{len(sources)} kaynak bulundu")

        # Extract and analyze content
        findings = await self._extract_findings(sources, topic, progress_callback)

        if progress_callback:
            await progress_callback(70, f"{len(findings)} bulgu çıkarıldı")

        # Synthesize results
        summary = self._synthesize_summary(findings, topic, language)
        key_insights = self._extract_key_insights(findings, topic)

        if progress_callback:
            await progress_callback(85, "Özet ve içgörüler oluşturuldu")

        # Generate bibliography
        bibliography = self._generate_bibliography(sources, CitationStyle.APA)

        # Calculate statistics
        statistics = self._calculate_statistics(sources, findings)

        if progress_callback:
            await progress_callback(100, "Araştırma tamamlandı")

        return ResearchResult(
            topic=topic,
            depth=depth,
            sources=sources,
            findings=findings,
            summary=summary,
            key_insights=key_insights,
            statistics=statistics,
            bibliography=bibliography
        )

    def _generate_queries(
        self,
        topic: str,
        focus_areas: List[str] = None,
        language: str = "tr"
    ) -> List[str]:
        """Generate diverse search queries"""
        queries = [topic]

        # Add language-specific variations
        if language == "tr":
            queries.extend([
                f"{topic} nedir",
                f"{topic} hakkında",
                f"{topic} araştırma",
                f"{topic} analiz",
                f"{topic} güncel bilgi",
                f"{topic} istatistik",
                f"{topic} tarihçe",
                f"{topic} uzman görüşü"
            ])
        else:
            queries.extend([
                f"what is {topic}",
                f"{topic} research",
                f"{topic} analysis",
                f"{topic} statistics",
                f"{topic} overview",
                f"{topic} latest news",
                f"{topic} expert opinion"
            ])

        # Add focus area queries
        if focus_areas:
            for area in focus_areas:
                queries.append(f"{topic} {area}")

        return queries[:15]  # Limit queries

    async def _fetch_sources(
        self,
        queries: List[str],
        target_count: int,
        exclude_domains: List[str],
        include_academic: bool,
        progress_callback: callable = None
    ) -> List[Source]:
        """Fetch sources from multiple search engines"""
        sources = []
        seen_urls = set()

        session = await self._get_session()

        for i, query in enumerate(queries):
            if len(sources) >= target_count:
                break

            try:
                # Search DuckDuckGo
                url = self.search_engines[0].format(quote_plus(query))
                headers = {"User-Agent": self._get_user_agent()}

                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        html = await response.text()
                        new_sources = await self._parse_search_results(
                            html, query, seen_urls, exclude_domains
                        )
                        sources.extend(new_sources)

                        for s in new_sources:
                            seen_urls.add(s.url)

                if progress_callback:
                    progress = 5 + int((i / len(queries)) * 40)
                    await progress_callback(progress, f"Sorgu {i+1}/{len(queries)} işleniyor")

                await asyncio.sleep(0.5)  # Rate limiting

            except Exception as e:
                logger.warning(f"Search error for query '{query}': {e}")
                continue

        # Score and sort sources
        for source in sources:
            source.reliability_score = self._calculate_reliability(source)

        sources.sort(key=lambda s: s.reliability_score, reverse=True)

        return sources[:target_count]

    async def _parse_search_results(
        self,
        html: str,
        query: str,
        seen_urls: set,
        exclude_domains: List[str]
    ) -> List[Source]:
        """Parse search results from HTML"""
        sources = []
        soup = BeautifulSoup(html, 'html.parser')

        # DuckDuckGo results
        results = soup.find_all('div', class_='result')
        if not results:
            results = soup.find_all('div', class_='links_main')

        for result in results[:10]:
            try:
                # Extract link
                link = result.find('a', class_='result__a') or result.find('a')
                if not link:
                    continue

                url = link.get('href', '')
                if not url or not url.startswith('http'):
                    continue

                # Skip excluded domains
                domain = urlparse(url).netloc
                if any(exc in domain for exc in exclude_domains):
                    continue

                if url in seen_urls:
                    continue

                # Extract title and snippet
                title = link.get_text(strip=True)
                snippet_elem = result.find('a', class_='result__snippet') or result.find('p')
                snippet = snippet_elem.get_text(strip=True) if snippet_elem else ""

                # Determine source type
                source_type = self._determine_source_type(domain)

                # Fetch full content
                content = await self._fetch_page_content(url)

                if content and len(content) > 100:
                    sources.append(Source(
                        url=url,
                        title=title,
                        content=content,
                        domain=domain,
                        snippet=snippet,
                        source_type=source_type
                    ))

            except Exception as e:
                logger.debug(f"Error parsing result: {e}")
                continue

        return sources

    async def _fetch_page_content(self, url: str) -> str:
        """Fetch and extract main content from a page"""
        try:
            session = await self._get_session()
            headers = {"User-Agent": self._get_user_agent()}

            async with session.get(url, headers=headers, allow_redirects=True) as response:
                if response.status != 200:
                    return ""

                content_type = response.headers.get('content-type', '')
                if 'text/html' not in content_type:
                    return ""

                html = await response.text()
                return self._extract_main_content(html)

        except Exception as e:
            logger.debug(f"Error fetching {url}: {e}")
            return ""

    def _extract_main_content(self, html: str) -> str:
        """Extract main textual content from HTML"""
        soup = BeautifulSoup(html, 'html.parser')

        # Remove unwanted elements
        for tag in soup(['script', 'style', 'nav', 'header', 'footer',
                        'aside', 'form', 'iframe', 'noscript']):
            tag.decompose()

        # Try to find main content
        main_content = None
        for selector in ['article', 'main', '.content', '.post', '#content', '.article']:
            main_content = soup.select_one(selector)
            if main_content:
                break

        if not main_content:
            main_content = soup.find('body')

        if not main_content:
            return ""

        # Extract text
        text = main_content.get_text(separator='\n', strip=True)

        # Clean up
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        lines = [line for line in lines if len(line) > 30]  # Filter short lines

        # Limit content size
        content = '\n'.join(lines)
        return content[:15000]  # Max 15KB of text

    def _determine_source_type(self, domain: str) -> str:
        """Determine the type of source"""
        domain_lower = domain.lower()

        if any(acad in domain_lower for acad in self.academic_sources):
            return "academic"
        elif any(news in domain_lower for news in self.news_sources):
            return "news"
        elif "wikipedia" in domain_lower:
            return "wiki"
        else:
            return "web"

    def _calculate_reliability(self, source: Source) -> float:
        """Calculate reliability score for a source"""
        score = 0.5

        domain = source.domain.lower()

        # Domain-based scoring
        if ".gov" in domain or ".edu" in domain:
            score += 0.3
        elif any(rel in domain for rel in self.reliable_domains):
            score += 0.2
        elif any(acad in domain for acad in self.academic_sources):
            score += 0.25
        elif any(news in domain for news in self.news_sources):
            score += 0.15

        # HTTPS bonus
        if source.url.startswith("https://"):
            score += 0.05

        # Content quality
        if source.content:
            # Length bonus
            if len(source.content) > 2000:
                score += 0.1

            # Citation indicators
            if any(word in source.content.lower() for word in
                   ['research', 'study', 'according to', 'araştırma', 'çalışma']):
                score += 0.05

        return min(1.0, score)

    async def _extract_findings(
        self,
        sources: List[Source],
        topic: str,
        progress_callback: callable = None
    ) -> List[Finding]:
        """Extract key findings from sources"""
        findings = []
        topic_words = set(topic.lower().split())

        for i, source in enumerate(sources):
            if not source.content:
                continue

            # Split into sentences
            sentences = re.split(r'[.!?]\s+', source.content)

            for sentence in sentences:
                sentence = sentence.strip()
                if len(sentence) < 50 or len(sentence) > 500:
                    continue

                # Calculate relevance
                sentence_words = set(sentence.lower().split())
                overlap = len(topic_words & sentence_words)
                relevance = overlap / max(len(topic_words), 1)

                if relevance > 0.3:
                    # Check if this is a factual statement
                    if self._is_factual_statement(sentence):
                        # Extract keywords
                        keywords = self._extract_keywords(sentence)

                        # Categorize
                        category = self._categorize_finding(sentence)

                        # Check for duplicates
                        is_duplicate = any(
                            self._similarity(sentence, f.content) > 0.8
                            for f in findings
                        )

                        if not is_duplicate:
                            findings.append(Finding(
                                content=sentence,
                                sources=[source.url],
                                confidence=source.reliability_score * relevance,
                                category=category,
                                importance=self._calculate_importance(sentence),
                                keywords=keywords
                            ))

            if progress_callback:
                progress = 50 + int((i / len(sources)) * 20)
                await progress_callback(progress, f"Kaynak {i+1}/{len(sources)} analiz ediliyor")

        # Sort by importance and confidence
        findings.sort(key=lambda f: (f.importance, f.confidence), reverse=True)

        return findings[:50]  # Top 50 findings

    def _is_factual_statement(self, sentence: str) -> bool:
        """Check if a sentence is a factual statement"""
        # Exclude questions
        if '?' in sentence:
            return False

        # Exclude imperative/commands
        imperative_starts = ['click', 'subscribe', 'sign up', 'tıkla', 'abone', 'kayıt']
        if any(sentence.lower().startswith(imp) for imp in imperative_starts):
            return False

        # Exclude navigation/UI text
        ui_words = ['menu', 'cookie', 'privacy', 'terms', 'login', 'giriş', 'menü']
        if any(ui in sentence.lower() for ui in ui_words):
            return False

        return True

    def _extract_keywords(self, text: str) -> List[str]:
        """Extract keywords from text"""
        # Simple keyword extraction
        words = re.findall(r'\b[a-zA-ZçğıöşüÇĞİÖŞÜ]{4,}\b', text.lower())

        # Remove common words
        stop_words = {
            'that', 'this', 'with', 'from', 'have', 'been', 'were', 'will',
            'olan', 'için', 'olan', 'gibi', 'daha', 'kadar', 'ancak', 'ise'
        }

        keywords = [w for w in words if w not in stop_words]

        # Count and return top keywords
        from collections import Counter
        counter = Counter(keywords)
        return [word for word, _ in counter.most_common(5)]

    def _categorize_finding(self, text: str) -> str:
        """Categorize a finding"""
        text_lower = text.lower()

        if any(w in text_lower for w in ['istatistik', 'yüzde', '%', 'oran', 'statistic', 'percent']):
            return "statistics"
        elif any(w in text_lower for w in ['tarih', 'yıl', 'history', 'year', 'century']):
            return "historical"
        elif any(w in text_lower for w in ['tanım', 'definition', 'nedir', 'what is']):
            return "definition"
        elif any(w in text_lower for w in ['araştırma', 'çalışma', 'research', 'study']):
            return "research"
        elif any(w in text_lower for w in ['uzman', 'expert', 'professor', 'doktor']):
            return "expert_opinion"
        else:
            return "general"

    def _calculate_importance(self, text: str) -> int:
        """Calculate importance score 1-5"""
        score = 1
        text_lower = text.lower()

        # Statistics boost
        if re.search(r'\d+%|\d+\s*(milyon|billion|million)', text_lower):
            score += 2

        # Research/study boost
        if any(w in text_lower for w in ['araştırma', 'çalışma', 'research', 'study']):
            score += 1

        # Expert opinion boost
        if any(w in text_lower for w in ['uzman', 'expert', 'professor']):
            score += 1

        return min(5, score)

    def _similarity(self, text1: str, text2: str) -> float:
        """Calculate simple similarity between two texts"""
        words1 = set(text1.lower().split())
        words2 = set(text2.lower().split())

        if not words1 or not words2:
            return 0.0

        intersection = len(words1 & words2)
        union = len(words1 | words2)

        return intersection / union if union > 0 else 0.0

    def _synthesize_summary(
        self,
        findings: List[Finding],
        topic: str,
        language: str = "tr"
    ) -> str:
        """Synthesize findings into a coherent summary"""
        if not findings:
            if language == "tr":
                return f"{topic} hakkında yeterli bilgi bulunamadı."
            return f"Insufficient information found about {topic}."

        # Group by category
        categories = {}
        for finding in findings:
            if finding.category not in categories:
                categories[finding.category] = []
            categories[finding.category].append(finding)

        # Build summary
        summary_parts = []

        # Definitions first
        if "definition" in categories:
            defs = categories["definition"][:2]
            summary_parts.append(defs[0].content)

        # Statistics
        if "statistics" in categories:
            stats = categories["statistics"][:3]
            for stat in stats:
                summary_parts.append(stat.content)

        # Research findings
        if "research" in categories:
            research = categories["research"][:3]
            for r in research:
                summary_parts.append(r.content)

        # Expert opinions
        if "expert_opinion" in categories:
            experts = categories["expert_opinion"][:2]
            for e in experts:
                summary_parts.append(e.content)

        # General information
        if "general" in categories:
            general = categories["general"][:3]
            for g in general:
                if g.importance >= 2:
                    summary_parts.append(g.content)

        return "\n\n".join(summary_parts[:10])

    def _extract_key_insights(self, findings: List[Finding], topic: str) -> List[str]:
        """Extract key insights from findings"""
        insights = []

        # Top findings by importance
        top_findings = sorted(findings, key=lambda f: (f.importance, f.confidence), reverse=True)[:10]

        for finding in top_findings:
            # Shorten if needed
            content = finding.content
            if len(content) > 200:
                content = content[:200] + "..."
            insights.append(content)

        return insights

    def _generate_bibliography(
        self,
        sources: List[Source],
        style: CitationStyle = CitationStyle.APA
    ) -> List[str]:
        """Generate bibliography in specified citation style"""
        bibliography = []

        for source in sources:
            citation = self._format_citation(source, style)
            if citation:
                bibliography.append(citation)

        return bibliography

    def _format_citation(self, source: Source, style: CitationStyle) -> str:
        """Format a single citation"""
        author = source.author if source.author != "Unknown" else source.domain
        title = source.title
        date = source.date or source.accessed_date
        url = source.url
        accessed = source.accessed_date

        if style == CitationStyle.APA:
            return f"{author}. ({date}). {title}. Retrieved from {url}"

        elif style == CitationStyle.MLA:
            return f'{author}. "{title}." Web. {accessed}. <{url}>'

        elif style == CitationStyle.CHICAGO:
            return f'{author}. "{title}." Accessed {accessed}. {url}.'

        elif style == CitationStyle.HARVARD:
            return f"{author} ({date}) {title}. Available at: {url} (Accessed: {accessed})"

        elif style == CitationStyle.IEEE:
            return f'{author}, "{title}," [Online]. Available: {url}. [Accessed: {accessed}]'

        return f"{author}. {title}. {url}"

    def _calculate_statistics(
        self,
        sources: List[Source],
        findings: List[Finding]
    ) -> Dict[str, Any]:
        """Calculate research statistics"""
        return {
            "total_sources": len(sources),
            "total_findings": len(findings),
            "source_types": {
                "academic": sum(1 for s in sources if s.source_type == "academic"),
                "news": sum(1 for s in sources if s.source_type == "news"),
                "wiki": sum(1 for s in sources if s.source_type == "wiki"),
                "web": sum(1 for s in sources if s.source_type == "web")
            },
            "finding_categories": {
                cat: sum(1 for f in findings if f.category == cat)
                for cat in set(f.category for f in findings)
            },
            "avg_reliability": sum(s.reliability_score for s in sources) / len(sources) if sources else 0,
            "avg_confidence": sum(f.confidence for f in findings) / len(findings) if findings else 0,
            "high_importance_findings": sum(1 for f in findings if f.importance >= 3)
        }

    async def close(self):
        """Close the session"""
        if self.session and not self.session.closed:
            await self.session.close()


# Singleton instance
_engine_instance = None


def get_research_engine() -> DeepResearchEngine:
    """Get or create research engine instance"""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = DeepResearchEngine()
    return _engine_instance


async def deep_research(
    topic: str,
    depth: str = "standard",
    language: str = "tr",
    focus_areas: List[str] = None,
    include_academic: bool = True
) -> Dict[str, Any]:
    """
    Perform deep research on a topic

    Args:
        topic: Research topic
        depth: Research depth (quick/standard/comprehensive/academic)
        language: Primary language
        focus_areas: Specific areas to focus on
        include_academic: Include academic sources

    Returns:
        Research results dictionary
    """
    try:
        engine = get_research_engine()

        # Map depth string to enum
        depth_map = {
            "quick": ResearchDepth.QUICK,
            "standard": ResearchDepth.STANDARD,
            "comprehensive": ResearchDepth.COMPREHENSIVE,
            "academic": ResearchDepth.ACADEMIC
        }
        research_depth = depth_map.get(depth.lower(), ResearchDepth.STANDARD)

        result = await engine.research(
            topic=topic,
            depth=research_depth,
            language=language,
            focus_areas=focus_areas,
            include_academic=include_academic
        )

        return {
            "success": True,
            "research_id": result.research_id,
            "topic": result.topic,
            "depth": result.depth.value,
            "summary": result.summary,
            "key_insights": result.key_insights,
            "findings": [f.to_dict() for f in result.findings[:20]],
            "sources": [s.to_dict() for s in result.sources],
            "statistics": result.statistics,
            "bibliography": result.bibliography,
            "created_at": result.created_at
        }

    except Exception as e:
        logger.error(f"Deep research error: {e}")
        return {
            "success": False,
            "error": str(e),
            "topic": topic
        }
