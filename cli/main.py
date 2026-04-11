#!/usr/bin/env python3
"""Elyan CLI ana giriş noktası."""
import argparse
import asyncio
import json
import os
import sys
from difflib import get_close_matches
from pathlib import Path

try:
    import typer
except ImportError:
    typer = None

from core.dependencies.autoinstall_hook import activate as _activate_autoinstall_hook

_activate_autoinstall_hook()

from core.version import APP_VERSION


TOP_LEVEL_COMMANDS = [
    "chat",
    "doctor",
    "health",
    "logs",
    "status",
    "cognitive",
    "routines",
    "config",
    "gateway",
    "channels",
    "skills",
    "integrations",
    "security",
    "models",
    "cron",
    "memory",
    "webhooks",
    "agents",
    "browser",
    "voice",
    "message",
    "service",
    "desktop",
    "dashboard",
    "dashboard-api",
    "launch",
    "autopilot",
    "lean",
    "packs",
    "quivr",
    "cloudflare-agents",
    "opengauss",
    "onboard",
    "setup",
    "install",
    "bootstrap",
    "update",
    "version",
    "completion",
    "subscription",
    "quota",
    "research",
    "screen",
    "code",
    "workflow",
    "ux",
    "approve",
    "runs",
]

COMMAND_SUGGESTION_OVERRIDES = {
    "desktop": "desktop",
    "cloudflare_agents": "cloudflare-agents",
}


SETUP_OPTIONAL_COMMANDS = {
    "onboard",
    "setup",
    "install",
    "bootstrap",
    "version",
    "completion",
    "doctor",
    "health",
    "status",
    "autopilot",
    "chat",
    "quivr",
    "packs",
    "cloudflare-agents",
    "opengauss",
}


def _bootstrap_project_path():
    """
    Prefer workspace source tree over stale site-packages copy when available.

    This keeps CLI behavior consistent during active development and local installs.
    """
    candidates: list[Path] = []
    env_project = os.environ.get("ELYAN_PROJECT_DIR", "").strip()
    if env_project:
        candidates.append(Path(env_project).expanduser())
    candidates.append(Path.cwd())

    for base in candidates:
        try:
            cli_main = base / "cli" / "main.py"
            has_core = (base / "core").exists()
            has_config = (base / "config").exists()
            if cli_main.exists() and has_core and has_config:
                base_str = str(base)
                if base_str not in sys.path:
                    sys.path.insert(0, base_str)
                return
        except Exception:
            continue


_bootstrap_project_path()


def _suggest_command(raw: str) -> str:
    override = COMMAND_SUGGESTION_OVERRIDES.get(raw.strip().lower())
    if override:
        return override
    matches = get_close_matches(raw, TOP_LEVEL_COMMANDS, n=1, cutoff=0.68)
    return matches[0] if matches else ""


