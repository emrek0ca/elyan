
import pytest
import asyncio
from pathlib import Path
from tools.office_tools.word_tools import write_word
from tools.file_tools import write_file
from core.output_contract import get_contract_engine

@pytest.mark.asyncio
async def test_word_content_length_guard():
    """Test that write_word rejects short content."""
    # This should trigger CONTENT_TOO_SHORT
    result = await write_word(path="test.docx", content="Too short")
    assert result["success"] is False
    assert result["error_code"] == "CONTENT_TOO_SHORT"

@pytest.mark.asyncio
async def test_file_docx_fallback_guard():
    """Test that write_file rejects .docx extension."""
    # This should trigger DOCX_UNAVAILABLE
    result = await write_file(path="test.docx", content="Some valid long enough content that should still fail because of extension.")
    assert result["success"] is False
    assert result["error_code"] == "DOCX_UNAVAILABLE"


@pytest.mark.asyncio
async def test_write_file_allows_short_content_for_explicit_notes():
    result = await write_file(
        path="test_note.txt",
        content="sen kimsin",
        allow_short_content=True,
    )
    assert result["success"] is True
    assert result["size"] == len("sen kimsin")

@pytest.mark.asyncio
async def test_output_contract_web_project():
    """Test that web project spec requires semantic elements."""
    engine = get_contract_engine()
    params = {
        "project_name": "test_site",
        "output_dir": "~/Desktop"
    }
    spec = engine.create_spec("create_web_project_scaffold", params)
    assert spec is not None
    
    # Check that index.html artifact has the required patterns we added
    html_artifact = next(a for a in spec.artifacts if a.path.endswith("index.html"))
    assert "<nav" in html_artifact.required_patterns
    assert "<section" in html_artifact.required_patterns
    assert html_artifact.min_size_bytes >= 2500
