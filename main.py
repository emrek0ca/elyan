#!/usr/bin/env python3
"""
Elyan — CLI-First Autonomous AI Agent
"""

import sys
import os
import json
import socket
import time
import subprocess
from pathlib import Path

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
VERSION = "20.0.0"
GATEWAY_PORT = int(os.environ.get("ELYAN_PORT", 18789))
ELYAN_HOME = Path.home() / ".elyan"
CONFIG_FILE = ELYAN_HOME / "elyan.json"


# ── Helpers ──────────────────────────────────────────────────

def _port_alive(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        try:
            s.connect(("127.0.0.1", port))
            return True
        except (ConnectionRefusedError, OSError):
            return False


def _load_config() -> dict:
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text())
    return {}


def _save_config(cfg: dict):
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False))


def _ollama_running() -> bool:
    try:
        import httpx
        r = httpx.get("http://localhost:11434/api/tags", timeout=2)
        return r.status_code == 200
    except Exception:
        return False


def _ollama_models() -> list:
    try:
        import httpx
        r = httpx.get("http://localhost:11434/api/tags", timeout=3)
        data = r.json()
        return [m["name"] for m in data.get("models", [])]
    except Exception:
        return []


def _ollama_pull(model_name: str):
    click.echo(f"  ⬇️  Downloading {model_name}...")
    try:
        proc = subprocess.Popen(
            ["ollama", "pull", model_name],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        )
        for line in proc.stdout:
            click.echo(f"  {line.rstrip()}")
        proc.wait()
        if proc.returncode == 0:
            click.echo(f"  ✅ {model_name} downloaded.")
        else:
            click.echo(f"  ❌ Download failed (exit {proc.returncode})")
    except FileNotFoundError:
        click.echo("  ❌ ollama not installed. Run: brew install ollama")


# ── ROOT ─────────────────────────────────────────────────────

@click.group()
@click.version_option(VERSION, prog_name="Elyan")
def cli():
    """🧠 Elyan — Autonomous AI Agent

    \b
    Quick start:
      elyan start             Start the AI gateway
      elyan models            Manage LLM models
      elyan status            System overview
      elyan doctor            Health check
      elyan team              Agent team info
    """
    pass


# ── elyan start ──────────────────────────────────────────────

@cli.command()
@click.option("--port", default=GATEWAY_PORT, help="Port")
@click.option("--daemon", is_flag=True, help="Run in background")
def start(port, daemon):
    """🚀 Start the Elyan gateway."""
    if _port_alive(port):
        click.echo(f"⚠️  Already running on port {port}")
        return

    cfg = _load_config()
    model = cfg.get("model", "")
    if model:
        click.echo(f"🧠 Model: {model}")
    else:
        click.echo("⚠️  No model set. Run: elyan models use <provider/model>")

    if daemon:
        proc = subprocess.Popen(
            [sys.executable, "-c",
             f"import sys; sys.path.insert(0,'{project_root}'); "
             f"from main import _run_gateway; _run_gateway({port})"],
            stdout=open(ELYAN_HOME / "logs" / "gateway.out.log", "a"),
            stderr=open(ELYAN_HOME / "logs" / "gateway.err.log", "a"),
            start_new_session=True, cwd=str(project_root)
        )
        click.echo(f"✅ Started (PID: {proc.pid}, port: {port})")
    else:
        _run_gateway(port)


def _run_gateway(port: int):
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
            click.echo("❌ Init failed.")
            return
        loop.run_until_complete(server.start())
        click.echo(f"✅ Elyan v{VERSION} — port {port}")
        click.echo("   Ctrl+C to stop.\n")
        loop.run_forever()
    except KeyboardInterrupt:
        click.echo("\n🛑 Stopped.")
    finally:
        try:
            loop.run_until_complete(server.stop())
        except:
            pass
        loop.close()


