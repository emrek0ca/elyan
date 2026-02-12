"""
Gelişmiş Araştırma Araçları - Advanced Research Tools
Çoklu kaynak araştırma, sentez ve değerlendirme
"""

from .advanced_research import (
    advanced_research,
    evaluate_source,
    quick_research,
    save_research_to_document
)
from .research_synthesizer import (
    synthesize_findings,
    create_research_report
)
from .deep_research_engine import (
    DeepResearchEngine,
    ResearchDepth,
    CitationStyle,
    Source,
    Finding,
    ResearchResult,
    get_research_engine,
    deep_research
)

__all__ = [
    "advanced_research",
    "evaluate_source",
    "quick_research",
    "save_research_to_document",
    "synthesize_findings",
    "create_research_report",
    # Deep Research Engine
    "DeepResearchEngine",
    "ResearchDepth",
    "CitationStyle",
    "Source",
    "Finding",
    "ResearchResult",
    "get_research_engine",
    "deep_research"
]