def _read_cli_config() -> dict:
    config_file = Path.home() / ".elyan" / "elyan.json"
    if not config_file.exists():
        return {}
    try:
        return json.loads(config_file.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _gateway_running() -> tuple[bool, int | None]:
    pid_file = Path.home() / ".elyan" / "gateway.pid"
    if not pid_file.exists():
        return False, None
    try:
        gateway_pid = int(pid_file.read_text(encoding="utf-8").strip())
        os.kill(gateway_pid, 0)
        return True, gateway_pid
    except Exception:
        return False, None


def _print_cli_home() -> None:
    config = _read_cli_config()
    models = config.get("models", {}) if isinstance(config, dict) else {}
    default_model = models.get("default", {}) if isinstance(models, dict) else {}
    role_map = models.get("roles", {}) if isinstance(models, dict) else {}
    channels = config.get("channels", []) if isinstance(config, dict) else []
    active_channels = []
    if isinstance(channels, list):
        active_channels = [str(ch.get("type", "?")) for ch in channels if isinstance(ch, dict) and ch.get("enabled", False)]

    gateway_running, gateway_pid = _gateway_running()
    router_role = role_map.get("router", {}) if isinstance(role_map, dict) else {}

    print("Elyan")
    print("Local operator runtime")
    print("")
    print(f"Gateway: {'active' if gateway_running else 'inactive'}" + (f" (PID {gateway_pid})" if gateway_pid else ""))
    print(f"Default model: {default_model.get('provider', '?')} / {default_model.get('model', '?')}")
    if router_role:
        print(f"Router model: {router_role.get('provider', '?')} / {router_role.get('model', '?')}")
    if active_channels:
        print(f"Active channels: {', '.join(active_channels)}")

    print("")
    print("Quick start")
    print("  elyan desktop")
    print("  elyan launch")
    if not gateway_running:
        print("  elyan gateway start --daemon")
    print("  elyan status")
    print("  elyan bootstrap status")
    print("  elyan chat")
    print("  elyan doctor")
    print("")
    print("Core surfaces")
    print("  elyan agents")
    print("  elyan desktop")
    print("  elyan research \"topic\"")
    print("  elyan files ls")
    print("  elyan settings")


def _render_agent_response(response) -> int:
    text = str(getattr(response, "text", "") or "").strip()
    if text:
        print(text)

    attachments = list(getattr(response, "attachments", []) or [])
    if attachments:
        print("")
        print("Artifacts:")
        for item in attachments:
            name = str(getattr(item, "name", "") or "").strip()
            kind = str(getattr(item, "type", "") or "file").strip()
            path = str(getattr(item, "path", "") or "").strip()
            if not path:
                continue
            label = name or Path(path).name
            print(f"  - [{kind}] {label}: {path}")

    metadata = getattr(response, "metadata", {}) or {}
    away_task_id = str(metadata.get("away_task_id") or "").strip()
    if away_task_id:
        print("")
        print(f"Follow-up: elyan run status {away_task_id}")

    return 0 if str(getattr(response, "status", "success") or "success") != "failed" else 1


def _run_natural_language(prompt: str) -> int:
    cleaned = str(prompt or "").strip()
    if not cleaned:
        print("Empty request.")
        return 1

    from core.agent import Agent

    async def _invoke() -> int:
        agent = Agent()
        response = await agent.process_envelope(
            cleaned,
            channel="cli",
            metadata={"channel_type": "cli", "channel_id": "local", "entrypoint": "cli_natural_language"},
        )
        return _render_agent_response(response)

    return asyncio.run(_invoke())


def _run_chat_session(initial_prompt: str = "") -> int:
    from core.agent import Agent

    async def _chat() -> int:
        agent = Agent()
        await agent.initialize()
        print("Elyan chat hazir. Cikmak icin 'exit' veya 'quit' yaz.")
        first = str(initial_prompt or "").strip()
        if first:
            print("")
            print(f"> {first}")
            response = await agent.process_envelope(
                first,
                channel="cli",
                metadata={"channel_type": "cli", "channel_id": "local", "entrypoint": "cli_chat"},
            )
            _render_agent_response(response)

        while True:
            try:
                raw = input("\n> ").strip()
            except EOFError:
                print("")
                return 0
            except KeyboardInterrupt:
                print("\n")
                return 0

            if not raw:
                continue
            if raw.lower() in {"exit", "quit", "cik", "çik"}:
                return 0

            response = await agent.process_envelope(
                raw,
                channel="cli",
                metadata={"channel_type": "cli", "channel_id": "local", "entrypoint": "cli_chat"},
            )
            _render_agent_response(response)

    return asyncio.run(_chat())


def main(argv: list[str] | None = None):
    argv = list(sys.argv[1:] if argv is None else argv)

    # Backward-compat gateway aliases (legacy habit: `elyan restart`).
    if argv:
        first = str(argv[0]).strip().lower()
        if first in {"start", "stop", "restart"}:
            argv = ["gateway", *argv]
            # Legacy top-level behavior: keep shell responsive by default.
            if first in {"start", "restart"} and "--daemon" not in argv:
                argv.append("--daemon")

    parser = argparse.ArgumentParser(prog="elyan", description=f"Elyan CLI v{APP_VERSION}")
    sub = parser.add_subparsers(dest="command", help="Komut")

    # ── chat ────────────────────────────────────────────────────────────
    p = sub.add_parser("chat", help="Dogal dil ile interaktif Elyan oturumu")
    p.add_argument("prompt", nargs="*", help="Istersen ilk mesaji dogrudan verebilirsin")

    def _add_onboard_args(target):
        target.add_argument("--headless", action="store_true")
        target.add_argument("--channel", metavar="CHANNEL")
        target.add_argument("--install-daemon", action="store_true")
        target.add_argument("--force", action="store_true")
        target.add_argument("--skip-deps", action="store_true")
        target.add_argument("--no-dashboard", action="store_true")

    # ── doctor ──────────────────────────────────────────────────────────
    p = sub.add_parser("doctor", help="Sistem tanılaması")
    p.add_argument("action", nargs="?", choices=["fix"], help="Kisa kullanim: 'elyan doctor fix'")
    p.add_argument("--fix", action="store_true", help="Sorunları otomatik düzelt")
    p.add_argument("--deep", action="store_true")
    p.add_argument("--report", action="store_true")
    p.add_argument("--check", metavar="AREA")

    # ── health ──────────────────────────────────────────────────────────
    sub.add_parser("health", help="Hızlı sağlık özeti")

    # ── logs ────────────────────────────────────────────────────────────
    p = sub.add_parser("logs", help="Gateway loglarını göster")
    p.add_argument("--tail", type=int, default=50)
    p.add_argument("--level", default="all")
    p.add_argument("--filter", metavar="TERM")

    # ── status ──────────────────────────────────────────────────────────
    p = sub.add_parser("status", help="Genel durum")
    p.add_argument("--deep", action="store_true")
    p.add_argument("--json", action="store_true")

    # ── cognitive ───────────────────────────────────────────────────────
    p = sub.add_parser("cognitive", help="Bilişsel katman (Phase 4)")
    p.add_argument("subcommand", nargs="?",
                   choices=["status", "insights", "diagnostics", "mode", "schedule-sleep"])
    p.add_argument("task_id", nargs="?", help="Task ID (for insights)")
    p.add_argument("--set-mode", dest="set_mode", metavar="MODE",
                   help="Set execution mode (FOCUSED or DIFFUSE)")
    p.add_argument("--time", metavar="HH:MM", help="Schedule time for sleep consolidation")
    p.add_argument("--deep", action="store_true", help="Deep diagnostics")
    p.add_argument("--json", action="store_true")

    # ── routines ────────────────────────────────────────────────────────
    p = sub.add_parser("routines", help="Rutin otomasyon yönetimi")
    p.add_argument("action", nargs="?", choices=["list", "templates", "suggest", "add", "rm", "enable", "disable", "run", "history"])
    p.add_argument("id", nargs="?")
    p.add_argument("--json", action="store_true")
    p.add_argument("--text", metavar="TEXT")
    p.add_argument("--name", metavar="NAME")
    p.add_argument("--expression", metavar="CRON_EXPR")
    p.add_argument("--steps", metavar="STEP1;STEP2;STEP3")
    p.add_argument("--template-id", dest="template_id", metavar="TEMPLATE_ID")
    p.add_argument("--panels", metavar="URL1,URL2")
    p.add_argument("--report-channel", dest="report_channel", default="telegram")
    p.add_argument("--report-chat-id", dest="report_chat_id", default="")
    p.add_argument("--disabled", action="store_true")
    p.add_argument("--port", type=int)

    # ── config ──────────────────────────────────────────────────────────
    p = sub.add_parser("config", help="Yapılandırma yönetimi")
    p.add_argument("action", nargs="?",
                   choices=["show", "get", "set", "unset", "validate", "reset", "export", "import", "edit"])
    p.add_argument("key", nargs="?")
    p.add_argument("value", nargs="?")
    p.add_argument("--masked", action="store_true")
    p.add_argument("--output", metavar="FILE")
    p.add_argument("--file", metavar="FILE")

    # ── gateway ─────────────────────────────────────────────────────────
    p = sub.add_parser("gateway", help="Gateway yönetimi")
    p.add_argument("action", choices=["start", "stop", "status", "restart", "logs", "reload", "health"])
    p.add_argument("--daemon", action="store_true")
    p.add_argument("--port", type=int)
    p.add_argument("--json", dest="json", action="store_true")
    p.add_argument("--tail", type=int, default=50)
    p.add_argument("--level", default="info")
    p.add_argument("--filter", metavar="TERM")

    # ── channels ────────────────────────────────────────────────────────
    p = sub.add_parser("channels", help="Kanal yönetimi")
    p.add_argument("subcommand", nargs="?",
                   choices=["list", "status", "add", "remove", "enable", "disable", "test", "login", "logout", "info", "sync"])
    p.add_argument("channel_id", nargs="?", help="Kanal ID veya tip")
    p.add_argument("--json", dest="json", action="store_true")
    p.add_argument("--type", dest="channel_type", metavar="TYPE")

    # ── skills ──────────────────────────────────────────────────────────
    p = sub.add_parser("skills", help="Beceri yönetimi")
    p.add_argument("action", nargs="?",
                   choices=["list", "info", "install", "enable", "disable", "update", "edit", "remove", "search", "check"])
    p.add_argument("name", nargs="?")
    p.add_argument("--available", action="store_true")
    p.add_argument("--enabled", dest="enabled_only", action="store_true")
    p.add_argument("--all", dest="update_all", action="store_true")
    p.add_argument("--set", dest="set_values", action="append", default=[], help="key=value manifest alanı güncelle")
    p.add_argument("--file", dest="file", metavar="JSON_FILE", help="Manifest güncellemesi için JSON dosyası")
    p.add_argument("--replace", action="store_true", help="Manifesti tamamen verilen alanlarla değiştir")
    p.add_argument("--json", action="store_true")

    # ── integrations ───────────────────────────────────────────────────
    p = sub.add_parser("integrations", help="Entegrasyon hesapları ve trace yönetimi")
    p.add_argument("action", nargs="?",
                   choices=["accounts", "list", "status", "connect", "revoke", "traces", "summary"], default="accounts")
    p.add_argument("--provider", metavar="PROVIDER", default="")
    p.add_argument("--app-name", dest="app_name", metavar="APP_NAME", default="")
    p.add_argument("--account-alias", dest="account_alias", metavar="ALIAS", default="default")
    p.add_argument("--scopes", nargs="*", default=[])
    p.add_argument("--mode", default="auto")
    p.add_argument("--authorization-code", dest="authorization_code", metavar="CODE", default="")
    p.add_argument("--redirect-uri", dest="redirect_uri", metavar="URI", default="")
    p.add_argument("--display-name", dest="display_name", metavar="NAME", default="")
    p.add_argument("--email", metavar="EMAIL", default="")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--user-id", dest="user_id", metavar="USER_ID", default="")
    p.add_argument("--operation", default="")
    p.add_argument("--connector-name", dest="connector_name", default="")
    p.add_argument("--integration-type", dest="integration_type", default="")
    p.add_argument("--json", dest="json", action="store_true")

    # ── security ────────────────────────────────────────────────────────
    p = sub.add_parser("security", help="Güvenlik araçları")
    p.add_argument("subcommand", nargs="?",
                   choices=["audit", "status", "events", "sandbox", "keychain"])
    p.add_argument("--fix", action="store_true")
    p.add_argument("--clear-env", action="store_true", help="Migrate edilen secretları .env dosyasında boşalt")
    p.add_argument("--severity", choices=["low", "medium", "high", "critical"])
    p.add_argument("--last", metavar="PERIOD", default="24h")
    p.add_argument("--report", action="store_true")

    # ── models ──────────────────────────────────────────────────────────
    p = sub.add_parser("models", help="Model yönetimi")
    p.add_argument("subcommand", nargs="?",
                   choices=["list", "status", "test", "use", "switch", "add",
                             "set-default", "set-fallback", "cost", "ollama", "ollama-check"])
    p.add_argument("name", nargs="?", help="Model/sağlayıcı adı")
    p.add_argument("--provider", metavar="NAME")
    p.add_argument("--key", metavar="API_KEY")
    p.add_argument("--model", metavar="MODEL")
    p.add_argument("--period", default="30d")
    p.add_argument("action", nargs="?")  # ollama sub-action (list/pull/start/stop)

    # ── cron ────────────────────────────────────────────────────────────
    p = sub.add_parser("cron", help="Cron işleri")
    p.add_argument("subcommand", nargs="?",
                   choices=["list", "status", "add", "rm", "remove",
                             "enable", "disable", "run", "history", "next"])
    p.add_argument("job_id", nargs="?")
    p.add_argument("--expression", metavar="CRON_EXPR")
    p.add_argument("--prompt", metavar="PROMPT")
    p.add_argument("--channel", metavar="CHANNEL")
    p.add_argument("--user-id", dest="user_id", metavar="USER_ID")

    # ── memory ──────────────────────────────────────────────────────────
    p = sub.add_parser("memory", help="Bellek yönetimi")
    p.add_argument("subcommand", nargs="?",
                   choices=["status", "index", "search", "recall", "history", "export", "import", "clear", "stats"])
    p.add_argument("query", nargs="?")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--size", action="store_true")
    p.add_argument("--user", metavar="USER_ID")
    p.add_argument("--format", default="json")
    p.add_argument("--file", metavar="FILE")

    # ── webhooks ────────────────────────────────────────────────────────
    p = sub.add_parser("webhooks", help="Webhook yönetimi")
    p.add_argument("subcommand", nargs="?",
                   choices=["list", "add", "remove", "test", "logs", "gmail"])
    p.add_argument("name", nargs="?", help="Webhook adı")
    p.add_argument("url", nargs="?", help="Webhook URL")
    p.add_argument("--json", dest="json", action="store_true")
    p.add_argument("--account", metavar="EMAIL")

    # ── agents ──────────────────────────────────────────────────────────
    p = sub.add_parser("agents", help="Agent yönetimi")
    p.add_argument("action", nargs="?",
                   choices=[
                       "list",
                       "status",
                       "add",
                       "remove",
                       "start",
                       "stop",
                       "logs",
                       "info",
                       "create",
                       "modules",
                       "module-run",
                       "module-enable",
                       "module-tasks",
                       "module-health",
                       "module-run-now",
                       "module-pause",
                       "module-resume",
                       "module-remove",
                       "module-update",
                       "module-reconcile",
                   ])
    p.add_argument("id", nargs="?")
    p.add_argument("--channel", metavar="CHANNEL")
    p.add_argument("--interval", type=int, metavar="SECONDS")
    p.add_argument("--timeout", type=int, metavar="SECONDS")
    p.add_argument("--retries", type=int, metavar="COUNT")
    p.add_argument("--backoff", type=int, metavar="SECONDS")
    p.add_argument("--circuit-threshold", type=int, metavar="COUNT")
    p.add_argument("--circuit-cooldown", type=int, metavar="SECONDS")
    p.add_argument("--status", choices=["active", "paused", "disabled"])
    p.add_argument("--include-inactive", action="store_true")
    p.add_argument("--json", dest="json", action="store_true")
    p.add_argument("--workspace", metavar="PATH")
    p.add_argument("--params", metavar="JSON")

    # ── browser ─────────────────────────────────────────────────────────
    p = sub.add_parser("browser", help="Tarayıcı otomasyonu")
    p.add_argument("action", nargs="?",
                   choices=["snapshot", "screenshot", "navigate", "click", "type",
                             "extract", "scroll", "back", "forward", "refresh",
                             "close", "profiles", "list-profiles", "clear-profile"])
    p.add_argument("target", nargs="?", help="URL / element / metin")
    p.add_argument("--url", metavar="URL")
    p.add_argument("--profile", metavar="NAME")

    # ── voice ───────────────────────────────────────────────────────────
    p = sub.add_parser("voice", help="Ses komutları")
    p.add_argument("action", nargs="?",
                   choices=["start", "stop", "status", "test", "transcribe", "speak",
                             "set-wake-word", "set-tts", "set-stt", "listen"])
    p.add_argument("text", nargs="?")
    p.add_argument("--file", metavar="FILE")

    # ── message ─────────────────────────────────────────────────────────
    p = sub.add_parser("message", help="Mesaj gönder")
    p.add_argument("action", nargs="?", choices=["send", "poll", "broadcast"])
    p.add_argument("--text", metavar="TEXT")
    p.add_argument("--channel", metavar="CHANNEL")
    p.add_argument("--options", metavar="OPT1,OPT2")

    # ── service ─────────────────────────────────────────────────────────
    p = sub.add_parser("service", help="Sistem servisi")
    p.add_argument("action", choices=["install", "uninstall"])

    # ── desktop ─────────────────────────────────────────────────────────
    p = sub.add_parser("desktop", help="Desktop uygulamayı başlat")
    p.add_argument("--detached", action="store_true", help="Arka planda başlat")

    # ── dashboard ───────────────────────────────────────────────────────
    p = sub.add_parser("dashboard", help="Uyumluluk alias'ı: desktop aç")
    p.add_argument("--port", type=int)
    p.add_argument("--no-browser", action="store_true")
    p.add_argument("--ops", action="store_true", help="Admin ops console ac")

    # ── dashboard-api ───────────────────────────────────────────────────
    p = sub.add_parser("dashboard-api", help="Real-time Dashboard API (Phase 5-3)")
    p.add_argument("subcommand", nargs="?", choices=["start", "status", "metrics"], default="start")
    p.add_argument("metric_name", nargs="?")
    p.add_argument("--host", default="127.0.0.1", help="API sunucu adresi")
    p.add_argument("--port", type=int, default=5000, help="API port")
    p.add_argument("--debug", action="store_true", help="Debug modunda başlat")

    # ── launch ─────────────────────────────────────────────────────────
    p = sub.add_parser("launch", help="Gateway'i başlatıp desktop uygulamayı aç")
    p.add_argument("--port", type=int)
    p.add_argument("--no-browser", action="store_true")
    p.add_argument("--ops", action="store_true", help="Admin ops console ac")
    p.add_argument("-f", "--force", action="store_true", help="Eski süreçleri öldürüp temiz başlatır")

    # ── autopilot ───────────────────────────────────────────────────────
    p = sub.add_parser("autopilot", help="Otonom otomasyon motoru")
    p.add_argument("action", nargs="?", choices=["status", "start", "stop", "tick"], default="status")
    p.add_argument("--port", type=int)
    p.add_argument("--reason", default="manual_cli")

    # ── lean ───────────────────────────────────────────────────────────
    p = sub.add_parser("lean", help="Lean 4 proje ve formalizasyon orkestrasyonu")
    p.add_argument("action", nargs="?", choices=["status", "project", "prove", "draft", "autoprove", "formalize", "autoformalize", "swarm"], default="status")
    p.add_argument("text", nargs="*", help="Goal veya theorem metni")
    p.add_argument("--path", metavar="PATH", default="")
    p.add_argument("--name", metavar="NAME", default="")
    p.add_argument("--target", metavar="FILE", default="")
    p.add_argument("--backend", default="auto")
    p.add_argument("--project-action", choices=["status", "init", "create", "use", "clear", "list"], default="status")
    p.add_argument("--swarm-action", choices=["list", "attach", "cancel"], default="list")
    p.add_argument("--session-id", default="")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--no-verify", action="store_true")
    p.add_argument("--json", action="store_true")

    # ── packs ──────────────────────────────────────────────────────────
    p = sub.add_parser("packs", help="Project pack kataloğu ve dispatcher")
    p.add_argument("action", nargs="?", choices=["list", "status", "project", "scaffold", "workflow", "bundle", "ask", "query"], default="list")
    p.add_argument("pack", nargs="?", default="all")
    p.add_argument("text", nargs="*", help="Hedef, soru veya SQL metni")
    p.add_argument("--path", metavar="PATH", default="")
    p.add_argument("--name", metavar="NAME", default="")
    p.add_argument("--backend", default="auto")
    p.add_argument("--question", metavar="QUESTION", default="")
    p.add_argument("--retrieval-config", dest="retrieval_config", metavar="PATH", default="")
    p.add_argument("--file-path", dest="file_paths", action="append", default=[], help="Kaynak dosya yolu")
    p.add_argument("--include-samples", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--include-chat", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--include-workflows", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--include-mcp", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--image", metavar="IMAGE", default="opengauss/opengauss-server:latest")
    p.add_argument("--database", metavar="DB", default="appdb")
    p.add_argument("--user", metavar="USER", default="root")
    p.add_argument("--password", metavar="PASSWORD", default="OpenGauss@123")
    p.add_argument("--port", type=int, default=5432)
    p.add_argument("--force", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--use-llm", action="store_true")
    p.add_argument("--sql", metavar="SQL", default="")
    p.add_argument("--execute", action="store_true")
    p.add_argument("--allow-mutation", action="store_true")
    p.add_argument("--timeout", type=int, default=30)
    p.add_argument("--json", action="store_true")

    # ── quivr ───────────────────────────────────────────────────────────
    p = sub.add_parser("quivr", help="Quivr second-brain orkestrasyonu")
    p.add_argument("action", nargs="?", choices=["status", "project", "scaffold", "ask", "bundle", "workflow"], default="status")
    p.add_argument("text", nargs="*", help="Soru veya hedef metni")
    p.add_argument("--path", metavar="PATH", default="")
    p.add_argument("--name", metavar="NAME", default="")
    p.add_argument("--backend", default="auto")
    p.add_argument("--question", metavar="QUESTION", default="")
    p.add_argument("--retrieval-config", dest="retrieval_config", metavar="PATH", default="")
    p.add_argument("--file-path", dest="file_paths", action="append", default=[], help="Kaynak dosya yolu")
    p.add_argument("--include-samples", action="store_true")
    p.add_argument("--force", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--use-llm", action="store_true")
    p.add_argument("--json", action="store_true")

    # ── cloudflare-agents ───────────────────────────────────────────────
    p = sub.add_parser("cloudflare-agents", help="Cloudflare Agents proje orkestrasyonu")
    p.add_argument("action", nargs="?", choices=["status", "project", "scaffold", "workflow", "bundle"], default="status")
    p.add_argument("text", nargs="*", help="Hedef veya proje özeti")
    p.add_argument("--path", metavar="PATH", default="")
    p.add_argument("--name", metavar="NAME", default="")
    p.add_argument("--backend", default="auto")
    p.add_argument("--include-chat", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--include-workflows", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--include-mcp", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--force", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true")

    # ── opengauss ───────────────────────────────────────────────────────
    p = sub.add_parser("opengauss", help="OpenGauss database orkestrasyonu")
    p.add_argument("action", nargs="?", choices=["status", "project", "scaffold", "query", "workflow", "bundle"], default="status")
    p.add_argument("text", nargs="*", help="SQL veya hedef metni")
    p.add_argument("--path", metavar="PATH", default="")
    p.add_argument("--name", metavar="NAME", default="")
    p.add_argument("--image", metavar="IMAGE", default="opengauss/opengauss-server:latest")
    p.add_argument("--database", metavar="DB", default="appdb")
    p.add_argument("--user", metavar="USER", default="root")
    p.add_argument("--password", metavar="PASSWORD", default="OpenGauss@123")
    p.add_argument("--port", type=int, default=5432)
    p.add_argument("--backend", default="docker")
    p.add_argument("--force", action="store_true")
    p.add_argument("--include-samples", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--execute", action="store_true")
    p.add_argument("--allow-mutation", action="store_true")
    p.add_argument("--timeout", type=int, default=30)
    p.add_argument("--json", action="store_true")

    # ── onboard ─────────────────────────────────────────────────────────
    p = sub.add_parser("onboard", help="Kurulum sihirbazı")
    _add_onboard_args(p)

    # ── bootstrap ─────────────────────────────────────────────────────
    p = sub.add_parser("bootstrap", help="Kanonik kurulum ve geri yükleme akışı")
    p.add_argument("action", nargs="?", choices=["status", "install", "onboard", "repair", "restore", "snapshot"], default="status")
    p.add_argument("--headless", action="store_true")
    p.add_argument("--channel", metavar="CHANNEL")
    p.add_argument("--install-daemon", action="store_true")
    p.add_argument("--force", action="store_true")
    p.add_argument("--bundle", metavar="BUNDLE")
    p.add_argument("--output", metavar="OUTPUT")
    p.add_argument("--json", dest="json", action="store_true")

    # ── setup (onboard alias) ──────────────────────────────────────────
    p = sub.add_parser("setup", help="Kurulum sihirbazı (onboard alias)")
    _add_onboard_args(p)

    # ── install ────────────────────────────────────────────────────────
    sub.add_parser("install", help="Tek komutlu kurulum akışı (bootstrap install alias)")

    # ── update ──────────────────────────────────────────────────────────
    p = sub.add_parser("update", help="Güncelleme")
    p.add_argument("--check", action="store_true")
    p.add_argument("--beta", action="store_true")

    # ── version ─────────────────────────────────────────────────────────
    sub.add_parser("version", help="Sürüm bilgisi")

    # ── completion ───────────────────────────────────────────────────────
    p = sub.add_parser("completion", help="Shell auto-completion kur")
    p.add_argument("action", nargs="?", choices=["show", "install", "uninstall"], default="show")
    p.add_argument("--shell", choices=["zsh", "bash", "fish"])

    # ── subscription ─────────────────────────────────────────────────────
    p = sub.add_parser("subscription", help="Abonelik yönetimi")
    p.add_argument("subcommand", nargs="?", choices=["status", "set", "list-tiers"], default="status")
    p.add_argument("--user-id", dest="user_id", metavar="USER_ID")
    p.add_argument("--tier", choices=["free", "pro", "enterprise"])
    p.add_argument("--days", type=int, help="Geçerlilik süresi (gün)")

    # ── quota ────────────────────────────────────────────────────────────
    p = sub.add_parser("quota", help="Kota ve kullanım takibi")
    p.add_argument("subcommand", nargs="?", choices=["status", "check"], default="status")
    p.add_argument("--user", metavar="USER_ID")

    # ── research ─────────────────────────────────────────────────────────
    p = sub.add_parser("research", help="🔬 Araştırma Motoru — Multi-kaynak, atıf")
    p.add_argument("command", nargs="?", choices=["search", "session", "list"], default="search")
    p.add_argument("query", nargs="*", help="Araştırma sorgusu")
    p.add_argument("--depth", choices=["basic", "standard", "deep", "academic"], default="standard")
    p.add_argument("--format", choices=["text", "json", "md"], default="text")
    p.add_argument("--session", metavar="SESSION_ID", help="Oturum ID'si (kaydetmek için)")

    # ── screen ───────────────────────────────────────────────────────────
    p = sub.add_parser("screen", help="👁️ Gorsel Analiz — OCR, erisilebilirlik")
    p.add_argument("subcommand", nargs="?",
                   choices=["analyze", "ocr", "accessibility", "session", "list"],
                   default="analyze")
    p.add_argument("target", nargs="?", help="Goruntu dosyasi (yoksa ekran goruntusu alinir)")
    p.add_argument("--prompt", metavar="PROMPT")
    p.add_argument("--type", dest="analysis_type",
                   choices=["comprehensive", "ocr", "ui", "diff"],
                   default="comprehensive")
    p.add_argument("--app", metavar="APP")
    p.add_argument("--format", choices=["text", "json", "md"], default="text")
    p.add_argument("--session", metavar="SESSION_ID")

    # ── code ─────────────────────────────────────────────────────────────
    p = sub.add_parser("code", help="🔍 Kod Analizi — Tarama, calistirma, test uretimi")
    p.add_argument("subcommand", nargs="?",
                   choices=["analyze", "run", "scan", "test"],
                   default="analyze")
    p.add_argument("target", nargs="?", help="Dosya yolu veya '-' (stdin)")
    p.add_argument("--language", "-l", default="auto", metavar="LANG")
    p.add_argument("--timeout", type=int, default=10)
    p.add_argument("--severity",
                   choices=["low", "medium", "high", "critical"],
                   default=None)
    p.add_argument("--format", choices=["text", "json", "md"], default="text")

    # ── workflow ─────────────────────────────────────────────────────────
    p = sub.add_parser("workflow", help="⚙️ Adim Adim İş Akışı — Otomasyonu")
    p.add_argument("subcommand", nargs="?",
                   choices=["run", "create", "list", "status", "delete"],
                   default="list")
    p.add_argument("target", nargs="?", help="Workflow ID veya JSON spec dosyasi")
    p.add_argument("--name", metavar="NAME")
    p.add_argument("--format", choices=["text", "json", "md"], default="text")
    p.add_argument("--yes", action="store_true")

    # ── ux ───────────────────────────────────────────────────────────────
    p = sub.add_parser("ux", help="✨ Premium UX — Sohbet, öneriler, bağlam sürekliliği")
    p.add_argument("subcommand", nargs="?",
                   choices=["message", "session", "sessions", "clear"],
                   default="sessions")
    p.add_argument("target", nargs="?", help="Mesaj veya Session ID")
    p.add_argument("--session", metavar="ID", default="default")
    p.add_argument("--stream", action="store_true", help="Real-time streaming")
    p.add_argument("--format", choices=["text", "json", "md"], default="text")
    p.add_argument("--multimodal", nargs="*", help="Multimodal inputs (images, audio, docs)")
    p.add_argument("--yes", action="store_true")

    # ── approve ──────────────────────────────────────────────────────────
    p = sub.add_parser("approve", help="Approval System — Beklemeye alan onayları yönet")
    sub_approve = p.add_subparsers(dest="subcommand", help="Subcommand")

    p_pending = sub_approve.add_parser("pending", help="Beklemede olan onayları listele")
    p_pending.add_argument("--output", "-o", choices=["json", "table"], help="Output formatı")

    p_approve = sub_approve.add_parser("approve", help="Onay isteğini onayla")
    p_approve.add_argument("request_id", help="Approval request ID")

    p_deny = sub_approve.add_parser("deny", help="Onay isteğini reddet")
    p_deny.add_argument("request_id", help="Approval request ID")

    # ── runs ─────────────────────────────────────────────────────────────
    p = sub.add_parser("runs", help="Run Inspector — Çalıştırma geçmişini görüntüle")
    sub_runs = p.add_subparsers(dest="subcommand", help="Subcommand")

    p_list = sub_runs.add_parser("list", help="Çalıştırmaları listele")
    p_list.add_argument("--limit", "-l", type=int, default=20, help="Maksimum çalıştırma sayısı")
    p_list.add_argument("--status", "-s", help="Status'e göre filtrele")
    p_list.add_argument("--output", "-o", choices=["json", "table"], help="Output formatı")

    p_inspect = sub_runs.add_parser("inspect", help="Çalıştırma detaylarını görüntüle")
    p_inspect.add_argument("run_id", help="Run ID")

    p_cancel = sub_runs.add_parser("cancel", help="Çalıştırmayı iptal et")
    p_cancel.add_argument("run_id", help="Run ID")

    # ════════════════════════════════════════════════════════════════════
    if argv:
        first = str(argv[0]).strip()
        if first and not first.startswith("-") and first not in TOP_LEVEL_COMMANDS:
            suggestion = _suggest_command(first)
            if suggestion:
                parser.print_usage(sys.stderr)
                print(
                    f"elyan: error: bilinmeyen komut: '{first}'. Şunu mu demek istediniz: '{suggestion}'?",
                    file=sys.stderr,
                )
                return 2
            from cli.onboard import ensure_first_run_setup
            if not ensure_first_run_setup(command="prompt", non_interactive=not sys.stdin.isatty()):
                return 1
            return _run_natural_language(" ".join(argv))

    args = parser.parse_args(argv)

    if not args.command:
        from cli.onboard import ensure_first_run_setup
        if not ensure_first_run_setup(command="", non_interactive=not sys.stdin.isatty()):
            return 1
        _print_cli_home()
        return 0

    if args.command not in SETUP_OPTIONAL_COMMANDS:
        from cli.onboard import ensure_first_run_setup
        if not ensure_first_run_setup(command=args.command, non_interactive=not sys.stdin.isatty()):
            return 1

    # ── Routing ─────────────────────────────────────────────────────────
    if args.command == "doctor":
        from cli.commands import doctor
        doctor_fix = bool(getattr(args, "fix", False) or getattr(args, "action", "") == "fix")
        doctor.run_doctor(fix=doctor_fix)

    elif args.command == "health":
        from cli.commands import health
        runner = getattr(health, "run_health", None) or getattr(health, "run", None)
        if runner:
            try:
                runner(args)
            except TypeError:
                runner()
        else:
            print("Health komutu bulunamadı.")
            return 1

    elif args.command == "chat":
        return _run_chat_session(" ".join(getattr(args, "prompt", []) or []))

    elif args.command == "status":
        from cli.commands import status
        runner = getattr(status, "run_status", None) or getattr(status, "run", None)
        if runner:
            runner(args)
        else:
            print("Status komutu bulunamadı.")
            return 1

    elif args.command == "cognitive":
        from cli.commands import cognitive
        cognitive.run(args)

    elif args.command == "subscription":
        from cli.commands import subscription
        subscription.run(args)

    elif args.command == "quota":
        from cli.commands import quota
        quota.run(args)

    elif args.command == "research":
        from cli.commands import research
        research_cmd = getattr(args, "command", "search").strip().lower()
        query = " ".join(getattr(args, "query", []) or []).strip()

        if research_cmd == "search":
            if not query:
                print("Hata: Sorgu gerekli (örn: elyan research 'Python nedir')", file=sys.stderr)
                return 1
            research.research_search(
                query,
                depth=getattr(args, "depth", "standard"),
                format=getattr(args, "format", "text"),
                session=getattr(args, "session", None),
            )
        elif research_cmd == "session":
            if not query:
                print("Hata: Oturum ID gerekli (örn: elyan research session abc123)", file=sys.stderr)
                return 1
            research.research_session(query, format=getattr(args, "format", "text"))
        elif research_cmd == "list":
            research.research_list(format=getattr(args, "format", "text"))

    elif args.command == "screen":
        from cli.commands import screen
        screen_cmd = getattr(args, "subcommand", "analyze").strip().lower()
        target = getattr(args, "target", "") or ""

        if screen_cmd == "analyze":
            screen.screen_analyze(
                target,
                prompt=getattr(args, "prompt", None),
                analysis_type=getattr(args, "analysis_type", "comprehensive"),
                format=getattr(args, "format", "text"),
                session=getattr(args, "session", None),
            )
        elif screen_cmd == "ocr":
            screen.screen_ocr(target, format=getattr(args, "format", "text"))
        elif screen_cmd == "accessibility":
            screen.screen_accessibility(
                app=getattr(args, "app", None),
                format=getattr(args, "format", "text"),
            )
        elif screen_cmd == "session":
            if not target:
                print("Hata: Oturum ID gerekli", file=sys.stderr)
                return 1
            screen.screen_session(target, format=getattr(args, "format", "text"))
        elif screen_cmd == "list":
            screen.screen_list(format=getattr(args, "format", "text"))

    elif args.command == "code":
        from cli.commands import code
        code_cmd = getattr(args, "subcommand", "analyze").strip().lower()
        target = getattr(args, "target", "") or ""

        if not target and code_cmd != "help":
            print("Hata: TARGET gerekli (dosya yolu veya '-' stdin için)", file=sys.stderr)
            return 1

        if code_cmd == "analyze":
            code.code_analyze(
                target,
                language=getattr(args, "language", "auto"),
                format=getattr(args, "format", "text"),
            )
        elif code_cmd == "run":
            code.code_run(
                target,
                language=getattr(args, "language", "auto"),
                timeout=getattr(args, "timeout", 10),
            )
        elif code_cmd == "scan":
            code.code_scan(
                target,
                language=getattr(args, "language", "auto"),
                severity=getattr(args, "severity", None),
                format=getattr(args, "format", "text"),
            )
        elif code_cmd == "test":
            code.code_test(
                target,
                language=getattr(args, "language", "python"),
                format=getattr(args, "format", "text"),
            )

    elif args.command == "workflow":
        from cli.commands import workflow
        wf_cmd = getattr(args, "subcommand", "list").strip().lower()
        target = getattr(args, "target", "") or ""

        if wf_cmd == "run":
            if not target:
                print("Hata: Workflow ID veya dosya gerekli", file=sys.stderr)
                return 1
            workflow.workflow_run(
                target,
                format=getattr(args, "format", "text"),
            )
        elif wf_cmd == "create":
            if not target:
                print("Hata: Spec dosyasi gerekli", file=sys.stderr)
                return 1
            workflow.workflow_create(
                target,
                name=getattr(args, "name", None),
            )
        elif wf_cmd == "list":
            workflow.workflow_list(format=getattr(args, "format", "text"))
        elif wf_cmd == "status":
            if not target:
                print("Hata: Workflow ID gerekli", file=sys.stderr)
                return 1
            workflow.workflow_status(
                target,
                format=getattr(args, "format", "text"),
            )
        elif wf_cmd == "delete":
            if not target:
                print("Hata: Workflow ID gerekli", file=sys.stderr)
                return 1
            workflow.workflow_delete(
                target,
                yes=getattr(args, "yes", False),
            )

    elif args.command == "ux":
        from cli.commands import ux
        ux_cmd = getattr(args, "subcommand", "sessions").strip().lower()
        target = getattr(args, "target", "") or ""

        if ux_cmd == "message":
            if not target:
                print("Hata: Mesaj gerekli", file=sys.stderr)
                return 1
            ux.ux_message(
                target,
                session=getattr(args, "session", "default"),
                stream=getattr(args, "stream", False),
                format=getattr(args, "format", "text"),
                multimodal=getattr(args, "multimodal", None),
            )
        elif ux_cmd == "session":
            if not target:
                print("Hata: Session ID gerekli", file=sys.stderr)
                return 1
            ux.ux_session(
                target,
                format=getattr(args, "format", "text"),
            )
        elif ux_cmd == "sessions":
            ux.ux_sessions(format=getattr(args, "format", "text"))
        elif ux_cmd == "clear":
            if not target:
                print("Hata: Session ID gerekli", file=sys.stderr)
                return 1
            ux.ux_clear(
                target,
                yes=getattr(args, "yes", False),
            )

    elif args.command == "routines":
        from cli.commands import routines
        routines.run(args)

    elif args.command == "config":
        from cli.commands import config
        config.handle_config(args)

    elif args.command == "gateway":
        from cli.commands import gateway
        if args.action == "start":
            gateway.start_gateway(daemon=args.daemon, port=getattr(args, "port", None))
        elif args.action == "stop":
            gateway.stop_gateway(port=getattr(args, "port", None))
        elif args.action == "status":
            gateway.gateway_status(as_json=getattr(args, "json", False), port=getattr(args, "port", None))
        elif args.action == "restart":
            gateway.restart_gateway(daemon=args.daemon, port=getattr(args, "port", None))
        elif args.action == "health":
            gateway.gateway_health(as_json=getattr(args, "json", False), port=getattr(args, "port", None))
        elif args.action == "logs":
            gateway.gateway_logs(
                tail=getattr(args, "tail", 50),
                level=getattr(args, "level", "all"),
                filter_term=getattr(args, "filter", None),
            )
        elif args.action == "reload":
            gateway.gateway_reload(port=getattr(args, "port", None), as_json=getattr(args, "json", False))

    elif args.command == "channels":
        from cli.commands import channels
        channels.run(args)

    elif args.command == "skills":
        from cli.commands import skills
        skills.handle_skills(args)

    elif args.command == "integrations":
        from cli.commands import integrations
        result = integrations.handle_integrations(args)
        if isinstance(result, int):
            return result

    elif args.command == "security":
        from cli.commands import security
        # --last gibi period'u saate çevir
        hours = 24
        if hasattr(args, "last") and args.last:
            period = args.last
            if period.endswith("h"):
                hours = int(period[:-1])
            elif period.endswith("d"):
                hours = int(period[:-1]) * 24
        args.hours = hours
        security.run(args)

    elif args.command == "models":
        from cli.commands import models
        # "ollama-check" uyumu
        if getattr(args, "subcommand", None) == "ollama-check":
            args.subcommand = "ollama"
            args.action = "list"
        models.run(args)

    elif args.command == "cron":
        from cli.commands import cron
        cron.run(args)

    elif args.command == "memory":
        from cli.commands import memory
        memory.run(args)

    elif args.command == "webhooks":
        from cli.commands import webhooks
        webhooks.run(args)

    elif args.command == "agents":
        from cli.commands import agents
        result = agents.handle_agents(args)
        if isinstance(result, int):
            return result

    elif args.command == "browser":
        from cli.commands import browser
        result = browser.handle_browser(args)
        if isinstance(result, int):
            return result

    elif args.command == "voice":
        from cli.commands import voice
        result = voice.handle_voice(args)
        if isinstance(result, int):
            return result

    elif args.command == "message":
        from cli.commands import message
        result = message.handle_message(args)
        if isinstance(result, int):
            return result

    elif args.command == "service":
        from cli.daemon import daemon_manager
        if args.action == "install":
            if daemon_manager.install(): print("✅  Servis yüklendi.")
        else:
            if daemon_manager.uninstall(): print("🛑  Servis kaldırıldı.")

    elif args.command == "desktop":
        from cli.commands import desktop
        return int(desktop.open_desktop(detached=bool(getattr(args, "detached", False))))

    elif args.command == "dashboard":
        from cli.commands import dashboard
        return int(dashboard.open_dashboard(
            port=getattr(args, "port", None),
            no_browser=getattr(args, "no_browser", False),
            ops=getattr(args, "ops", False),
        ))

    elif args.command == "dashboard-api":
        from cli.commands import dashboard_api
        result = dashboard_api.handle_dashboard_api_command(args)
        if isinstance(result, dict):
            if result.get("success"):
                print(json.dumps(result, indent=2, ensure_ascii=False))
            else:
                print(f"Error: {result.get('error')}", file=sys.stderr)
                return 1
        elif isinstance(result, int):
            return result

    elif args.command == "launch":
        from cli.commands import launch
        result = launch.run(args)
        if isinstance(result, int):
            return result

    elif args.command == "autopilot":
        from cli.commands import autopilot
        result = autopilot.run_autopilot(args)
        if isinstance(result, int):
            return result

    elif args.command == "lean":
        from cli.commands import lean
        result = lean.run(args)
        if isinstance(result, int):
            return result

    elif args.command == "packs":
        from cli.commands import packs
        result = packs.run(args)
        if isinstance(result, int):
            return result

    elif args.command == "quivr":
        from cli.commands import quivr
        result = quivr.run(args)
        if isinstance(result, int):
            return result

    elif args.command == "cloudflare-agents":
        from cli.commands import cloudflare_agents
        result = cloudflare_agents.run(args)
        if isinstance(result, int):
            return result

    elif args.command == "opengauss":
        from cli.commands import opengauss
        result = opengauss.run(args)
        if isinstance(result, int):
            return result

    elif args.command in {"onboard", "setup"}:
        from cli.onboard import start_onboarding
        ok = start_onboarding(
            headless=getattr(args, "headless", False),
            channel=getattr(args, "channel", None),
            install_daemon=getattr(args, "install_daemon", False),
            skip_dependencies=getattr(args, "skip_deps", False),
            open_dashboard=not getattr(args, "no_dashboard", False),
            force=getattr(args, "force", False),
        )
        if not ok:
            return 1

    elif args.command == "bootstrap":
        from cli.commands import bootstrap
        result = bootstrap.handle_bootstrap(args)
        if isinstance(result, int):
            return result

    elif args.command == "install":
        from cli.commands import bootstrap
        install_args = argparse.Namespace(
            action="install",
            headless=False,
            channel=None,
            install_daemon=False,
            force=False,
            bundle=None,
            output=None,
            json=False,
        )
        result = bootstrap.handle_bootstrap(install_args)
        if isinstance(result, int):
            return result

    elif args.command == "update":
        print("Güncelleme kontrolü yapılıyor...")
        print(f"ℹ️  En güncel sürüm: v{APP_VERSION} (mevcut)")

    elif args.command == "version":
        print(f"Elyan CLI v{APP_VERSION}")

    elif args.command == "completion":
        from cli.commands.completion import handle_completion
        handle_completion(args)

    elif args.command == "logs":
        from cli.commands import gateway
        gateway.gateway_logs(
            tail=getattr(args, "tail", 50),
            level=getattr(args, "level", "all"),
            filter_term=getattr(args, "filter", None),
        )

    elif args.command == "approve":
        from cli.commands import approve
        try:
            if args.subcommand == "pending":
                approve.pending(output=getattr(args, "output", None))
            elif args.subcommand == "approve":
                approve.approve(request_id=args.request_id)
            elif args.subcommand == "deny":
                approve.deny(request_id=args.request_id)
            else:
                approve.pending(output=None)
        except Exception as e:
            if typer and isinstance(e, typer.Exit):
                return e.exit_code or 0
            raise

    elif args.command == "runs":
        from cli.commands import runs
        try:
            if args.subcommand == "list":
                runs.list_runs(
                    limit=args.limit,
                    status=getattr(args, "status", None),
                    output=getattr(args, "output", None)
                )
            elif args.subcommand == "inspect":
                runs.inspect(run_id=args.run_id)
            elif args.subcommand == "cancel":
                runs.cancel(run_id=args.run_id)
            else:
                runs.list_runs(limit=20, status=None, output=None)
        except Exception as e:
            if typer and isinstance(e, typer.Exit):
                return e.exit_code or 0
            raise

    else:
        parser.print_help()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
