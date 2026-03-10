"""Unit tests for browser automation helpers."""

import pytest
import httpx

from tools.browser_automation import SimpleBrowser


@pytest.mark.asyncio
async def test_simple_browser_retries_without_tls_verification(monkeypatch):
    browser = SimpleBrowser()
    calls = {"n": 0}

    async def fake_get(url):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed", request=httpx.Request("GET", url))

        class _Response:
            url = "https://example.com"
            status_code = 200
            text = "<html><title>Example</title><body>ok</body></html>"

            def raise_for_status(self):
                return None

        return _Response()

    monkeypatch.setattr(browser.client, "get", fake_get)

    rebuilt = {"done": False}

    def fake_build_client(*, verify):
        rebuilt["done"] = not verify

        class _Client:
            async def get(self, url):
                return await fake_get(url)

            async def aclose(self):
                return None

        return _Client()

    monkeypatch.setattr(browser, "_build_client", fake_build_client)
    result = await browser.goto("https://example.com")

    assert result["success"] is True
    assert result["tls_verify_bypassed"] is True
    assert rebuilt["done"] is True
