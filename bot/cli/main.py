#!/usr/bin/env python3
"""Elyan CLI — v18.0 Ana giriş noktası"""
import argparse
import os
import sys
from difflib import get_close_matches
from pathlib import Path


TOP_LEVEL_COMMANDS = [
    "doctor",
    "health",
    "logs",
    "status",
    "routines",
    "config",
    "gateway",
    "channels",
    "skills",
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
    "dashboard",
    "onboard",
    "update",
    "version",
    "completion",
]


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
    matches = get_close_matches(raw, TOP_LEVEL_COMMANDS, n=1, cutoff=0.68)
    return matches[0] if matches else ""


def main(argv: list[str] | None = None):
    argv = list(sys.argv[1:] if argv is None else argv)

    parser = argparse.ArgumentParser(prog="elyan", description="Elyan CLI v18.0")
    sub = parser.add_subparsers(dest="command", help="Komut")

    # ── doctor ──────────────────────────────────────────────────────────
    p = sub.add_parser("doctor", help="Sistem tanılaması")
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
                   choices=["list", "info", "install", "enable", "disable", "update", "remove", "search", "check"])
    p.add_argument("name", nargs="?")
    p.add_argument("--available", action="store_true")
    p.add_argument("--enabled", dest="enabled_only", action="store_true")
    p.add_argument("--all", dest="update_all", action="store_true")

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
                   choices=["list", "status", "test", "use", "add",
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
                   choices=["status", "index", "search", "export", "import", "clear", "stats"])
    p.add_argument("query", nargs="?")
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
                   choices=["list", "status", "add", "remove", "start", "stop", "logs", "info", "create"])
    p.add_argument("id", nargs="?")
    p.add_argument("--channel", metavar="CHANNEL")

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

    # ── dashboard ───────────────────────────────────────────────────────
    p = sub.add_parser("dashboard", help="Web kontrol panelini aç")
    p.add_argument("--port", type=int)
    p.add_argument("--no-browser", action="store_true")

    # ── onboard ─────────────────────────────────────────────────────────
    p = sub.add_parser("onboard", help="Kurulum sihirbazı")
    p.add_argument("--headless", action="store_true")
    p.add_argument("--channel", metavar="CHANNEL")
    p.add_argument("--install-daemon", action="store_true")

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

    # ════════════════════════════════════════════════════════════════════
    if argv:
        first = str(argv[0]).strip()
        if first and not first.startswith("-") and first not in TOP_LEVEL_COMMANDS:
            suggestion = _suggest_command(first)
            parser.print_usage(sys.stderr)
            if suggestion:
                print(
                    f"elyan: error: bilinmeyen komut: '{first}'. Şunu mu demek istediniz: '{suggestion}'?",
                    file=sys.stderr,
                )
            else:
                print(f"elyan: error: bilinmeyen komut: '{first}'", file=sys.stderr)
            return 2

    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 0

    # ── Routing ─────────────────────────────────────────────────────────
    if args.command == "doctor":
        from cli.commands import doctor
        doctor.run_doctor(fix=args.fix)

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

    elif args.command == "status":
        from cli.commands import status
        runner = getattr(status, "run_status", None) or getattr(status, "run", None)
        if runner:
            runner(args)
        else:
            print("Status komutu bulunamadı.")
            return 1

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
            print("elyan gateway reload — yakında eklenecek.")

    elif args.command == "channels":
        from cli.commands import channels
        channels.run(args)

    elif args.command == "skills":
        from cli.commands import skills
        skills.handle_skills(args)

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
        agents.handle_agents(args)

    elif args.command == "browser":
        from cli.commands import browser
        browser.handle_browser(args)

    elif args.command == "voice":
        from cli.commands import voice
        voice.handle_voice(args)

    elif args.command == "message":
        from cli.commands import message
        message.handle_message(args)

    elif args.command == "service":
        from cli.daemon import daemon_manager
        if args.action == "install":
            if daemon_manager.install(): print("✅  Servis yüklendi.")
        else:
            if daemon_manager.uninstall(): print("🛑  Servis kaldırıldı.")

    elif args.command == "dashboard":
        from cli.commands import dashboard
        dashboard.open_dashboard(
            port=getattr(args, "port", None),
            no_browser=getattr(args, "no_browser", False),
        )

    elif args.command == "onboard":
        from cli.onboard import start_onboarding
        start_onboarding()

    elif args.command == "update":
        print("Güncelleme kontrolü yapılıyor...")
        print("ℹ️  En güncel sürüm: v18.0.0 (mevcut)")

    elif args.command == "version":
        print("Elyan CLI v18.0.0")

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

    else:
        parser.print_help()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