@cli.command()
@click.option("--port", default=GATEWAY_PORT)
def stop(port):
    """🛑 Stop the gateway."""
    try:
        result = subprocess.run(["lsof", "-ti", f":{port}"], capture_output=True, text=True)
        pids = result.stdout.strip()
        if pids:
            for pid in pids.split("\n"):
                subprocess.run(["kill", "-9", pid.strip()], capture_output=True)
            click.echo(f"🛑 Stopped (port {port})")
        else:
            click.echo(f"ℹ️  Not running on port {port}")
    except Exception as e:
        click.echo(f"⚠️  {e}")


@cli.command()
@click.option("--port", default=GATEWAY_PORT)
def restart(port):
    """🔄 Restart the gateway."""
    click.echo("🔄 Restarting...")
    ctx = click.get_current_context()
    ctx.invoke(stop, port=port)
    time.sleep(1)
    ctx.invoke(start, port=port, daemon=False)


# ── elyan models ─────────────────────────────────────────────

@cli.group(invoke_without_command=True)
@click.pass_context
def models(ctx):
    """🤖 LLM model management."""
    if ctx.invoked_subcommand is None:
        cfg = _load_config()
        current = cfg.get("model", "not set")
        provider = cfg.get("provider", "auto")

        click.echo(f"\n🤖 Model Configuration")
        click.echo(f"{'─' * 40}")
        click.echo(f"  Active: {current}")
        click.echo(f"  Provider: {provider}")
        click.echo()

        # Show provider API keys
        providers = {
            "OpenAI": "OPENAI_API_KEY",
            "Anthropic": "ANTHROPIC_API_KEY",
            "Google": "GOOGLE_API_KEY",
            "Groq": "GROQ_API_KEY",
        }
        click.echo("  API Keys:")
        for name, env in providers.items():
            val = os.environ.get(env, "")
            status = "🟢 set" if val else "🔴 not set"
            click.echo(f"    {name:<12} {status}")

        # Ollama
        ollama_ok = _ollama_running()
        click.echo(f"\n  Ollama: {'🟢 running' if ollama_ok else '🔴 not running'}")
        if ollama_ok:
            local = _ollama_models()
            if local:
                click.echo(f"  Local models:")
                for m in local:
                    marker = " ◀ active" if m == current else ""
                    click.echo(f"    • {m}{marker}")

        click.echo(f"\n  Commands:")
        click.echo(f"    elyan models use <model>       Set active model")
        click.echo(f"    elyan models ollama             List local Ollama models")
        click.echo(f"    elyan models pull <model>       Download Ollama model")
        click.echo()


@models.command("use")
@click.argument("model")
def models_use(model):
    """Set the active LLM model (e.g. gpt-4o, claude-3.5-sonnet, ollama/llama3)."""
    cfg = _load_config()

    # Auto-detect provider
    if "/" in model:
        provider, model_name = model.split("/", 1)
    elif model.startswith("gpt") or model.startswith("o1") or model.startswith("o3"):
        provider, model_name = "openai", model
    elif model.startswith("claude"):
        provider, model_name = "anthropic", model
    elif model.startswith("gemini"):
        provider, model_name = "google", model
    else:
        # Assume ollama for unknown models
        if _ollama_running() and model in _ollama_models():
            provider, model_name = "ollama", model
        else:
            provider, model_name = "openai", model

    cfg["model"] = model
    cfg["provider"] = provider
    cfg["model_name"] = model_name
    _save_config(cfg)
    click.echo(f"  ✅ Model: {model} (provider: {provider})")


@models.command("ollama")
def models_ollama():
    """List local Ollama models."""
    if not _ollama_running():
        click.echo("  🔴 Ollama not running. Start with: ollama serve")
        return

    local = _ollama_models()
    click.echo(f"\n📦 Local Ollama Models ({len(local)})")
    click.echo(f"{'─' * 40}")
    if local:
        for m in local:
            click.echo(f"  • {m}")
        click.echo(f"\n  Use: elyan models use ollama/{local[0]}")
    else:
        click.echo("  No models. Pull one: elyan models pull llama3.2")
    click.echo()


