"""
Phase 6.2 — Visual Intelligence — Test Suite (13 tests)
"""

import pytest
import json
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock

from core.vision import (
    get_vision_engine,
    VisionResult,
    get_vision_session,
    list_vision_sessions,
    save_vision_session,
    format_text,
    format_json,
    format_md,
)


@pytest.fixture
def vision_engine():
    """Get singleton VisionEngine."""
    return get_vision_engine()


@pytest.fixture
def mock_analyze_image():
    """Mock vision_tools.analyze_image()."""
    with patch("tools.vision_tools.analyze_image") as mock:
        mock.return_value = {
            "success": True,
            "analysis": "Mock visual analysis result",
            "provider": "gemini",
        }
        yield mock


@pytest.fixture
def mock_screenshot():
    """Mock system_tools.take_screenshot()."""
    with patch("tools.system_tools.take_screenshot") as mock:
        mock.return_value = {
            "success": True,
            "path": "/tmp/screenshot.png",
            "method": "screencapture",
        }
        yield mock


@pytest.fixture
def mock_ocr():
    """Mock screen_operator OCR."""
    with patch("core.capabilities.screen_operator.services._default_ocr") as mock:
        mock.return_value = {
            "success": True,
            "text": "Hello World",
            "lines": [{"text": "Hello", "x": 10, "y": 20, "w": 50, "h": 20, "confidence": 0.95}],
        }
        yield mock


@pytest.fixture
def mock_accessibility():
    """Mock accessibility snapshot."""
    with patch("core.capabilities.screen_operator.services._default_accessibility_snapshot") as mock:
        mock.return_value = {
            "success": True,
            "frontmost_app": "Safari",
            "window_title": "Google",
            "elements": [
                {"role": "button", "label": "Search"},
                {"role": "text_field", "label": "Query"},
            ],
        }
        yield mock


# ────────────────────────────────────────────────────────────────────────────
# VisionEngine Tests
# ────────────────────────────────────────────────────────────────────────────

def test_vision_engine_singleton():
    """Test: VisionEngine is singleton."""
    engine1 = get_vision_engine()
    engine2 = get_vision_engine()
    assert engine1 is engine2


def test_vision_engine_init():
    """Test: VisionEngine initializes correctly."""
    engine = get_vision_engine()
    assert engine is not None
    assert hasattr(engine, 'capture_and_analyze')
    assert hasattr(engine, 'ocr')
    assert hasattr(engine, 'accessibility')


@pytest.mark.asyncio
async def test_capture_and_analyze_with_path(mock_analyze_image):
    """Test: analyze_image with file path."""
    # Create temp file
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        temp_path = f.name

    try:
        engine = get_vision_engine()
        with patch.object(engine, '_analyze_tool', new_callable=AsyncMock) as mock_tool:
            mock_tool.return_value = {
                "success": True,
                "analysis": "Test analysis",
                "provider": "gemini",
            }
            result = await engine.capture_and_analyze(temp_path, "Test prompt")

            assert result.success
            assert result.text == "Test analysis"
            assert result.source == "gemini"
            # Path might be resolved to /private/... on macOS, just check basename
            assert Path(result.image_path).name == Path(temp_path).name
    finally:
        Path(temp_path).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_capture_and_analyze_live_screenshot(mock_screenshot):
    """Test: analyze_image with live screenshot (None target)."""
    engine = get_vision_engine()
    with patch.object(engine, '_screenshot_tool', new_callable=AsyncMock) as mock_ss:
        with patch.object(engine, '_analyze_tool', new_callable=AsyncMock) as mock_analyze:
            mock_ss.return_value = {"success": True, "path": "/tmp/test.png"}
            mock_analyze.return_value = {"success": True, "analysis": "Live result", "provider": "ollama"}

            result = await engine.capture_and_analyze(None, "Prompt")

            assert result.success
            assert result.text == "Live result"


