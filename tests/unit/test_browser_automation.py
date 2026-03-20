"""Unit tests for browser automation helpers."""

import pytest
import httpx
import sys
from types import SimpleNamespace

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


def test_browser_automation_lazy_installs_httpx(monkeypatch):
    from tools import browser_automation

    calls = {}

    class _FakeRuntime:
        def ensure_module(self, *args, **kwargs):
            calls["args"] = args
            calls["kwargs"] = kwargs
            return SimpleNamespace(status="installed", reason="installed")

    fake_httpx = SimpleNamespace(AsyncClient=lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr(browser_automation, "httpx", None)
    monkeypatch.setattr(browser_automation, "get_dependency_runtime", lambda: _FakeRuntime())
    monkeypatch.setitem(sys.modules, "httpx", fake_httpx)

    assert browser_automation._ensure_httpx() is fake_httpx
    assert calls["kwargs"]["install_spec"] == "httpx"
    assert calls["kwargs"]["skill_name"] == "browser"
