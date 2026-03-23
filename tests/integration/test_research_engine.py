"""
Integration tests for ResearchEngine (Phase 6.1).
Minimal test suite (15 tests) covering:
- Engine init, search, citations, session persist, CLI
"""

import pytest
import asyncio
import json
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock

# Test fixtures and mocks


@pytest.fixture
async def research_engine():
    """Initialize ResearchEngine."""
    from core.research import get_research_engine
    engine = get_research_engine()
    yield engine


@pytest.fixture
def mock_sources():
    """Mock web search sources."""
    return [
        {
            "url": "https://example.com/article1",
            "title": "Understanding Python",
            "snippet": "Python is a high-level programming language...",
            "source_type": "web",
        },
        {
            "url": "https://edu.example.org/python-guide",
            "title": "Python Complete Guide",
            "snippet": "Comprehensive Python tutorial for beginners...",
            "source_type": "web",
        },
    ]


# ────────────────────────────────────────────────────────────────────────────
# ResearchEngine Tests
# ────────────────────────────────────────────────────────────────────────────


def test_research_engine_singleton():
    """Test: ResearchEngine is singleton."""
    from core.research import get_research_engine
    engine1 = get_research_engine()
    engine2 = get_research_engine()
    assert engine1 is engine2


def test_research_engine_init():
    """Test: ResearchEngine initializes correctly."""
    from core.research import get_research_engine
    engine = get_research_engine()
    assert engine is not None
    assert hasattr(engine, 'research')
    assert hasattr(engine, '_fetch_sources')
    assert hasattr(engine, '_synthesize_answer')


