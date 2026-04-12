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
    assert "Elyan" in captured.out
    assert "Local operator runtime" in captured.out
    assert "elyan launch" in captured.out
    assert "elyan gateway start --daemon" in captured.out
    assert "Router model: ollama / llama3.1:8b" in captured.out
    assert "elyan desktop" in captured.out


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


def test_setup_command_forwards_skip_deps_and_no_dashboard(monkeypatch):
    captured = {}

    def fake_start_onboarding(**kwargs):
        captured.update(kwargs)
        return True

    monkeypatch.setattr("cli.onboard.start_onboarding", fake_start_onboarding)

    code = cli_main.main(["setup", "--skip-deps", "--no-dashboard"])

    assert code == 0
    assert captured["skip_dependencies"] is True
    assert captured["open_dashboard"] is False


def test_main_routes_launch_command(monkeypatch):
    captured = {}
    monkeypatch.setattr("cli.onboard.ensure_first_run_setup", lambda command="", non_interactive=False: True)

    def fake_run(args):
        captured["port"] = getattr(args, "port", None)
        captured["no_browser"] = getattr(args, "no_browser", False)
        captured["ops"] = getattr(args, "ops", False)
        return 0

    monkeypatch.setattr("cli.commands.launch.run", fake_run, raising=False)

    code = cli_main.main(["launch", "--port", "18888", "--no-browser", "--ops"])

    assert code == 0
    assert captured["port"] == 18888
    assert captured["no_browser"] is True
    assert captured["ops"] is True


def test_main_routes_desktop_command(monkeypatch):
    monkeypatch.setattr("cli.onboard.ensure_first_run_setup", lambda command="", non_interactive=False: True)
    calls = {}

    monkeypatch.setattr(
        "cli.commands.desktop.open_desktop",
        lambda detached=False: (calls.setdefault("detached", detached), 0)[1],
        raising=False,
    )

    code = cli_main.main(["desktop", "--detached"])

    assert code == 0
    assert calls["detached"] is True


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


def test_main_routes_models_switch_command(monkeypatch):
    captured = {}
    monkeypatch.setattr("cli.onboard.ensure_first_run_setup", lambda command="", non_interactive=False: True)

    def fake_run(args):
        captured["subcommand"] = getattr(args, "subcommand", None)
        captured["name"] = getattr(args, "name", None)

    monkeypatch.setattr("cli.commands.models.run", fake_run, raising=False)

    code = cli_main.main(["models", "switch", "openai/gpt-4o"])

    assert code == 0
    assert captured["subcommand"] == "switch"
    assert captured["name"] == "openai/gpt-4o"


def test_main_routes_model_alias_defaults_to_switch(monkeypatch):
    captured = {}
    monkeypatch.setattr("cli.onboard.ensure_first_run_setup", lambda command="", non_interactive=False: True)

    def fake_run(args):
        captured["subcommand"] = getattr(args, "subcommand", None)
        captured["name"] = getattr(args, "name", None)

    monkeypatch.setattr("cli.commands.models.run", fake_run, raising=False)

    code = cli_main.main(["model", "openai/gpt-4o"])

    assert code == 0
    assert captured["subcommand"] == "switch"
    assert captured["name"] == "openai/gpt-4o"


def test_main_routes_platforms_command(monkeypatch):
    captured = {}
    monkeypatch.setattr("cli.onboard.ensure_first_run_setup", lambda command="", non_interactive=False: True)

    def fake_run(args):
        captured["json"] = getattr(args, "json", False)
        return 0

    monkeypatch.setattr("cli.commands.platforms.run", fake_run, raising=False)

    code = cli_main.main(["platforms", "--json"])

    assert code == 0
    assert captured["json"] is True


def test_main_routes_memory_recall_command(monkeypatch):
    captured = {}
    monkeypatch.setattr("cli.onboard.ensure_first_run_setup", lambda command="", non_interactive=False: True)

    def fake_run(args):
        captured["subcommand"] = getattr(args, "subcommand", None)
        captured["query"] = getattr(args, "query", None)
        captured["limit"] = getattr(args, "limit", None)

    monkeypatch.setattr("cli.commands.memory.run", fake_run, raising=False)

    code = cli_main.main(["memory", "recall", "iyzico", "--limit", "3"])

    assert code == 0
    assert captured["subcommand"] == "recall"
    assert captured["query"] == "iyzico"
    assert captured["limit"] == 3