@models.command("pull")
@click.argument("model")
def models_pull(model):
    """Download an Ollama model."""
    _ollama_pull(model)


@models.command("key")
@click.argument("provider")
@click.argument("api_key")
def models_key(provider, api_key):
    """Save an API key for a provider."""
    cfg = _load_config()
    cfg.setdefault("api_keys", {})[provider.lower()] = api_key
    _save_config(cfg)

    # Also set env for current session
    env_map = {
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "google": "GOOGLE_API_KEY",
        "groq": "GROQ_API_KEY",
    }
    env_key = env_map.get(provider.lower())
    if env_key:
        os.environ[env_key] = api_key

    click.echo(f"  ✅ {provider} API key saved.")


# ── elyan status ─────────────────────────────────────────────

@cli.command()
def status():
    """📊 System status overview."""
    cfg = _load_config()
    model = cfg.get("model", "not set")

    click.echo(f"\n🧠 Elyan v{VERSION}")
    click.echo(f"{'═' * 40}")
    click.echo(f"  Model:    {model}")
    click.echo(f"  Gateway:  {'🟢 ONLINE' if _port_alive(GATEWAY_PORT) else '🔴 OFFLINE'}")
    click.echo(f"  Ollama:   {'🟢' if _ollama_running() else '🔴'}")
    click.echo(f"  Platform: {sys.platform} / Python {sys.version.split()[0]}")
    click.echo()

    modules = {
        "Reasoning Engine": "core.reasoning.chain_of_thought",
        "Task Decomposer": "core.reasoning.task_decomposer",
        "Code Validator": "core.reasoning.code_validator",
        "Deep Researcher": "core.reasoning.deep_researcher",
        "Multi-Model Router": "core.reasoning.multi_model_router",
        "Secure Vault": "core.security.secure_vault",
        "Prompt Firewall": "core.security.prompt_firewall",
        "Plugin Manager": "core.plugins.plugin_manager",
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

    click.echo(f"\n  Modules: {loaded}/{len(modules)}")
    click.echo()


# ── elyan doctor ─────────────────────────────────────────────

@cli.command()
@click.option("--fix", is_flag=True, help="Auto-fix issues")
def doctor(fix):
    """🩺 System health check."""
    issues = []
    click.echo(f"\n🩺 Elyan Doctor")
    click.echo(f"{'─' * 40}\n")

    # Python
    py = sys.version_info
    click.echo(f"  {'✅' if py >= (3, 10) else '❌'} Python {py.major}.{py.minor}")
    if py < (3, 10):
        issues.append("python")

    # Home dir
    if ELYAN_HOME.exists():
        click.echo(f"  ✅ Home: {ELYAN_HOME}")
    else:
        if fix:
            ELYAN_HOME.mkdir(parents=True, exist_ok=True)
            click.echo(f"  ✅ Created: {ELYAN_HOME}")
        else:
            click.echo(f"  ⚠️  No home dir")
            issues.append("home")

    # Config
    if CONFIG_FILE.exists():
        click.echo(f"  ✅ Config found")
    else:
        if fix:
            _save_config({"model": "", "provider": ""})
            click.echo(f"  ✅ Config created")
        else:
            click.echo(f"  ⚠️  No config (run --fix or `elyan models use <model>`)")
            issues.append("config")

    # Model
    cfg = _load_config()
    model = cfg.get("model", "")
    if model:
        click.echo(f"  ✅ Model: {model}")
    else:
        click.echo(f"  ⚠️  No model set (run `elyan models use <model>`)")
        issues.append("model")

    # Gateway
    click.echo(f"  {'✅' if _port_alive(GATEWAY_PORT) else 'ℹ️ '} Gateway {'online' if _port_alive(GATEWAY_PORT) else 'offline'}")

    # Ollama
    click.echo(f"  {'✅' if _ollama_running() else 'ℹ️ '} Ollama {'running' if _ollama_running() else 'not running'}")

    # Key deps
    for dep in ["cryptography", "aiohttp", "httpx", "click", "psutil"]:
        try:
            __import__(dep)
            click.echo(f"  ✅ {dep}")
        except ImportError:
            click.echo(f"  ❌ {dep}")
            issues.append(dep)
            if fix:
                subprocess.run([sys.executable, "-m", "pip", "install", dep, "-q"], capture_output=True)
                click.echo(f"     → installed")

    click.echo(f"\n{'─' * 40}")
    if issues:
        click.echo(f"  ⚠️  {len(issues)} issue(s)" + (" — run `elyan doctor --fix`" if not fix else ""))
    else:
        click.echo(f"  ✅ All good!")
    click.echo()


# ── elyan team ───────────────────────────────────────────────

@cli.group(invoke_without_command=True)
@click.pass_context
def team(ctx):
    """🏢 Agent team info."""
    if ctx.invoked_subcommand is None:
        from core.multi_agent.specialists import get_specialist_registry
        r = get_specialist_registry()
        click.echo(f"\n{r.format_team_status()}\n")


@team.command("test")
@click.argument("message")
def team_test(message):
    """Test agent routing for a message."""
    from core.multi_agent.specialists import get_specialist_registry
    s = get_specialist_registry().select_for_input(message)
    click.echo(f"\n  \"{message}\" → {s.emoji} {s.name} ({s.role})\n")


# ── elyan config ─────────────────────────────────────────────

@cli.group(invoke_without_command=True)
@click.pass_context
def config(ctx):
    """⚙️  View/edit configuration."""
    if ctx.invoked_subcommand is None:
        cfg = _load_config()
        click.echo(f"\n⚙️  Config: {CONFIG_FILE}")
        click.echo(json.dumps(cfg, indent=2, ensure_ascii=False))
        click.echo()


@config.command("set")
@click.argument("key")
@click.argument("value")
def config_set(key, value):
    """Set a config value."""
    cfg = _load_config()
    try:
        cfg[key] = json.loads(value)
    except:
        cfg[key] = value
    _save_config(cfg)
    click.echo(f"  ✅ {key} = {value}")


@config.command("get")
@click.argument("key")
def config_get(key):
    """Read a config value."""
    cfg = _load_config()
    click.echo(f"  {key} = {json.dumps(cfg.get(key), ensure_ascii=False)}")


# ── elyan logs ───────────────────────────────────────────────

@cli.command()
@click.option("--tail", default=20, help="Lines")
def logs(tail):
    """📜 Show recent logs."""
    dirs = [ELYAN_HOME / "logs", project_root / "logs"]
    for d in dirs:
        if d.exists():
            files = sorted(d.glob("*.log"), reverse=True)
            if files:
                lines = files[0].read_text(errors="ignore").strip().split("\n")
                click.echo(f"\n📜 {files[0].name} (last {min(tail, len(lines))}):\n")
                for line in lines[-tail:]:
                    click.echo(f"  {line}")
                click.echo()
                return
    click.echo("📜 No logs.\n")


# ── elyan dashboard ──────────────────────────────────────────

@cli.command()
@click.option("--port", default=GATEWAY_PORT)
def dashboard(port):
    """🖥️  Open web dashboard."""
    import webbrowser
    url = f"http://localhost:{port}/dashboard"
    if not _port_alive(port):
        click.echo(f"⚠️  Gateway not running. Start with: elyan start")
        return
    click.echo(f"🌐 Opening {url}")
    webbrowser.open(url)


# ── ENTRY POINT ──────────────────────────────────────────────

def _cli_main():
    (ELYAN_HOME / "logs").mkdir(parents=True, exist_ok=True)
    cli()


def main():
    _cli_main()


if __name__ == "__main__":
    _cli_main()
