import asyncio

import pytest

from tools.office_tools.liteparse_adapter import _normalize_liteparse_payload, parse_document_with_liteparse
from tools.office_tools import pdf_tools


def test_normalize_liteparse_payload_extracts_pages():
    payload = {
        "pages": [
            {"page": 1, "markdown": "Hello world"},
            {"page": 2, "text": "Second page"},
        ],
        "metadata": {"kind": "pdf"},
    }
    result = _normalize_liteparse_payload(payload)
    assert "Hello world" in result["content"]
    assert len(result["pages"]) == 2
    assert result["metadata"]["page_count"] == 2


@pytest.mark.asyncio
async def test_parse_document_with_liteparse_uses_runner(monkeypatch, tmp_path):
    sample = tmp_path / "demo.pdf"
    sample.write_bytes(b"%PDF-1.4\n%EOF")

    async def _fake_runner(path):
        return {
            "success": True,
            "payload": {
                "pages": [{"page_number": 1, "text": "LiteParse content"}],
                "metadata": {"page_count": 1},
            },
        }

    monkeypatch.setattr("tools.office_tools.liteparse_adapter._run_liteparse", _fake_runner)
    result = await parse_document_with_liteparse(str(sample))
    assert result["success"] is True
    assert result["backend"] == "liteparse"
    assert "LiteParse content" in result["content"]


def test_read_pdf_prefers_liteparse(monkeypatch, tmp_path):
    sample = tmp_path / "demo.pdf"
    sample.write_bytes(b"%PDF-1.4\n%EOF")

    class _Settings:
        def _load(self):
            return None

        def get(self, key, default=None):
            if key == "liteparse_enabled":
                return True
            return default

    async def _fake_liteparse(path):
        return {
            "success": True,
            "content": "Primary content",
            "pages": [{"page_number": 1, "text": "Primary content"}],
            "metadata": {"page_count": 1},
            "screenshots": [],
        }

    monkeypatch.setattr(pdf_tools, "validate_path", lambda _p: (True, "", None))
    monkeypatch.setattr(pdf_tools, "SettingsPanel", lambda: _Settings())
    monkeypatch.setattr("tools.office_tools.liteparse_adapter.parse_document_with_liteparse", _fake_liteparse)

    result = asyncio.run(pdf_tools.read_pdf(str(sample), extract_tables=False, use_ocr=False))
    assert result["success"] is True
    assert result["backend"] == "liteparse"
    assert "Primary content" in result["content"]