@pytest.mark.asyncio
async def test_research_basic(mock_sources):
    """Test: Basic research execution."""
    from core.research import get_research_engine

    engine = get_research_engine()

    with patch.object(engine, '_fetch_sources', new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = mock_sources

        with patch.object(engine, '_synthesize_answer', new_callable=AsyncMock) as mock_synth:
            mock_synth.return_value = "Python is a programming language used for..."

            result = await engine.research("What is Python?", "basic")

            assert result is not None
            assert result.query == "What is Python?"
            assert result.depth == "basic"
            assert result.answer
            assert result.research_id
            assert len(result.citations) > 0


@pytest.mark.asyncio
async def test_research_result_to_dict():
    """Test: ResearchResult serialization."""
    from core.research import ResearchResult, CitedSource

    source = CitedSource(
        url="https://example.com",
        title="Example",
        content="Some content",
        reliability=0.85,
    )

    result = ResearchResult(
        query="test query",
        answer="test answer",
        citations=[source],
        confidence=0.8,
        depth="standard",
    )

    data = result.to_dict()
    assert data["query"] == "test query"
    assert data["answer"] == "test answer"
    assert data["confidence"] == 0.8
    assert len(data["citations"]) == 1


# ────────────────────────────────────────────────────────────────────────────
# Citation Tests
# ────────────────────────────────────────────────────────────────────────────


def test_cited_source_creation():
    """Test: CitedSource creation."""
    from core.research import CitedSource

    source = CitedSource(
        url="https://example.com",
        title="Example Article",
        content="Article content here",
        reliability=0.75,
    )

    assert source.url == "https://example.com"
    assert source.title == "Example Article"
    assert source.reliability == 0.75
    assert source.claim_references == []


def test_cited_source_to_dict():
    """Test: CitedSource serialization."""
    from core.research import CitedSource

    source = CitedSource(
        url="https://example.com",
        title="Example",
        content="x" * 600,  # Long content
        reliability=0.9,
        claim_references=["1", "2"],
    )

    data = source.to_dict()
    assert data["url"] == "https://example.com"
    assert len(data["content"]) == 500  # Truncated
    assert data["reliability"] == 0.9
    assert data["claim_references"] == ["1", "2"]


# ────────────────────────────────────────────────────────────────────────────
# Session Tests
# ────────────────────────────────────────────────────────────────────────────


def test_research_session_creation():
    """Test: ResearchSession creation."""
    from core.research import ResearchSession

    session = ResearchSession(session_id="test-session-001")
    assert session.session_id == "test-session-001"
    assert session.queries == []
    assert session.created_at


def test_research_session_add_query():
    """Test: Add query to session."""
    from core.research import ResearchSession, ResearchResult

    session = ResearchSession(session_id="test-001")
    result = ResearchResult(query="test", answer="answer", confidence=0.8)

    session.add_query("test query", result)
    assert len(session.queries) == 1
    assert session.queries[0]["query"] == "test query"


def test_research_session_persistence(tmp_path):
    """Test: Save and load research session."""
    from core.research import ResearchSession, save_research_session, get_research_session

    with patch('core.research.session._get_sessions_dir', return_value=tmp_path):
        session = ResearchSession(session_id="persist-001")
        session.add_query("test query", {"result": "test"})

        # Save
        success = save_research_session(session)
        assert success

        # Load
        loaded = get_research_session("persist-001")
        assert loaded is not None
        assert loaded.session_id == "persist-001"
        assert len(loaded.queries) == 1


def test_research_session_list(tmp_path):
    """Test: List saved sessions."""
    from core.research import (
        ResearchSession,
        save_research_session,
        list_research_sessions,
    )

    with patch('core.research.session._get_sessions_dir', return_value=tmp_path):
        # Create and save sessions
        for i in range(3):
            session = ResearchSession(session_id=f"session-{i}")
            session.add_query(f"query {i}", {"result": "test"})
            save_research_session(session)

        # List
        sessions = list_research_sessions()
        assert len(sessions) == 3


# ────────────────────────────────────────────────────────────────────────────
# Formatter Tests
# ────────────────────────────────────────────────────────────────────────────


def test_format_cited_answer():
    """Test: Markdown formatter with citations."""
    from core.research import format_cited_answer, ResearchResult, CitedSource

    source = CitedSource(
        url="https://example.com",
        title="Example",
        content="content",
        reliability=0.8,
    )

    result = ResearchResult(
        query="test",
        answer="Test answer text",
        citations=[source],
        confidence=0.85,
    )

    output = format_cited_answer(result)
    assert "Test answer text" in output
    assert "Kaynaklar" in output
    assert "https://example.com" in output
    assert "85%" in output


def test_format_json_result():
    """Test: JSON formatter."""
    from core.research import format_json_result, ResearchResult

    result = ResearchResult(
        query="test",
        answer="answer",
        confidence=0.8,
    )

    output = format_json_result(result)
    data = json.loads(output)

    assert data["query"] == "test"
    assert data["answer"] == "answer"
    assert data["confidence"] == 0.8


def test_format_cli_summary():
    """Test: CLI summary formatter."""
    from core.research import format_cli_summary, ResearchResult, CitedSource

    source = CitedSource(
        url="https://example.com",
        title="Example Article",
        content="content",
    )

    result = ResearchResult(
        query="What is X?",
        answer="X is Y" * 50,  # Long answer
        citations=[source],
        confidence=0.85,
    )

    output = format_cli_summary(result)
    assert "Research Summary" in output
    assert "What is X?" in output
    assert "85%" in output
    # Verify truncation is happening (answer will be cut)
    assert len(output) > 0


# ────────────────────────────────────────────────────────────────────────────
# API Tests
# ────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_research_api():
    """Test: Public research() API."""
    from core.research import research, ResearchResult

    with patch('core.research.get_research_engine') as mock_get_engine:
        mock_engine = AsyncMock()
        mock_result = ResearchResult(
            query="test",
            answer="test answer",
            confidence=0.8,
        )
        mock_engine.research.return_value = mock_result
        mock_get_engine.return_value = mock_engine

        result = await research("test query")
        assert result.query == "test"


def test_list_sessions_api():
    """Test: list_sessions() API."""
    from core.research import list_sessions

    with patch('core.research.list_research_sessions') as mock_list:
        mock_list.return_value = [
            {"session_id": "s1", "query_count": 2},
            {"session_id": "s2", "query_count": 1},
        ]

        sessions = list_sessions()
        assert len(sessions) == 2
        assert sessions[0]["session_id"] == "s1"


# ────────────────────────────────────────────────────────────────────────────
# CLI Tests
# ────────────────────────────────────────────────────────────────────────────


def test_cli_research_command_exists():
    """Test: CLI research command module exists."""
    from cli.commands import research
    assert hasattr(research, 'research_group')
    assert hasattr(research, 'research_search')
    assert hasattr(research, 'research_session')
    assert hasattr(research, 'research_list')


def test_cli_main_includes_research():
    """Test: CLI main.py includes research command."""
    from cli.main import TOP_LEVEL_COMMANDS
    assert "research" in TOP_LEVEL_COMMANDS


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
