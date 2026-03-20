from __future__ import annotations

from types import SimpleNamespace

from tools.browser import manager as browser_manager


def test_browser_manager_auto_installs_playwright_when_missing(monkeypatch):
    installed = {"value": False}
    calls = {}

    def fake_refresh():
        return installed["value"]

    def fake_get_dependency_runtime():
        class _Runtime:
            def ensure_module(self, *args, **kwargs):
                calls["args"] = args
                calls["kwargs"] = kwargs
                installed["value"] = True
                return SimpleNamespace(status="installed", reason="installed")

        return _Runtime()

    monkeypatch.setattr(browser_manager, "_refresh_playwright_import", fake_refresh)
    monkeypatch.setattr(browser_manager, "get_dependency_runtime", fake_get_dependency_runtime)

    assert browser_manager._ensure_playwright_runtime() is True
    assert calls["kwargs"]["install_spec"] == "playwright"
    assert calls["kwargs"]["post_install"] == ["playwright install chromium"]
    assert calls["kwargs"]["skill_name"] == "browser"
    assert installed["value"] is True
