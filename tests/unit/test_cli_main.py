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


def test_main_routes_integrations_command(monkeypatch):
    captured = {}
    monkeypatch.setattr("cli.onboard.ensure_first_run_setup", lambda command="", non_interactive=False: True)

    def fake_handle(args):
        captured["action"] = getattr(args, "action", None)
        captured["app_name"] = getattr(args, "app_name", None)
        captured["provider"] = getattr(args, "provider", None)
        captured["account_alias"] = getattr(args, "account_alias", None)
        return 0

    monkeypatch.setattr("cli.commands.integrations.handle_integrations", fake_handle, raising=False)

    code = cli_main.main(["integrations", "connect", "--app-name", "Gmail", "--provider", "google", "--account-alias", "work"])

    assert code == 0
    assert captured["action"] == "connect"
    assert captured["app_name"] == "Gmail"
    assert captured["provider"] == "google"
    assert captured["account_alias"] == "work"


def test_main_routes_bootstrap_command(monkeypatch):
    captured = {}
    monkeypatch.setattr("cli.onboard.ensure_first_run_setup", lambda command="", non_interactive=False: True)

    def fake_handle(args):
        captured["command"] = getattr(args, "command", None)
        captured["action"] = getattr(args, "action", None)
        captured["force"] = getattr(args, "force", None)
        return 0

    monkeypatch.setattr("cli.commands.bootstrap.handle_bootstrap", fake_handle, raising=False)

    code = cli_main.main(["bootstrap", "status"])

    assert code == 0
    assert captured["command"] == "bootstrap"
    assert captured["action"] == "status"


def test_main_routes_project_pack_commands(monkeypatch):
    monkeypatch.setattr("cli.onboard.ensure_first_run_setup", lambda command="", non_interactive=False: True)

    routes = []

    def fake_run(args):
        routes.append((getattr(args, "command", None), getattr(args, "action", None)))
        return 0

    monkeypatch.setattr("cli.commands.quivr.run", fake_run, raising=False)
    monkeypatch.setattr("cli.commands.cloudflare_agents.run", fake_run, raising=False)
    monkeypatch.setattr("cli.commands.opengauss.run", fake_run, raising=False)

    assert cli_main.main(["quivr", "status"]) == 0
    assert cli_main.main(["cloudflare-agents", "status"]) == 0
    assert cli_main.main(["opengauss", "status"]) == 0

    assert routes == [
        ("quivr", "status"),
        ("cloudflare-agents", "status"),
        ("opengauss", "status"),
    ]


def test_main_routes_packs_command(monkeypatch):
    captured = {}
    monkeypatch.setattr("cli.onboard.ensure_first_run_setup", lambda command="", non_interactive=False: True)

    def fake_run(args):
        captured["command"] = getattr(args, "command", None)
        captured["action"] = getattr(args, "action", None)
        captured["pack"] = getattr(args, "pack", None)
        return 0

    monkeypatch.setattr("cli.commands.packs.run", fake_run, raising=False)

    code = cli_main.main(["packs", "status", "quivr"])

    assert code == 0
    assert captured["command"] == "packs"
    assert captured["action"] == "status"
    assert captured["pack"] == "quivr"


def test_main_routes_skills_edit_command(monkeypatch):
    captured = {}
    monkeypatch.setattr("cli.onboard.ensure_first_run_setup", lambda command="", non_interactive=False: True)

    def fake_handle(args):
        captured["command"] = getattr(args, "command", None)
        captured["action"] = getattr(args, "action", None)
        captured["name"] = getattr(args, "name", None)
        captured["set_values"] = list(getattr(args, "set_values", []) or [])
        captured["replace"] = getattr(args, "replace", False)
        return 0

    monkeypatch.setattr("cli.commands.skills.handle_skills", fake_handle, raising=False)

    code = cli_main.main(["skills", "edit", "files", "--set", "description=Yeni skill", "--set", "approval_level=2"])

    assert code == 0
    assert captured["command"] == "skills"
    assert captured["action"] == "edit"
    assert captured["name"] == "files"
    assert "description=Yeni skill" in captured["set_values"]
    assert "approval_level=2" in captured["set_values"]
