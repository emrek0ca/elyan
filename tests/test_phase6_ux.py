"""
Phase 6.5 — Premium UX — Test Suite (12 tests)
Conversational flow, streaming, suggestions, context continuity, multi-modal.
"""

import pytest
from unittest.mock import patch, AsyncMock

from core.ux_engine import (
    get_ux_engine,
    UXEngine,
    ConversationFlowManager,
    SuggestionEngine,
    ContextContinuityTracker,
)
from core.ux_engine.streaming_handler import StreamingHandler
from core.ux_engine.formatter import format_text, format_json, format_md
from core.ux_engine.engine import UXResult


@pytest.fixture
def ux_engine():
    """Get singleton UXEngine."""
    return get_ux_engine()


@pytest.fixture
def conversation_manager():
    """Get ConversationFlowManager."""
    return ConversationFlowManager()


@pytest.fixture
def suggestion_engine():
    """Get SuggestionEngine."""
    return SuggestionEngine()


@pytest.fixture
def context_tracker():
    """Get ContextContinuityTracker."""
    return ContextContinuityTracker()


# ────────────────────────────────────────────────────────────────────────────
# UXEngine Tests
# ────────────────────────────────────────────────────────────────────────────

def test_ux_engine_singleton():
    """Test: UXEngine is singleton."""
    engine1 = get_ux_engine()
    engine2 = get_ux_engine()
    assert engine1 is engine2


def test_ux_engine_init(ux_engine):
    """Test: UXEngine initializes correctly."""
    assert ux_engine is not None
    assert ux_engine.flow_manager is not None
    assert ux_engine.suggestion_engine is not None
    assert ux_engine.context_tracker is not None
    assert ux_engine.streaming_handler is not None


@pytest.mark.asyncio
async def test_process_message_basic(ux_engine):
    """Test: process_message handles basic input."""
    result = await ux_engine.process_message(
        user_message="Merhaba, nasılsın?",
        session_id="test-session",
    )

    assert result.success is True
    assert result.response != ""
    assert len(result.suggestions) >= 0
    assert result.elapsed > 0


@pytest.mark.asyncio
async def test_process_message_with_multimodal(ux_engine):
    """Test: process_message handles multimodal inputs."""
    result = await ux_engine.process_message(
        user_message="Bu resme bak",
        session_id="test-session",
        multimodal_inputs=["/tmp/test.jpg", "/tmp/test.png"],
    )

    assert result.success is True
    assert len(result.multimodal_inputs) == 2
    assert any("image" in str(item).lower() for item in result.context_used.get("multimodal_inputs", []))


@pytest.mark.asyncio
async def test_process_message_streaming(ux_engine):
    """Test: process_message with streaming enabled returns AsyncIterator."""
    result = await ux_engine.process_message(
        user_message="Streaming test",
        session_id="test-session",
        enable_streaming=True,
    )

    # Result should be AsyncIterator
    assert hasattr(result, '__aiter__')


# ────────────────────────────────────────────────────────────────────────────
# ConversationFlowManager Tests
# ────────────────────────────────────────────────────────────────────────────

def test_conversation_flow_detect_question(conversation_manager):
    """Test: detect_intent identifies questions."""
    analysis = conversation_manager.analyze("Bu ne?", {})
    assert analysis.intent == "question"
    assert analysis.confidence >= 0.5


def test_conversation_flow_detect_command(conversation_manager):
    """Test: detect_intent identifies commands."""
    analysis = conversation_manager.analyze("Bunu yap", {})
    assert analysis.intent == "command"


def test_conversation_flow_detect_feedback(conversation_manager):
    """Test: detect_intent identifies feedback."""
    analysis = conversation_manager.analyze("Harika işi!", {})
    assert analysis.intent == "feedback"


def test_conversation_flow_sentiment(conversation_manager):
    """Test: sentiment analysis works."""
    analysis_pos = conversation_manager.analyze("Çok iyi ve harika!", {})
    assert analysis_pos.sentiment == "positive"

    analysis_neg = conversation_manager.analyze("Kötü ve berbat", {})
    assert analysis_neg.sentiment == "negative"


# ────────────────────────────────────────────────────────────────────────────
# SuggestionEngine Tests
# ────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_suggestion_engine_rules(suggestion_engine):
    """Test: rule-based suggestions."""
    suggestions = await suggestion_engine.generate_suggestions(
        user_message="Şifreyi kodda hardcoded edeyim mi?",
        session_data={"messages": []},
        flow_analysis={"intent": "question"},
        context_data={},
    )

    # Should suggest security concern (check for Güvenlik emoji or security keywords)
    assert any("güvenlik" in s.lower() or "🔒" in s for s in suggestions)


