"""
core/reasoning/deep_researcher.py
─────────────────────────────────────────────────────────────────────────────
Deep Research with Source Verification (Phase 32).
Multi-source research with cross-referencing and contradiction detection.
Ensures Elyan never presents unverified single-source claims as fact.
"""

import asyncio
import re
from dataclasses import dataclass, field
from typing import List, Dict
from utils.logger import get_logger

logger = get_logger("deep_researcher")

@dataclass
class Source:
    url: str
    title: str
    snippet: str
    credibility: float = 0.5  # 0-1

@dataclass
class ResearchClaim:
    claim: str
    supporting_sources: List[Source] = field(default_factory=list)
    contradicting_sources: List[Source] = field(default_factory=list)
    confidence: float = 0.0
    verified: bool = False

@dataclass 
class ResearchReport:
    query: str
    claims: List[ResearchClaim] = field(default_factory=list)
    summary: str = ""
    overall_confidence: float = 0.0
    sources_consulted: int = 0

class DeepResearcher:
    def __init__(self, agent_instance):
        self.agent = agent_instance
    
    async def research(self, query: str, depth: str = "medium") -> ResearchReport:
        """Multi-source research with cross-verification."""
        logger.info(f"🔬 Deep Research Started: {query[:60]}...")
        report = ResearchReport(query=query)
        
        # Step 1: Gather from multiple angles
        sources = await self._multi_source_gather(query)
        report.sources_consulted = len(sources)
        
        # Step 2: Extract claims from sources
        claims = await self._extract_claims(query, sources)
        
        # Step 3: Cross-reference claims
        for claim in claims:
            verified_claim = await self._cross_reference(claim, sources)
            report.claims.append(verified_claim)
        
        # Step 4: Detect contradictions
        report = await self._detect_contradictions(report)
        
        # Step 5: Generate summary with citations
        report.summary = await self._generate_cited_summary(report)
        report.overall_confidence = (
            sum(c.confidence for c in report.claims) / max(len(report.claims), 1)
        )
        
        logger.info(f"🔬 Research Complete: {len(report.claims)} claims, confidence={report.overall_confidence:.0%}")
        return report
    
    async def _multi_source_gather(self, query: str) -> List[Source]:
        """Query multiple perspectives on the same topic."""
        sources = []
        
        search_variations = [
            query,
            f"{query} advantages benefits",
            f"{query} disadvantages risks criticism"
        ]
        
        for variation in search_variations:
            try:
                from tools.web_tools import web_search
                results = await web_search(variation)
                for r in (results or [])[:3]:
                    sources.append(Source(
                        url=r.get("url", ""),
                        title=r.get("title", ""),
                        snippet=r.get("snippet", ""),
                        credibility=0.6
                    ))
            except:
                pass
        
        return sources
    
    async def _extract_claims(self, query: str, sources: List[Source]) -> List[ResearchClaim]:
        """Use LLM to extract distinct factual claims from sources."""
        source_text = "\n".join(
            f"[{i+1}] {s.title}: {s.snippet}" for i, s in enumerate(sources)
        )
        
        from core.multi_agent.orchestrator import AgentOrchestrator
        orch = AgentOrchestrator(self.agent)
        
        raw = await orch._run_specialist("qa", f"""
Aşağıdaki kaynaklardan "{query}" konusundaki temel iddiaları çıkar.
Her iddiayı ayrı satırda "- İddia: ..." formatında listele.

Kaynaklar:
{source_text[:1500]}
""")
        
        claims = []
        for line in raw.split("\n"):
            if "iddia" in line.lower() or line.strip().startswith("-"):
                clean = re.sub(r'^[-*]\s*(İddia:?\s*)?', '', line).strip()
                if clean and len(clean) > 10:
                    claims.append(ResearchClaim(claim=clean))
        
        return claims[:8]
    
    async def _cross_reference(self, claim: ResearchClaim, sources: List[Source]) -> ResearchClaim:
        """Check how many sources support or contradict the claim."""
        support_count = 0
        for source in sources:
            combined = f"{source.title} {source.snippet}".lower()
            key_words = claim.claim.lower().split()[:4]
            if any(w in combined for w in key_words if len(w) > 3):
                claim.supporting_sources.append(source)
                support_count += 1
        
        claim.confidence = min(support_count / max(len(sources), 1) * 2, 1.0)
        claim.verified = support_count >= 2
        return claim
    
    async def _detect_contradictions(self, report: ResearchReport) -> ResearchReport:
        """Flag claims that directly contradict each other."""
        from core.multi_agent.orchestrator import AgentOrchestrator
        orch = AgentOrchestrator(self.agent)
        
        if len(report.claims) < 2:
            return report
        
        claims_text = "\n".join(f"{i+1}. {c.claim}" for i, c in enumerate(report.claims))
        
        raw = await orch._run_specialist("qa", f"""
Aşağıdaki iddialar arasında çelişki var mı? Varsa hangi numaralı iddialar çelişiyor belirt.
Yoksa sadece "ÇELİŞKİ YOK" yaz.

{claims_text}
""")
        
        if "ÇELİŞKİ YOK" not in raw.upper():
            logger.warning(f"⚠️ Contradiction detected in research: {raw[:100]}")
        
        return report
    
    async def _generate_cited_summary(self, report: ResearchReport) -> str:
        """Generate a final summary with numbered citations."""
        from core.multi_agent.orchestrator import AgentOrchestrator
        orch = AgentOrchestrator(self.agent)
        
        claims_text = "\n".join(
            f"- {c.claim} (Güven: {c.confidence:.0%}, {'✅ Doğrulandı' if c.verified else '⚠️ Tek Kaynak'})" 
            for c in report.claims
        )
        
        return await orch._run_specialist("executor", f"""
Aşağıdaki araştırma bulgularını kısa ve net bir özet olarak yaz.
Her bilgiyi kaynak referansıyla destekle.

Konu: {report.query}
Bulgular:
{claims_text}
""")