def test_main_routes_memory_drafts_command(monkeypatch):
    captured = {}
    monkeypatch.setattr("cli.onboard.ensure_first_run_setup", lambda command="", non_interactive=False: True)

    def fake_run(args):
        captured["subcommand"] = getattr(args, "subcommand", None)
        captured["draft_type"] = getattr(args, "draft_type", None)
        captured["limit"] = getattr(args, "limit", None)

    monkeypatch.setattr("cli.commands.memory.run", fake_run, raising=False)

    code = cli_main.main(["memory", "drafts", "--type", "skills", "--limit", "4"])

    assert code == 0
    assert captured["subcommand"] == "drafts"
    assert captured["draft_type"] == "skills"


def test_main_routes_schedule_command(monkeypatch):
    captured = {}
    monkeypatch.setattr("cli.onboard.ensure_first_run_setup", lambda command="", non_interactive=False: True)

    def fake_run(args):
        captured["text"] = getattr(args, "text", None)
        captured["report_channel"] = getattr(args, "report_channel", None)
        return 0

    monkeypatch.setattr("cli.commands.schedule.run", fake_run, raising=False)

    code = cli_main.main(["schedule", "Her", "gün", "09:00", "günlük", "özet", "gönder", "--report-channel", "telegram"])

    assert code == 0
    assert captured["text"] == ["Her", "gün", "09:00", "günlük", "özet", "gönder"]
    assert captured["report_channel"] == "telegram"


def test_main_routes_goals_command(monkeypatch):
    captured = {}
    monkeypatch.setattr("cli.onboard.ensure_first_run_setup", lambda command="", non_interactive=False: True)

    def fake_run(args):
        captured["action"] = getattr(args, "action", None)
        captured["text"] = getattr(args, "text", None)
        return 0

    monkeypatch.setattr("cli.commands.goals.run", fake_run, raising=False)

    code = cli_main.main(["goals", "analyze", "ERP'den", "satışları", "çek", "ve", "mail", "at"])

    assert code == 0
    assert captured["action"] == "analyze"
    assert captured["text"] == ["ERP'den", "satışları", "çek", "ve", "mail", "at"]


def test_main_routes_skills_promote_draft_command(monkeypatch):
    captured = {}
    monkeypatch.setattr("cli.onboard.ensure_first_run_setup", lambda command="", non_interactive=False: True)

    def fake_handle(args):
        captured["action"] = getattr(args, "action", None)
        captured["name"] = getattr(args, "name", None)
        captured["skill_name"] = getattr(args, "skill_name", None)
        captured["description"] = getattr(args, "description", None)

    monkeypatch.setattr("cli.commands.skills.handle_skills", fake_handle, raising=False)

    code = cli_main.main(["skills", "promote-draft", "skilldraft_123", "--skill-name", "daily_digest"])

    assert code == 0
    assert captured["action"] == "promote-draft"
    assert captured["name"] == "skilldraft_123"
    assert captured["skill_name"] == "daily_digest"


def test_main_routes_digest_command(monkeypatch):
    captured = {}
    monkeypatch.setattr("cli.onboard.ensure_first_run_setup", lambda command="", non_interactive=False: True)

    def fake_run(args):
        captured["subcommand"] = getattr(args, "subcommand", None)
        captured["weather"] = getattr(args, "weather", None)
        return 0

    monkeypatch.setattr("cli.commands.digest.run", fake_run, raising=False)

    code = cli_main.main(["digest", "show", "--no-weather"])

    assert code == 0
    assert captured["subcommand"] == "show"
    assert captured["weather"] is False


def test_main_routes_research_with_local_paths(monkeypatch):
    captured = {}
    monkeypatch.setattr("cli.onboard.ensure_first_run_setup", lambda command="", non_interactive=False: True)

    def fake_search(query, depth="standard", format="text", session=None, paths=None, include_web=True):
        captured["query"] = query
        captured["depth"] = depth
        captured["paths"] = list(paths or [])
        captured["include_web"] = include_web

    monkeypatch.setattr("cli.commands.research.research_search", fake_search, raising=False)

    code = cli_main.main(["research", "search", "yerel", "belgeleri", "tara", "--path", "/tmp/doc.txt", "--local-only"])

    assert code == 0
    assert captured["query"] == "yerel belgeleri tara"
    assert captured["paths"] == ["/tmp/doc.txt"]
    assert captured["include_web"] is False


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
