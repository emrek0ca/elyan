"""
core/research — Research Engine
Perplexity-style multi-source research with citations, sessions, and LLM synthesis.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field
from datetime import datetime
import json

from .engine import ResearchEngine, ResearchResult, CitedSource
from .session import ResearchSession, get_research_session, list_research_sessions, save_research_session
from .formatter import format_cited_answer, format_json_result, format_cli_summary

_research_engine: Optional[ResearchEngine] = None


def get_research_engine() -> ResearchEngine:
    """Singleton: get or create ResearchEngine."""
    global _research_engine
    if _research_engine is None:
        _research_engine = ResearchEngine()
    return _research_engine


async def research(
    query: str,
    depth: str = "standard",
    session_id: Optional[str] = None,
    local_paths: Optional[list[str]] = None,
    include_web: bool = True,
) -> ResearchResult:
    """
    Execute research with optional session persistence.

    Args:
        query: Research query
        depth: "basic" (3-5 sources, ~2min), "standard" (8-12 sources, ~5min),
               "deep" (15-25 sources, ~10min), "academic" (25-40 sources, 15+min)
        session_id: Optional session ID for persistence

    Returns:
        ResearchResult with answer, citations, confidence, timestamp
    """
    engine = get_research_engine()
    result = await engine.research(query, depth, local_paths=local_paths, include_web=include_web)

    if session_id:
        session = ResearchSession(session_id=session_id)
        session.add_query(query, result)
        save_research_session(session)

    return result


def get_session(session_id: str) -> Optional[ResearchSession]:
    """Retrieve a past research session."""
    return get_research_session(session_id)


def list_sessions() -> list[dict]:
    """List all saved research sessions."""
    return list_research_sessions()


__all__ = [
    "ResearchEngine",
    "ResearchResult",
    "CitedSource",
    "ResearchSession",
    "get_research_engine",
    "research",
    "get_session",
    "list_sessions",
    "format_cited_answer",
    "format_json_result",
    "format_cli_summary",
]
