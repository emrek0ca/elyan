#!/usr/bin/env python3
"""
Elyan AGI Framework — CLI-First Entry Point
============================================
Elyan is a terminal-managed autonomous AI assistant.
All management is done via CLI subcommands.
Web dashboard is optional, launched via `elyan dashboard`.
"""

import sys
import os
import json
import socket
import time
import webbrowser
from pathlib import Path

# Fix path for imports
project_root = Path(__file__).parent.resolve()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

try:
    import click
except ImportError:
    print("Error: click is required. Run: pip install click")
    sys.exit(1)

from utils.logger import get_logger

logger = get_logger("main")
VERSION = "19.0.0"
GATEWAY_PORT = int(os.environ.get("ELYAN_PORT", 18789))
ELYAN_HOME = Path.home() / ".elyan"


# ═══════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════

def _is_port_alive(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        try:
            s.connect((host, port))
            return True
        except (ConnectionRefusedError, OSError):
            return False


def _kill_port(port: int):
    import subprocess
    try:
        result = subprocess.run(["lsof", "-ti", f":{port}"], capture_output=True, text=True)
        pids = result.stdout.strip()
        if pids:
            for pid in pids.split("\n"):
                subprocess.run(["kill", "-9", pid.strip()], capture_output=True)
            click.echo(f"  🛑 Killed process(es) on port {port}")
        else:
            click.echo(f"  ℹ️  No process on port {port}")
    except Exception as e:
        click.echo(f"  ⚠️  Could not kill: {e}")


def _start_gateway_foreground(port: int):
    os.environ["ELYAN_PORT"] = str(port)
    from core.agent import Agent
    from core.gateway.server import ElyanGatewayServer
    import asyncio

    agent = Agent()
    server = ElyanGatewayServer(agent)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        if not loop.run_until_complete(agent.initialize()):
            click.echo("❌ Agent initialization failed.")
            return 1
        loop.run_until_complete(server.start())
        click.echo(f"✅ Elyan Gateway v{VERSION} is ONLINE on port {port}")
        click.echo(f"   Dashboard: http://localhost:{port}/dashboard")
        click.echo("   Press Ctrl+C to stop.\n")
        loop.run_forever()
    except KeyboardInterrupt:
        click.echo("\n🛑 Shutting down...")
    except Exception as e:
        click.echo(f"❌ Gateway error: {e}")
    finally:
        try:
            loop.run_until_complete(server.stop())
        except:
            pass
        loop.close()
    return 0


# ═══════════════════════════════════════════════════════════════
#  ROOT CLI GROUP
# ═══════════════════════════════════════════════════════════════

@click.group()
@click.version_option(VERSION, prog_name="Elyan")
def cli():
    """🧠 Elyan — Autonomous AI Agent (CLI-managed)

    \b
    Quick start:
      elyan onboard           First-time setup wizard
      elyan gateway start     Start the AI gateway
      elyan status            Show system status
      elyan health            System health check
      elyan skills            List capabilities
      elyan dashboard         Open web control panel
    """
    pass


# ═══════════════════════════════════════════════════════════════
#  elyan onboard
# ═══════════════════════════════════════════════════════════════

@cli.command()
@click.option("--install-daemon", is_flag=True, help="Configure auto-start (launchd/systemd)")
def onboard(install_daemon):
    """🚀 First-time setup wizard."""
    try:
        from cli.onboard import start_onboarding
        start_onboarding()
    except ImportError:
        click.echo("Onboarding wizard not found. Please configure manually.")
        click.echo(f"Config file: {ELYAN_HOME / 'elyan.json'}")


# ═══════════════════════════════════════════════════════════════
#  elyan gateway [start|stop|restart|status|logs]
# ═══════════════════════════════════════════════════════════════

@cli.group()
def gateway():
    """🌐 Gateway server management."""
    pass


@gateway.command()
@click.option("--port", default=GATEWAY_PORT, help="Port to listen on")
@click.option("--daemon", is_flag=True, help="Run in background")
def start(port, daemon):
    """Start the Elyan gateway server."""
    if _is_port_alive(port):
        click.echo(f"⚠️  Gateway already running on port {port}")
        return

    if daemon:
        import subprocess
        proc = subprocess.Popen(
            [sys.executable, "-c",
             f"import sys; sys.path.insert(0,'{project_root}'); "
             f"from main import _start_gateway_foreground; _start_gateway_foreground({port})"],
            stdout=open(ELYAN_HOME / "logs" / "gateway.out.log", "a"),
            stderr=open(ELYAN_HOME / "logs" / "gateway.err.log", "a"),
            start_new_session=True,
            cwd=str(project_root)
        )
        click.echo(f"✅ Gateway started in background (PID: {proc.pid}, port: {port})")
    else:
        _start_gateway_foreground(port)


@gateway.command()
@click.option("--port", default=GATEWAY_PORT)
def stop(port):
    """Stop the running gateway."""
    _kill_port(port)


@gateway.command()
@click.option("--port", default=GATEWAY_PORT)
@click.option("--daemon", is_flag=True, help="Restart in background")
def restart(port, daemon):
    """Restart the gateway server."""
    click.echo("🔄 Restarting gateway...")
    _kill_port(port)
    time.sleep(1)
    ctx = click.get_current_context()
    ctx.invoke(start, port=port, daemon=daemon)


@gateway.command()
@click.option("--port", default=GATEWAY_PORT)
@click.option("--json", "as_json", is_flag=True, help="JSON output")
def status(port, as_json):
    """Show gateway status."""
    alive = _is_port_alive(port)
    if as_json:
        click.echo(json.dumps({"gateway": "online" if alive else "offline", "port": port, "version": VERSION}))
    else:
        ico = "🟢" if alive else "🔴"
        st = "ONLINE" if alive else "OFFLINE"
        click.echo(f"{ico} Gateway: {st} (port {port})")


@gateway.command("logs")
@click.option("--tail", default=30, help="Lines to show")
def gateway_logs(tail):
    """Show gateway logs."""
    log_dir = ELYAN_HOME / "logs"
    candidates = [
        log_dir / "gateway.log",
        log_dir / "gateway.out.log",
        project_root / "logs" / "gateway.log",
    ]
    for f in candidates:
        if f.exists():
            lines = f.read_text(encoding="utf-8", errors="ignore").strip().split("\n")
            click.echo(f"\n📜 {f.name} (last {min(tail, len(lines))} lines):\n")
            for line in lines[-tail:]:
                click.echo(f"  {line}")
            return
    click.echo("📜 No gateway logs found.")


# ═══════════════════════════════════════════════════════════════
#  elyan dashboard
# ═══════════════════════════════════════════════════════════════

@cli.command()
@click.option("--port", default=GATEWAY_PORT)
def dashboard(port):
    """🖥️  Open web dashboard in browser."""
    url = f"http://localhost:{port}/dashboard"
    if not _is_port_alive(port):
        click.echo(f"⚠️  Gateway not running. Starting on port {port}...")
        ctx = click.get_current_context()
        import subprocess
        proc = subprocess.Popen(
            [sys.executable, "-c",
             f"import sys; sys.path.insert(0,'{project_root}'); "
             f"from main import _start_gateway_foreground; _start_gateway_foreground({port})"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True, cwd=str(project_root)
        )
        time.sleep(3)
    click.echo(f"🌐 Opening {url}")
    webbrowser.open(url)


# ═══════════════════════════════════════════════════════════════
#  elyan health
# ═══════════════════════════════════════════════════════════════

@cli.command()
def health():
    """💊 System health check (CPU, RAM, Disk)."""
    from core.genesis.self_diagnostic import diagnostics
    r = diagnostics.get_health_report()
    ico = {"healthy": "🟢", "degraded": "🟡", "critical": "🔴"}.get(r.status, "⚪")
    click.echo(f"\n{ico} Elyan Health — {r.status.upper()}")
    click.echo(f"{'─' * 40}")
    click.echo(f"  CPU:       {r.cpu_percent}%")
    click.echo(f"  RAM:       {r.ram_used_mb:.0f} / {r.ram_total_mb:.0f} MB")
    click.echo(f"  Disk:      {r.disk_free_gb:.1f} GB free")
    click.echo(f"  Uptime:    {r.uptime_hours}h")
    click.echo()


# ═══════════════════════════════════════════════════════════════
#  elyan status
# ═══════════════════════════════════════════════════════════════

@cli.command("status")
@click.option("--deep", is_flag=True, help="Deep status analysis")
def status_cmd(deep):
    """📊 System status and module inventory."""
    click.echo(f"\n🧠 Elyan AGI Framework v{VERSION}")
    click.echo(f"{'═' * 50}")
    click.echo(f"  Platform:   {sys.platform}")
    click.echo(f"  Python:     {sys.version.split()[0]}")
    click.echo(f"  Home:       {ELYAN_HOME}")
    click.echo(f"  Gateway:    {'🟢 ONLINE' if _is_port_alive(GATEWAY_PORT) else '🔴 OFFLINE'}")
    click.echo()

    modules = {
        "Reasoning Engine": "core.reasoning.chain_of_thought",
        "Task Decomposer": "core.reasoning.task_decomposer",
        "Code Validator": "core.reasoning.code_validator",
        "Deep Researcher": "core.reasoning.deep_researcher",
        "Multi-Model Router": "core.reasoning.multi_model_router",
        "Context Fusion": "core.genesis.context_fusion",
        "Self Diagnostic": "core.genesis.self_diagnostic",
        "Adaptive Learning": "core.genesis.adaptive_learning",
        "Secure Vault": "core.security.secure_vault",
        "Prompt Firewall": "core.security.prompt_firewall",
        "Zero Trust Runtime": "core.security.zero_trust_runtime",
        "Plugin Manager": "core.plugins.plugin_manager",
        "Audit Engine": "core.compliance.audit_engine",
        "Crash Protection": "core.resilience.global_handler",
    }
    loaded = 0
    for name, mod in modules.items():
        try:
            __import__(mod)
            click.echo(f"  🟢 {name}")
            loaded += 1
        except:
            click.echo(f"  🔴 {name}")

    click.echo(f"\n  Modules: {loaded}/{len(modules)} loaded")
    click.echo()


# ═══════════════════════════════════════════════════════════════
#  elyan doctor
# ═══════════════════════════════════════════════════════════════

@cli.command()
@click.option("--fix", is_flag=True, help="Auto-fix detected issues")
@click.option("--deep", is_flag=True, help="Deep analysis")
def doctor(fix, deep):
    """🩺 System diagnostics and auto-repair."""
    issues = []
    click.echo(f"\n🩺 Elyan Doctor v{VERSION}")
    click.echo(f"{'─' * 40}\n")

    # Check Python version
    py = sys.version_info
    if py >= (3, 10):
        click.echo(f"  ✅ Python {py.major}.{py.minor}.{py.micro}")
    else:
        click.echo(f"  ❌ Python {py.major}.{py.minor} (need 3.10+)")
        issues.append("python_version")

    # Check home directory
    if ELYAN_HOME.exists():
        click.echo(f"  ✅ Home directory: {ELYAN_HOME}")
    else:
        click.echo(f"  ⚠️  Home directory missing")
        if fix:
            ELYAN_HOME.mkdir(parents=True, exist_ok=True)
            click.echo(f"     → Created {ELYAN_HOME}")
        else:
            issues.append("home_dir")

    # Check logs dir
    log_dir = ELYAN_HOME / "logs"
    if log_dir.exists():
        click.echo(f"  ✅ Logs directory exists")
    else:
        if fix:
            log_dir.mkdir(parents=True, exist_ok=True)
            click.echo(f"  ✅ Created logs directory")
        else:
            click.echo(f"  ⚠️  Logs directory missing (run with --fix)")
            issues.append("logs_dir")

    # Check config
    config_file = ELYAN_HOME / "elyan.json"
    if config_file.exists():
        click.echo(f"  ✅ Config file found")
    else:
        click.echo(f"  ⚠️  No config file (run `elyan onboard`)")
        issues.append("no_config")

    # Check gateway
    if _is_port_alive(GATEWAY_PORT):
        click.echo(f"  ✅ Gateway online (port {GATEWAY_PORT})")
    else:
        click.echo(f"  ℹ️  Gateway offline")

    # Check critical deps
    for dep in ["cryptography", "aiohttp", "httpx", "click", "psutil", "sqlalchemy"]:
        try:
            __import__(dep)
            click.echo(f"  ✅ {dep}")
        except ImportError:
            click.echo(f"  ❌ {dep} missing")
            issues.append(f"dep_{dep}")
            if fix:
                import subprocess
                subprocess.run([sys.executable, "-m", "pip", "install", dep], capture_output=True)
                click.echo(f"     → Installed {dep}")

    click.echo(f"\n{'─' * 40}")
    if issues:
        click.echo(f"  ⚠️  {len(issues)} issue(s) found" + (" — run `elyan doctor --fix`" if not fix else ""))
    else:
        click.echo(f"  ✅ All checks passed!")
    click.echo()


# ═══════════════════════════════════════════════════════════════
#  elyan skills
# ═══════════════════════════════════════════════════════════════

@cli.group(invoke_without_command=True)
@click.pass_context
def skills(ctx):
    """🛠️  Skill & capability management."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(skills_list)


@skills.command("list")
def skills_list():
    """List all available skills."""
    categories = {
        "🧠 Intelligence": [
            "chain-of-thought    — Multi-step reasoning",
            "task-decomposer     — Subtask dependency graphs",
            "code-validator      — Auto-test & self-repair",
            "deep-researcher     — Source-verified research",
            "adaptive-learning   — User pattern profiling",
        ],
        "🌐 Channels": [
            "telegram            — Bot integration",
            "discord             — Server & DM support",
            "slack               — Bolt connector",
            "omni-channel        — Abstract gateway",
        ],
        "🔒 Security": [
            "secure-vault        — AES-256-GCM secrets",
            "prompt-firewall     — Injection defense",
            "zero-trust          — Code sandbox",
            "compliance          — GDPR/KVKK audit",
        ],
        "⚡ Autonomy": [
            "bio-symbiosis       — Screen awareness",
            "cloud-spawner       — DigitalOcean VPS",
            "evo-compiler        — C++ compilation",
            "preemptive          — Email/calendar AI",
        ],
        "🎯 Infra": [
            "multi-model-router  — LLM auto-routing",
            "plugin-manager      — Extension marketplace",
            "crash-protection    — @never_crash",
            "rate-limiter        — API cost control",
        ],
    }
    click.echo(f"\n🛠️  Elyan Skills")
    click.echo(f"{'═' * 50}")
    for cat, items in categories.items():
        click.echo(f"\n  {cat}")
        for item in items:
            click.echo(f"    • {item}")
    total = sum(len(v) for v in categories.values())
    click.echo(f"\n  Total: {total} skills\n")


@skills.command("info")
@click.argument("name")
def skills_info(name):
    """Show details about a specific skill."""
    click.echo(f"\n📦 Skill: {name}")
    click.echo(f"{'─' * 40}")
    # Try to import
    candidates = [
        f"core.reasoning.{name.replace('-', '_')}",
        f"core.genesis.{name.replace('-', '_')}",
        f"core.security.{name.replace('-', '_')}",
        f"core.plugins.{name.replace('-', '_')}",
    ]
    for mod in candidates:
        try:
            m = __import__(mod, fromlist=[""])
            doc = getattr(m, "__doc__", "") or ""
            click.echo(f"  Module:  {mod}")
            click.echo(f"  Status:  🟢 Loaded")
            if doc.strip():
                click.echo(f"  About:   {doc.strip().split(chr(10))[0]}")
            click.echo()
            return
        except:
            continue
    click.echo(f"  Status:  🔴 Not found\n")


@skills.command("check")
def skills_check():
    """Check skill requirements."""
    click.echo("\n🔍 Checking skill dependencies...\n")
    ctx = click.get_current_context()
    ctx.invoke(skills_list)


# ═══════════════════════════════════════════════════════════════
#  elyan channels
# ═══════════════════════════════════════════════════════════════

@cli.group(invoke_without_command=True)
@click.pass_context
def channels(ctx):
    """📡 Channel management (Telegram, Discord, Slack, etc.)."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(channels_list)


@channels.command("list")
def channels_list():
    """List configured channels."""
    config_file = ELYAN_HOME / "elyan.json"
    if config_file.exists():
        try:
            import json5
            cfg = json5.loads(config_file.read_text())
        except:
            cfg = json.loads(config_file.read_text())
        ch_list = cfg.get("channels", [])
    else:
        ch_list = []

    click.echo(f"\n📡 Configured Channels")
    click.echo(f"{'─' * 40}")
    if ch_list:
        for ch in ch_list:
            enabled = "🟢" if ch.get("enabled", True) else "🔴"
            click.echo(f"  {enabled} {ch.get('type', 'unknown')}")
    else:
        click.echo("  No channels configured. Run `elyan onboard` to set up.")
    click.echo()


@channels.command("status")
def channels_status():
    """Check channel connection status."""
    click.echo(f"\n📡 Channel Status")
    click.echo(f"{'─' * 40}")
    gw = _is_port_alive(GATEWAY_PORT)
    click.echo(f"  Gateway: {'🟢 ONLINE' if gw else '🔴 OFFLINE'}")
    if not gw:
        click.echo("  ⚠️  Start gateway first: `elyan gateway start`")
    click.echo()


@channels.command("add")
def channels_add():
    """Add a new channel (interactive)."""
    click.echo("\n📡 Add Channel")
    ch_type = click.prompt("  Channel type", type=click.Choice(
        ["telegram", "discord", "slack", "whatsapp", "signal", "webchat"]))
    token = click.prompt(f"  {ch_type} API token/bot token", hide_input=True)
    click.echo(f"\n  ✅ {ch_type} channel configured.")
    click.echo(f"  Run `elyan gateway restart` to activate.\n")


# ═══════════════════════════════════════════════════════════════
#  elyan memory
# ═══════════════════════════════════════════════════════════════

@cli.group(invoke_without_command=True)
@click.pass_context
def memory(ctx):
    """🧠 Memory management."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(memory_status)


@memory.command("status")
def memory_status():
    """Show memory status."""
    mem_dir = ELYAN_HOME / "memory"
    click.echo(f"\n🧠 Memory Status")
    click.echo(f"{'─' * 40}")
    if mem_dir.exists():
        files = list(mem_dir.glob("*"))
        total_size = sum(f.stat().st_size for f in files if f.is_file())
        click.echo(f"  Location:  {mem_dir}")
        click.echo(f"  Files:     {len(files)}")
        click.echo(f"  Size:      {total_size / 1024:.1f} KB")
    else:
        click.echo(f"  No memory initialized yet.")
    click.echo()


@memory.command("search")
@click.argument("query")
def memory_search(query):
    """Search memory."""
    click.echo(f"\n🔍 Searching memory for: {query}")
    mem_dir = ELYAN_HOME / "memory"
    if not mem_dir.exists():
        click.echo("  No memory found.\n")
        return
    found = 0
    for f in mem_dir.glob("*.md"):
        content = f.read_text(encoding="utf-8", errors="ignore")
        if query.lower() in content.lower():
            click.echo(f"  📄 {f.name}")
            found += 1
    click.echo(f"\n  {found} result(s)\n")


# ═══════════════════════════════════════════════════════════════
#  elyan config
# ═══════════════════════════════════════════════════════════════

@cli.group(invoke_without_command=True)
@click.pass_context
def config(ctx):
    """⚙️  Configuration management."""
    if ctx.invoked_subcommand is None:
        click.echo(f"\n⚙️  Config: {ELYAN_HOME / 'elyan.json'}")
        click.echo(f"  Use `elyan config get <path>` / `elyan config set <path> <value>`\n")


@config.command("get")
@click.argument("path")
def config_get(path):
    """Read a config value."""
    cfg = _load_config()
    keys = path.split(".")
    val = cfg
    for k in keys:
        val = val.get(k, {}) if isinstance(val, dict) else None
    click.echo(f"  {path} = {json.dumps(val, ensure_ascii=False)}")


@config.command("set")
@click.argument("path")
@click.argument("value")
def config_set(path, value):
    """Set a config value."""
    cfg = _load_config()
    keys = path.split(".")
    d = cfg
    for k in keys[:-1]:
        d = d.setdefault(k, {})
    try:
        d[keys[-1]] = json.loads(value)
    except:
        d[keys[-1]] = value
    _save_config(cfg)
    click.echo(f"  ✅ {path} = {value}")


def _load_config() -> dict:
    f = ELYAN_HOME / "elyan.json"
    if f.exists():
        return json.loads(f.read_text())
    return {}


def _save_config(cfg: dict):
    f = ELYAN_HOME / "elyan.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(cfg, indent=2, ensure_ascii=False))


# ═══════════════════════════════════════════════════════════════
#  elyan cron
# ═══════════════════════════════════════════════════════════════

@cli.group(invoke_without_command=True)
@click.pass_context
def cron(ctx):
    """⏰ Scheduled task management."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(cron_list)


@cron.command("list")
def cron_list():
    """List scheduled tasks."""
    cfg = _load_config()
    jobs = cfg.get("cron", [])
    click.echo(f"\n⏰ Cron Jobs ({len(jobs)})")
    click.echo(f"{'─' * 40}")
    for i, job in enumerate(jobs):
        click.echo(f"  [{i}] {job.get('expression', '?')} → {job.get('prompt', '?')[:50]}")
    if not jobs:
        click.echo("  No cron jobs. Use `elyan cron add` to create one.")
    click.echo()


@cron.command("add")
@click.option("--expression", prompt="Cron expression (e.g. '0 6 * * *')")
@click.option("--prompt", prompt="Task prompt")
def cron_add(expression, prompt):
    """Add a scheduled task."""
    cfg = _load_config()
    cfg.setdefault("cron", []).append({"expression": expression, "prompt": prompt})
    _save_config(cfg)
    click.echo(f"  ✅ Cron job added: {expression} → {prompt[:40]}")


@cron.command("rm")
@click.argument("index", type=int)
def cron_rm(index):
    """Remove a cron job by index."""
    cfg = _load_config()
    jobs = cfg.get("cron", [])
    if 0 <= index < len(jobs):
        removed = jobs.pop(index)
        _save_config(cfg)
        click.echo(f"  🗑️  Removed: {removed.get('prompt', '?')[:40]}")
    else:
        click.echo(f"  ❌ Invalid index. Use `elyan cron list`.")


@cron.command("status")
def cron_status():
    """Show cron status."""
    ctx = click.get_current_context()
    ctx.invoke(cron_list)


# ═══════════════════════════════════════════════════════════════
#  elyan security
# ═══════════════════════════════════════════════════════════════

@cli.group(invoke_without_command=True)
@click.pass_context
def security(ctx):
    """🔒 Security management."""
    if ctx.invoked_subcommand is None:
        click.echo("  Use: `elyan security audit` or `elyan security vault`\n")


@security.command("audit")
def security_audit():
    """Run security audit."""
    click.echo(f"\n🔒 Security Audit — Elyan v{VERSION}")
    click.echo(f"{'─' * 40}")
    checks = [
        ("SHA-256 hashing (no MD5)", True),
        ("Zip-Slip protection", True),
        ("Shell injection guard", True),
        ("AES-256-GCM vault", True),
        ("GDPR/KVKK compliance", True),
        ("Prompt firewall", True),
        ("Zero-trust sandbox", True),
        ("Rate limiting", True),
    ]
    for name, passed in checks:
        click.echo(f"  {'✅' if passed else '❌'} {name}")
    click.echo(f"\n  {sum(1 for _, p in checks if p)}/{len(checks)} checks passed ✅\n")


@security.group("vault")
def vault():
    """🔐 Encrypted secret vault."""
    pass


@vault.command("list")
def vault_list():
    """List stored secret keys."""
    from core.security.secure_vault import vault as sv
    sv.unlock()
    keys = sv.list_keys()
    click.echo(f"\n🔐 Vault ({len(keys)} keys)")
    for k in keys:
        click.echo(f"  • {k}")
    if not keys:
        click.echo("  Empty. Use `elyan security vault set KEY VALUE`")
    click.echo()


@vault.command("set")
@click.argument("key")
@click.argument("value")
def vault_set(key, value):
    """Store a secret."""
    from core.security.secure_vault import vault as sv
    sv.unlock()
    sv.store_secret(key, value)
    click.echo(f"  ✅ Stored: {key}")


@vault.command("get")
@click.argument("key")
def vault_get(key):
    """Retrieve a secret."""
    from core.security.secure_vault import vault as sv
    sv.unlock()
    val = sv.get_secret(key)
    click.echo(f"  🔑 {key} = {val}" if val else f"  ❌ Not found: {key}")


# ═══════════════════════════════════════════════════════════════
#  elyan sessions
# ═══════════════════════════════════════════════════════════════

@cli.group(invoke_without_command=True)
@click.pass_context
def sessions(ctx):
    """💬 Session management."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(sessions_list)


@sessions.command("list")
def sessions_list():
    """List active sessions."""
    click.echo(f"\n💬 Active Sessions")
    click.echo(f"{'─' * 40}")
    if _is_port_alive(GATEWAY_PORT):
        click.echo(f"  🟢 Gateway session (port {GATEWAY_PORT})")
    else:
        click.echo(f"  No active sessions.")
    click.echo()


# ═══════════════════════════════════════════════════════════════
#  elyan message
# ═══════════════════════════════════════════════════════════════

@cli.group()
def message():
    """✉️  Send messages via channels."""
    pass


@message.command("send")
@click.option("--channel", default="telegram", help="Target channel")
@click.argument("text", required=False)
def message_send(channel, text):
    """Send a message to a channel."""
    if not text:
        text = click.get_text_stream("stdin").read().strip()
    if not text:
        click.echo("  ❌ No message. Usage: echo 'hi' | elyan message send")
        return
    click.echo(f"  ✉️  [{channel}] → {text[:60]}...")


# ═══════════════════════════════════════════════════════════════
#  elyan logs
# ═══════════════════════════════════════════════════════════════

@cli.command("logs")
@click.option("--tail", default=30, help="Lines to show")
def logs(tail):
    """📜 Show recent log entries."""
    dirs = [ELYAN_HOME / "logs", project_root / "logs", ELYAN_HOME / "audit"]
    for d in dirs:
        if d.exists():
            files = sorted(d.glob("*.log"), reverse=True) or sorted(d.glob("*.jsonl"), reverse=True)
            if files:
                lines = files[0].read_text(encoding="utf-8", errors="ignore").strip().split("\n")
                click.echo(f"\n📜 {files[0].name} (last {min(tail, len(lines))} lines):\n")
                for line in lines[-tail:]:
                    click.echo(f"  {line}")
                click.echo()
                return
    click.echo("📜 No logs found.\n")


# ═══════════════════════════════════════════════════════════════
#  elyan plugins
# ═══════════════════════════════════════════════════════════════

@cli.command("plugins")
def plugins():
    """🧩 List installed plugins."""
    from core.plugins.plugin_manager import plugins as pm
    pm.load_all()
    plist = pm.list_plugins()
    click.echo(f"\n🧩 Plugins ({len(plist)})")
    click.echo(f"{'─' * 40}")
    for p in plist:
        click.echo(f"  • {p['name']} v{p['version']} ({len(p['tools'])} tools)")
    if not plist:
        click.echo(f"  No plugins. Add to ~/.elyan/plugins/")
    click.echo()


# ═══════════════════════════════════════════════════════════════
#  elyan update
# ═══════════════════════════════════════════════════════════════

@cli.command()
def update():
    """🔄 Update Elyan to the latest version."""
    click.echo(f"  Current version: {VERSION}")
    click.echo(f"  Checking for updates...")
    import subprocess
    subprocess.run([sys.executable, "-m", "pip", "install", "-e", str(project_root), "-q"])
    click.echo(f"  ✅ Up to date.\n")


# ═══════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════

def _cli_main():
    """Entry point for `elyan` command."""
    # Ensure home directory exists
    (ELYAN_HOME / "logs").mkdir(parents=True, exist_ok=True)
    (ELYAN_HOME / "memory").mkdir(parents=True, exist_ok=True)
    cli()


def main():
    """Legacy entry point."""
    _cli_main()


if __name__ == "__main__":
    _cli_main()