@pytest.mark.asyncio
async def test_ocr_with_path(mock_ocr):
    """Test: OCR on file path."""
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        temp_path = f.name

    try:
        engine = get_vision_engine()
        with patch.object(engine, '_ocr_tool', new_callable=AsyncMock) as mock_tool:
            mock_tool.return_value = {"success": True, "text": "OCR text"}

            result = await engine.ocr(temp_path)

            assert result.success
            assert result.text == "OCR text"
            assert result.source == "tesseract"
    finally:
        Path(temp_path).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_ocr_live_screenshot(mock_screenshot):
    """Test: OCR on live screenshot."""
    engine = get_vision_engine()
    with patch.object(engine, '_screenshot_tool', new_callable=AsyncMock) as mock_ss:
        with patch.object(engine, '_ocr_tool', new_callable=AsyncMock) as mock_ocr:
            mock_ss.return_value = {"success": True, "path": "/tmp/test.png"}
            mock_ocr.return_value = {"success": True, "text": "Screenshot text"}

            result = await engine.ocr(None)

            assert result.success
            assert result.text == "Screenshot text"


@pytest.mark.asyncio
async def test_accessibility_snapshot(mock_accessibility):
    """Test: accessibility snapshot."""
    engine = get_vision_engine()
    with patch.object(engine, '_accessibility_tool', new_callable=AsyncMock) as mock_tool:
        mock_tool.return_value = {
            "success": True,
            "frontmost_app": "Safari",
            "window_title": "Google",
            "elements": [{"role": "button"}],
        }

        result = await engine.accessibility()

        assert result.success
        assert "Safari" in result.text
        assert result.source == "applescript"


def test_missing_file_returns_error():
    """Test: missing file returns error."""
    import asyncio
    engine = get_vision_engine()
    result = asyncio.run(engine.capture_and_analyze("/nonexistent/file.png", "Prompt"))

    assert not result.success
    assert result.image_path is None


def test_vision_result_fields():
    """Test: VisionResult dataclass fields."""
    result = VisionResult(
        success=True,
        text="Test",
        image_path="/tmp/test.png",
        source="gemini",
    )

    assert result.success
    assert result.text == "Test"
    assert result.image_path == "/tmp/test.png"
    assert result.source == "gemini"
    assert result.timestamp


# ────────────────────────────────────────────────────────────────────────────
# VisionSession Tests
# ────────────────────────────────────────────────────────────────────────────

def test_vision_session_save_and_load(tmp_path):
    """Test: VisionSession save and load."""
    from core.vision.session import VisionSession, _get_session_path

    with patch("core.vision.session._get_sessions_dir", return_value=tmp_path):
        session = VisionSession(session_id="test-001")
        session.add_entry("/tmp/test.png", "comprehensive", "Test analysis")

        # Save
        success = save_vision_session(session)
        assert success

        # Load
        loaded = get_vision_session("test-001")
        assert loaded is not None
        assert loaded.session_id == "test-001"
        assert len(loaded.entries) == 1
        assert loaded.entries[0]["text"] == "Test analysis"


def test_vision_session_list(tmp_path):
    """Test: list_vision_sessions."""
    from core.vision.session import VisionSession

    with patch("core.vision.session._get_sessions_dir", return_value=tmp_path):
        for i in range(3):
            session = VisionSession(session_id=f"session-{i}")
            session.add_entry(f"/tmp/test{i}.png", "ocr", f"Text {i}")
            save_vision_session(session)

        sessions = list_vision_sessions()
        assert len(sessions) == 3


def test_vision_session_nonexistent_returns_none():
    """Test: get_vision_session returns None for missing session."""
    result = get_vision_session("nonexistent-session")
    assert result is None


# ────────────────────────────────────────────────────────────────────────────
# Formatter Tests
# ────────────────────────────────────────────────────────────────────────────

def test_format_text():
    """Test: text formatter."""
    result = VisionResult(
        success=True,
        text="Test analysis result",
        image_path="/tmp/test.png",
        source="gemini",
    )

    output = format_text(result)
    assert "Test analysis result" in output
    assert "/tmp/test.png" in output


def test_format_json_valid():
    """Test: JSON formatter produces valid JSON."""
    result = VisionResult(
        success=True,
        text="Test result",
        source="ollama",
    )

    output = format_json(result)
    data = json.loads(output)

    assert data["success"]
    assert data["text"] == "Test result"
    assert data["source"] == "ollama"


def test_format_md_has_header():
    """Test: Markdown formatter has header."""
    result = VisionResult(
        success=True,
        text="Test markdown result",
        source="gemini",
    )

    output = format_md(result)
    assert "#" in output  # Markdown header
    assert "Test markdown result" in output


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
