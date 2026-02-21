"""Compatibility tests for CLI command entrypoints."""

from cli.commands import health, status


def test_health_has_run_health_wrapper(monkeypatch):
    called = {"ok": False}

    def _fake_run(args):
        _ = args
        called["ok"] = True

    monkeypatch.setattr(health, "run", _fake_run)
    health.run_health()
    assert called["ok"] is True


def test_status_has_run_status_wrapper(monkeypatch):
    called = {"ok": False}

    def _fake_run(args):
        _ = args
        called["ok"] = True

    monkeypatch.setattr(status, "run", _fake_run)
    status.run_status()
    assert called["ok"] is True


def test_core_domain_package_importable():
    from core.domain import AppConfig, AgentConfig  # noqa: F401


def test_health_provider_state_uses_keychain(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setattr(health.keychain, "is_available", lambda: True)
    monkeypatch.setattr(health.keychain, "get_key", lambda key: "sk-test" if key == "openai_api_key" else "")

    status = health._provider_state("OPENAI_API_KEY", "openai_api_key")
    assert status == "YAPILANDIRILDI (KEYCHAIN)"