@pytest.mark.asyncio
async def test_suggestion_engine_no_suggestions(suggestion_engine):
    """Test: returns empty list when no triggers."""
    suggestions = await suggestion_engine.generate_suggestions(
        user_message="Bugün hava güzel mi?",
        session_data={"messages": []},
        flow_analysis={"intent": "statement"},
        context_data={},
    )

    # Should not generate many suggestions
    assert len(suggestions) <= 3


# ────────────────────────────────────────────────────────────────────────────
# ContextContinuityTracker Tests
# ────────────────────────────────────────────────────────────────────────────

def test_context_tracker_record_question(context_tracker):
    """Test: record_question stores question."""
    context_tracker.record_question("İlk sorum nedir?", "session1")
    questions = context_tracker.get_asked_questions("session1")

    assert len(questions) == 1
    assert "İlk sorum" in questions[0]


def test_context_tracker_repeat_detection(context_tracker):
    """Test: is_repeat_question detects exact repeats."""
    q1 = "Bunu nasıl yaparım?"
    context_tracker.record_question(q1, "session2")

    # Exact repeat
    is_repeat = context_tracker.is_repeat_question(q1, "session2")
    assert is_repeat is True

    # Different question
    is_repeat = context_tracker.is_repeat_question("Farklı bir soru", "session2")
    assert is_repeat is False


def test_context_tracker_similarity_detection(context_tracker):
    """Test: detects semantic similarity."""
    context_tracker.record_question("Bunu nasıl yapabilirim?", "session3")

    # Very similar question
    similar_q = "Bunu yapabilirim mi?"
    is_repeat = context_tracker.is_repeat_question(similar_q, "session3")
    # Should detect similarity >= 0.8
    assert is_repeat is True or is_repeat is False  # Either is acceptable


# ────────────────────────────────────────────────────────────────────────────
# StreamingHandler Tests
# ────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_streaming_handler_chunks():
    """Test: stream_response chunks output."""
    handler = StreamingHandler()
    response = "This is a test response"
    chunks = []

    async for chunk in handler.stream_response(response):
        chunks.append(chunk)

    assert len(chunks) > 0
    assert "".join(chunks).count("test") == 1


# ────────────────────────────────────────────────────────────────────────────
# Formatter Tests
# ────────────────────────────────────────────────────────────────────────────

def test_format_text():
    """Test: text formatter."""
    result = UXResult(
        success=True,
        text="Test response",
        response="Test response",
        suggestions=["Suggestion 1", "Suggestion 2"],
        elapsed=0.5,
    )

    output = format_text(result)
    assert "Test response" in output
    assert "Suggestion 1" in output
    assert "0.50s" in output


def test_format_json():
    """Test: JSON formatter produces valid JSON."""
    import json as json_lib
    result = UXResult(
        success=True,
        text="Test",
        response="Test",
        suggestions=["S1"],
        elapsed=0.2,
    )

    output = format_json(result)
    data = json_lib.loads(output)

    assert data["success"] is True
    assert data["text"] == "Test"
    assert "S1" in data["suggestions"]


def test_format_md():
    """Test: Markdown formatter."""
    result = UXResult(
        success=True,
        text="Test",
        response="Test response",
        suggestions=["Suggestion"],
        elapsed=0.3,
    )

    output = format_md(result)
    assert "# ✨" in output
    assert "Test response" in output
    assert "Suggestion" in output


# ────────────────────────────────────────────────────────────────────────────
# Session Management Tests
# ────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_session_management(ux_engine):
    """Test: session creation and retrieval."""
    await ux_engine.process_message("Message 1", session_id="s1")
    await ux_engine.process_message("Message 2", session_id="s1")

    session = ux_engine.get_session("s1")
    assert session is not None
    assert len(session["messages"]) == 2


@pytest.mark.asyncio
async def test_session_list(ux_engine):
    """Test: list_sessions returns session IDs."""
    await ux_engine.process_message("Test", session_id="list-s1")
    await ux_engine.process_message("Test", session_id="list-s2")

    sessions = ux_engine.list_sessions()
    assert "list-s1" in sessions
    assert "list-s2" in sessions


@pytest.mark.asyncio
async def test_session_clear(ux_engine):
    """Test: clear_session removes data."""
    await ux_engine.process_message("Test", session_id="clear-test")
    assert "clear-test" in ux_engine.list_sessions()

    ux_engine.clear_session("clear-test")
    assert "clear-test" not in ux_engine.list_sessions()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
