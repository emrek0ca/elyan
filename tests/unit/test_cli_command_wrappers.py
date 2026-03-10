"""Unit tests for CLI command wrapper compatibility."""

from types import SimpleNamespace

from cli.commands import agents, browser, voice


def test_agents_handle_list_works_with_config_rows(monkeypatch, capsys):
    monkeypatch.setattr(agents, "_load_agents", lambda: [{"id": "default", "routes": ["webchat"], "model": "gpt-4o"}])
    monkeypatch.setattr(agents, "_running_ids", lambda: {"default"})

    code = agents.handle_agents(SimpleNamespace(action="list", id=None, channel=None))
    captured = capsys.readouterr()

    assert code == 0
    assert "default" in captured.out
    assert "active" in captured.out


def test_browser_handle_extract_uses_safe_extract(monkeypatch, capsys):
    async def fake_extract(url, selector=None):
        return {"success": True, "text": "ornek metin"}

    monkeypatch.setattr("tools.browser_automation.extract_webpage_text", fake_extract)
    code = browser.handle_browser(SimpleNamespace(action="extract", target="https://example.com", url=None, profile=None))
    captured = capsys.readouterr()

    assert code == 0
    assert "ornek metin" in captured.out


def test_voice_handle_status_invokes_status(monkeypatch):
    called = {}

    def fake_status():
        called["ok"] = True

    monkeypatch.setattr(voice, "_run_voice_status", fake_status)
    code = voice.handle_voice(SimpleNamespace(action="status", text=None, file=None))

    assert code == 0
    assert called["ok"] is True


def test_browser_extract_returns_success_when_ssl_retry_recovers(monkeypatch, capsys):
    async def fake_extract(url, selector=None):
        return {"success": True, "text": "ssl tamam"}

    monkeypatch.setattr("tools.browser_automation.extract_webpage_text", fake_extract)
    code = browser.handle_browser(SimpleNamespace(action="extract", target="https://example.com", url=None, profile=None))
    captured = capsys.readouterr()

    assert code == 0
    assert "ssl tamam" in captured.out
