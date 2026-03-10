from __future__ import annotations

import pytest

from tools.browser import automation as browser_automation
from tools.browser import scraper as browser_scraper


@pytest.mark.asyncio
async def test_browser_open_wrapper_maps_runtime_result(monkeypatch):
    async def _fake_run_browser_runtime(**kwargs):
        _ = kwargs
        return {
            "success": True,
            "url": "https://example.com",
            "title": "Example Domain",
            "message": "Example Domain",
            "action_result": {"status_code": 200},
            "artifacts": [{"path": "/tmp/page.png", "type": "image"}],
            "verifier_outcomes": [{"ok": True}],
            "fallback": {"used": False},
        }

    monkeypatch.setattr("core.capabilities.browser.run_browser_runtime", _fake_run_browser_runtime)

    result = await browser_automation.browser_open("https://example.com")

    assert result["success"] is True
    assert result["url"] == "https://example.com"
    assert result["status"] == 200


@pytest.mark.asyncio
async def test_browser_get_text_wrapper_returns_extracted_text(monkeypatch):
    async def _fake_run_browser_runtime(**kwargs):
        _ = kwargs
        return {"success": True, "extracted_text": "Visible page text"}

    monkeypatch.setattr("core.capabilities.browser.run_browser_runtime", _fake_run_browser_runtime)

    result = await browser_automation.browser_get_text("main")

    assert result == "Visible page text"


@pytest.mark.asyncio
async def test_scrape_page_wrapper_uses_runtime(monkeypatch):
    calls = {"count": 0}

    async def _fake_run_browser_runtime(**kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return {"success": True, "url": "https://example.com", "title": "Example"}
        return {"success": True, "extracted_text": "Hello world"}

    monkeypatch.setattr("core.capabilities.browser.run_browser_runtime", _fake_run_browser_runtime)

    result = await browser_scraper.scrape_page("https://example.com")

    assert result["success"] is True
    assert result["data"]["url"] == "https://example.com"
    assert result["data"]["text"] == "Hello world"


@pytest.mark.asyncio
async def test_scrape_links_wrapper_uses_runtime(monkeypatch):
    calls = {"count": 0}

    async def _fake_run_browser_runtime(**kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return {"success": True, "url": "https://example.com", "title": "Example"}
        return {"success": True, "links": [{"href": "https://example.com/a", "text": "A"}]}

    monkeypatch.setattr("core.capabilities.browser.run_browser_runtime", _fake_run_browser_runtime)

    result = await browser_scraper.scrape_links("https://example.com", pattern="/a")

    assert result["success"] is True
    assert result["links"][0]["href"].endswith("/a")
