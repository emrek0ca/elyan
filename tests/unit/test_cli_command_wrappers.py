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


def test_agents_handle_modules_prints_catalog(monkeypatch, capsys):
    monkeypatch.setattr(
        agents,
        "list_agent_modules",
        lambda: [
            {
                "module_id": "context_recovery",
                "default_interval_seconds": 86400,
                "category": "productivity",
                "name": "Context Recovery",
            }
        ],
    )
    code = agents.handle_agents(SimpleNamespace(action="modules", id=None, channel=None))
    captured = capsys.readouterr()

    assert code == 0
    assert "context_recovery" in captured.out
    assert "Context Recovery" in captured.out


def test_agents_handle_module_run_outputs_json(monkeypatch, capsys):
    async def _fake_run(module_id, payload):
        assert module_id == "context_recovery"
        assert payload.get("workspace") == "/tmp/ws"
        assert payload.get("focus") == "daily"
        return {"success": True, "module_id": module_id, "status": "ok"}

    monkeypatch.setattr(agents, "run_agent_module", _fake_run)
    code = agents.handle_agents(
        SimpleNamespace(
            action="module-run",
            id="context_recovery",
            channel=None,
            workspace="/tmp/ws",
            params='{"focus":"daily"}',
            interval=None,
        )
    )
    captured = capsys.readouterr()
    assert code == 0
    assert '"module_id": "context_recovery"' in captured.out


def test_agents_handle_module_enable_registers_automation(monkeypatch, capsys):
    called = {}

    def _fake_register_module(module_id, *, interval_seconds=None, channel=None, params=None, **kwargs):
        called["module_id"] = module_id
        called["interval_seconds"] = interval_seconds
        called["channel"] = channel
        called["params"] = dict(params or {})
        called["kwargs"] = dict(kwargs or {})
        return "auto123"

    monkeypatch.setattr(agents.automation_registry, "register_module", _fake_register_module)
    code = agents.handle_agents(
        SimpleNamespace(
            action="module-enable",
            id="website_change_intelligence",
            channel="automation",
            workspace="/tmp/ws",
            params='{"tracked_urls":["https://example.com"]}',
            interval=900,
            timeout=120,
            retries=2,
            backoff=10,
            circuit_threshold=3,
            circuit_cooldown=600,
        )
    )
    captured = capsys.readouterr()
    assert code == 0
    assert called["module_id"] == "website_change_intelligence"
    assert called["interval_seconds"] == 900
    assert called["params"]["workspace"] == "/tmp/ws"
    assert called["kwargs"]["timeout_seconds"] == 120
    assert called["kwargs"]["max_retries"] == 2
    assert called["kwargs"]["retry_backoff_seconds"] == 10
    assert called["kwargs"]["circuit_breaker_threshold"] == 3
    assert called["kwargs"]["circuit_breaker_cooldown_seconds"] == 600
    assert "auto123" in captured.out


def test_agents_handle_module_tasks_json(monkeypatch, capsys):
    monkeypatch.setattr(
        agents.automation_registry,
        "list_module_tasks",
        lambda include_inactive=False, limit=200: [
            {"task_id": "t1", "module_id": "context_recovery", "status": "active", "health": "healthy"}
        ],
    )
    code = agents.handle_agents(
        SimpleNamespace(action="module-tasks", id=None, include_inactive=True, json=True)
    )
    captured = capsys.readouterr()

    assert code == 0
    assert '"module_id": "context_recovery"' in captured.out


def test_agents_handle_module_health_json(monkeypatch, capsys):
    monkeypatch.setattr(
        agents.automation_registry,
        "get_module_health",
        lambda limit=50: {"summary": {"active_modules": 1, "healthy": 1}, "modules": []},
    )
    code = agents.handle_agents(SimpleNamespace(action="module-health", id=None, json=True))
    captured = capsys.readouterr()

    assert code == 0
    assert '"active_modules": 1' in captured.out


def test_agents_handle_module_run_now(monkeypatch, capsys):
    async def _fake_run_task_now(task_id, agent=None):
        _ = agent
        return {"success": True, "task_id": task_id, "status": "ok"}

    monkeypatch.setattr(agents.automation_registry, "run_task_now", _fake_run_task_now)
    code = agents.handle_agents(SimpleNamespace(action="module-run-now", id="task123"))
    captured = capsys.readouterr()

    assert code == 0
    assert '"task_id": "task123"' in captured.out


def test_agents_handle_module_update(monkeypatch, capsys):
    called = {}

    def _fake_update(task_id, **kwargs):
        called["task_id"] = task_id
        called["kwargs"] = dict(kwargs or {})
        return {"id": task_id, "module_id": "context_recovery", "interval_seconds": 1200}

    monkeypatch.setattr(agents.automation_registry, "update_module_task", _fake_update)
    code = agents.handle_agents(
        SimpleNamespace(
            action="module-update",
            id="task321",
            interval=1200,
            timeout=80,
            retries=3,
            backoff=9,
            circuit_threshold=4,
            circuit_cooldown=300,
            workspace="/tmp/ws",
            params='{"focus":"daily"}',
            channel="automation",
            status="paused",
        )
    )
    captured = capsys.readouterr()

    assert code == 0
    assert called["task_id"] == "task321"
    assert called["kwargs"]["interval_seconds"] == 1200
    assert called["kwargs"]["timeout_seconds"] == 80
    assert called["kwargs"]["max_retries"] == 3
    assert called["kwargs"]["status"] == "paused"
    assert '"module_id": "context_recovery"' in captured.out


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
