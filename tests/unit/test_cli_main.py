"""Unit tests for top-level CLI parsing UX."""

import types

from cli import main as cli_main
from cli import onboard as cli_onboard


def test_main_suggests_closest_command_for_typo(capsys):
    code = cli_main.main(["gatewat", "logs"])
    captured = capsys.readouterr()
    assert code == 2
    assert "Şunu mu demek istediniz: 'gateway'" in captured.err


def test_main_version_command(capsys):
    code = cli_main.main(["version"])
    captured = capsys.readouterr()
    assert code == 0
    assert "Elyan CLI v18.0.0" in captured.out


def test_doctor_fix_alias_triggers_fix(monkeypatch):
    called = {}
    fake_doctor = types.SimpleNamespace(run_doctor=lambda fix=False: called.setdefault("fix", fix))
    monkeypatch.setattr("cli.commands.doctor", fake_doctor, raising=False)

    code = cli_main.main(["doctor", "fix"])
    assert code == 0
    assert called.get("fix") is True


def test_main_without_args_prints_cli_home(monkeypatch, capsys):
    monkeypatch.setattr("cli.onboard.ensure_first_run_setup", lambda command="", non_interactive=False: True)
    monkeypatch.setattr(cli_main, "_read_cli_config", lambda: {
        "models": {
            "default": {"provider": "openai", "model": "gpt-4o"},
            "roles": {"router": {"provider": "ollama", "model": "llama3.1:8b"}},
        },
        "channels": [{"type": "telegram", "enabled": True}],
    })
    monkeypatch.setattr(cli_main, "_gateway_running", lambda: (False, None))

    code = cli_main.main([])
    captured = capsys.readouterr()

    assert code == 0
    assert "Elyan CLI hazir." in captured.out
    assert "elyan gateway start --daemon" in captured.out
    assert "Router modeli: ollama / llama3.1:8b" in captured.out


def test_build_role_map_prefers_local_router_when_ollama_present(monkeypatch):
    monkeypatch.setattr(cli_onboard.elyan_config, "get", lambda key, default=None: "llama3.1:8b" if key == "models.local.model" else default)
    role_map = cli_onboard._build_role_map("openai", "gpt-4o", has_ollama=True)

    assert role_map["router"] == {"provider": "ollama", "model": "llama3.1:8b"}
    assert role_map["inference"] == {"provider": "ollama", "model": "llama3.1:8b"}
    assert role_map["critic"] == {"provider": "openai", "model": "gpt-4o"}
    assert role_map["research_worker"] == {"provider": "openai", "model": "gpt-4o"}


def test_main_routes_unknown_non_command_to_natural_language(monkeypatch):
    captured = {}
    monkeypatch.setattr("cli.onboard.ensure_first_run_setup", lambda command="", non_interactive=False: True)
    def fake_run(prompt):
        captured["prompt"] = prompt
        return 0
    monkeypatch.setattr(cli_main, "_run_natural_language", fake_run)

    code = cli_main.main(["kopekler", "hakkinda", "arastirma", "yap"])

    assert code == 0
    assert captured["prompt"] == "kopekler hakkinda arastirma yap"


def test_main_chat_command_starts_chat_session(monkeypatch):
    captured = {}

    monkeypatch.setattr("cli.onboard.ensure_first_run_setup", lambda command="", non_interactive=False: True)

    def fake_chat(prompt=""):
        captured["prompt"] = prompt
        return 0

    monkeypatch.setattr(cli_main, "_run_chat_session", fake_chat)
    code = cli_main.main(["chat", "merhaba", "elyan"])

    assert code == 0
    assert captured["prompt"] == "merhaba elyan"


def test_main_rejects_desktop_command_and_suggests_dashboard(monkeypatch, capsys):
    monkeypatch.setattr("cli.onboard.ensure_first_run_setup", lambda command="", non_interactive=False: True)

    code = cli_main.main(["desktop"])
    captured = capsys.readouterr()

    assert code == 2
    assert "Şunu mu demek istediniz: 'dashboard'" in captured.err
