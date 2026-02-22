#!/usr/bin/env python3
"""
Elyan v18.0 - Unified Entry Point
Usage:
  python main.py         -> Starts Desktop UI
  python main.py --cli   -> Starts Telegram/CLI mode (Gateway)
  python main.py --onboard -> Starts onboarding wizard

FIX BUG-FUNC-001:
- loop.close() in finally block (always runs)
- server.stop() called on any exception, not just KeyboardInterrupt
- --onboard takes priority over --cli
"""

import argparse
import asyncio
import sys
import os
import json
import socket
import time
from pathlib import Path

# Fix path for imports
project_root = Path(__file__).parent.resolve()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from utils.logger import get_logger

logger = get_logger("main")
VERSION = "18.0.0"
GATEWAY_PORT = int(os.environ.get("ELYAN_PORT", 18789))


def check_port_available(port: int, host: str = "127.0.0.1") -> bool:
    """
    BUG-FUNC-009 hardened:
    Avoid false negatives right after restart (TIME_WAIT) by checking
    active listeners first, then probing bind with SO_REUSEADDR.
    """
    # If something is actively accepting, port is in use.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.3)
        try:
            if probe.connect_ex((host, port)) == 0:
                return False
        except OSError:
            pass

    # Fallback bind probe that tolerates restart race windows.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.settimeout(1)
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def find_existing_gateway(port: int, host: str = "127.0.0.1") -> bool:
    """Check if an Elyan gateway is already running on the port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        try:
            s.connect((host, port))
            return True
        except (ConnectionRefusedError, OSError):
            return False


def start_ui():
    """Start the PyQt6 based Desktop application."""
    try:
        logger.info(f"Starting Elyan UI v{VERSION}...")
        from ui.clean_main_app import main as run_ui
        return run_ui()
    except Exception as e:
        logger.error(f"UI failed: {e}", exc_info=True)
        return 1


def start_cli():
    """Start the Unified Gateway (API + Telegram + All Channels)."""
    # BUG-FUNC-009: Check port availability before starting.
    # Add short retries to survive rapid stop/start races.
    if not check_port_available(GATEWAY_PORT):
        if find_existing_gateway(GATEWAY_PORT):
            logger.error(
                f"Port {GATEWAY_PORT} is already in use by another Elyan instance. "
                f"Run 'elyan gateway status' to check, or set ELYAN_PORT env var."
            )
            return 1
        became_free = False
        for _ in range(8):  # ~2s total
            if check_port_available(GATEWAY_PORT):
                became_free = True
                break
            time.sleep(0.25)
        if not became_free:
            logger.error(
                f"Port {GATEWAY_PORT} is already in use by another process. "
                f"Free the port or set ELYAN_PORT=<other_port> and retry."
            )
            return 1

    try:
        logger.info(f"Starting Elyan Gateway v{VERSION}...")
        from core.agent import Agent
        from core.gateway.server import ElyanGatewayServer

        agent = Agent()
        server = ElyanGatewayServer(agent)

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            # 1. Initialize Agent
            if not loop.run_until_complete(agent.initialize()):
                logger.error("Agent initialization failed.")
                return 1

            # 2. Start Gateway
            loop.run_until_complete(server.start())

            logger.info("Gateway and Dashboard are now ONLINE.")
            logger.info(f"Access Dashboard at: http://localhost:{GATEWAY_PORT}/dashboard")

            # 3. Keep the loop running
            loop.run_forever()

        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received, shutting down...")
        except Exception as e:
            logger.error(f"Gateway runtime error: {e}", exc_info=True)
        finally:
            # BUG-FUNC-001: Always stop server and close loop
            logger.info("Stopping gateway...")
            try:
                loop.run_until_complete(server.stop())
            except Exception as e:
                logger.error(f"Error during gateway stop: {e}")
            finally:
                loop.close()
                logger.info("Event loop closed.")

        return 0

    except Exception as e:
        logger.error(f"Gateway failed to start: {e}", exc_info=True)
        return 1


# ═══════════════════════════════════════════════════════════════════════
# ENTERPRISE CLI — Click-based subcommand architecture
# ═══════════════════════════════════════════════════════════════════════

def _cli_main():
    """Click-based CLI entry point for the `elyan` command."""
    try:
        import click
    except ImportError:
        # Fallback to legacy argparse if Click is missing
        return main()

    @click.group(invoke_without_command=True)
    @click.option("--cli", is_flag=True, help="Start Gateway/CLI mode")
    @click.option("--onboard", is_flag=True, help="Start onboarding wizard")
    @click.option("--version", is_flag=True, help="Show version")
    @click.pass_context
    def cli(ctx, cli, onboard, version):
        """🧠 Elyan AGI Framework — Autonomous AI Agent"""
        if version:
            click.echo(f"Elyan AGI Framework v{VERSION}")
            ctx.exit(0)
        if onboard:
            from cli.onboard import start_onboarding
            ctx.exit(start_onboarding())
        if cli:
            ctx.exit(start_cli())
        if ctx.invoked_subcommand is None:
            ctx.exit(start_ui())

    # ─── gateway ───────────────────────────────────────────────────
    @cli.group()
    def gateway():
        """🌐 Gateway server management"""
        pass

    @gateway.command("start")
    @click.option("--port", default=GATEWAY_PORT, help="Port to listen on")
    @click.option("--daemon", is_flag=True, help="Run in background (daemonize)")
    def gateway_start(port, daemon):
        """Start the Elyan Gateway server."""
        os.environ["ELYAN_PORT"] = str(port)
        if daemon:
            click.echo(f"🚀 Starting Elyan Gateway on port {port} (daemon mode)...")
            import subprocess
            proc = subprocess.Popen(
                [sys.executable, __file__, "--cli"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True
            )
            click.echo(f"✅ Gateway started (PID: {proc.pid})")
        else:
            click.echo(f"🚀 Starting Elyan Gateway on port {port}...")
            sys.exit(start_cli())

    @gateway.command("restart")
    @click.option("--port", default=GATEWAY_PORT, help="Port to listen on")
    @click.option("--daemon", is_flag=True, help="Run in background")
    def gateway_restart(port, daemon):
        """Restart the Elyan Gateway server."""
        click.echo("🔄 Stopping existing gateway...")
        _kill_gateway(port)
        time.sleep(1)
        click.echo(f"🚀 Restarting gateway on port {port}...")
        os.environ["ELYAN_PORT"] = str(port)
        if daemon:
            import subprocess
            proc = subprocess.Popen(
                [sys.executable, __file__, "--cli"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True
            )
            click.echo(f"✅ Gateway restarted (PID: {proc.pid})")
        else:
            sys.exit(start_cli())

    @gateway.command("stop")
    @click.option("--port", default=GATEWAY_PORT)
    def gateway_stop(port):
        """Stop the running Gateway."""
        _kill_gateway(port)

    @gateway.command("health")
    @click.option("--port", default=GATEWAY_PORT)
    @click.option("--json", "as_json", is_flag=True, help="Output as JSON")
    def gateway_health(port, as_json):
        """Check gateway health status."""
        alive = find_existing_gateway(port)
        data = {
            "gateway": "online" if alive else "offline",
            "port": port,
            "version": VERSION,
            "timestamp": time.time()
        }
        if as_json:
            click.echo(json.dumps(data, indent=2))
        else:
            status = "🟢 ONLINE" if alive else "🔴 OFFLINE"
            click.echo(f"Gateway: {status} (port {port})")

    @gateway.command("status")
    @click.option("--port", default=GATEWAY_PORT)
    def gateway_status(port):
        """Show gateway process status."""
        alive = find_existing_gateway(port)
        if alive:
            import subprocess
            result = subprocess.run(
                ["lsof", "-ti", f":{port}"], capture_output=True, text=True
            )
            pids = result.stdout.strip() or "unknown"
            click.echo(f"🟢 Gateway RUNNING on port {port} (PID: {pids})")
        else:
            click.echo(f"🔴 Gateway NOT RUNNING on port {port}")

    # ─── health ────────────────────────────────────────────────────
    @cli.command("health")
    def health():
        """💊 Show Elyan system health (CPU, RAM, Disk)."""
        try:
            from core.genesis.self_diagnostic import diagnostics
            report = diagnostics.get_health_report()
            status_icon = {"healthy": "🟢", "degraded": "🟡", "critical": "🔴"}.get(report.status, "⚪")

            click.echo(f"\n{status_icon} Elyan Health Report")
            click.echo(f"{'─' * 40}")
            click.echo(f"  Status:     {report.status.upper()}")
            click.echo(f"  CPU:        {report.cpu_percent}%")
            click.echo(f"  RAM:        {report.ram_used_mb:.0f} MB / {report.ram_total_mb:.0f} MB")
            click.echo(f"  Disk Free:  {report.disk_free_gb:.1f} GB")
            click.echo(f"  Avg Resp:   {report.avg_response_ms:.0f} ms")
            click.echo(f"  Uptime:     {report.uptime_hours} hours")
            click.echo()
        except Exception as e:
            click.echo(f"❌ Health check failed: {e}")

    # ─── status ────────────────────────────────────────────────────
    @cli.command("status")
    def status():
        """📊 Show Elyan system status and module inventory."""
        click.echo(f"\n🧠 Elyan AGI Framework v{VERSION}")
        click.echo(f"{'═' * 50}")

        # Core modules check
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
            "Progress Tracker": "core.ux.progress_tracker",
            "Error Explainer": "core.ux.error_explainer",
            "Omni-Channel Gateway": "core.net.abstract_gateway",
            "Cloud Spawner": "core.net.cloud_spawner",
            "Bio Symbiosis": "core.genesis.bio_symbiosis",
            "Evo Compiler": "core.genesis.evo_compiler",
        }

        loaded = 0
        for name, module_path in modules.items():
            try:
                __import__(module_path)
                click.echo(f"  🟢 {name}")
                loaded += 1
            except Exception:
                click.echo(f"  🔴 {name} (not loadable)")

        click.echo(f"\n{'─' * 50}")
        click.echo(f"  Modules: {loaded}/{len(modules)} loaded")
        click.echo(f"  Platform: {sys.platform}")
        click.echo(f"  Python: {sys.version.split()[0]}")
        click.echo()

    # ─── skills ────────────────────────────────────────────────────
    @cli.command("skills")
    def skills():
        """🛠️ List all available Elyan skills and tools."""
        click.echo(f"\n🛠️ Elyan Skills & Capabilities")
        click.echo(f"{'═' * 50}")

        skill_categories = {
            "🧠 Intelligence": [
                "Chain-of-Thought Reasoning (4-phase structured thinking)",
                "Task Decomposition (dependency-ordered subtask graphs)",
                "Code Generation + Auto-Test + Self-Repair loop",
                "Deep Research with source cross-verification",
                "Adaptive Learning (user pattern profiling)",
            ],
            "🌐 Communication": [
                "Telegram Bot Integration",
                "Discord Gateway",
                "Slack Bolt Connector",
                "Omni-Channel Abstract Gateway",
            ],
            "🔒 Security": [
                "AES-256-GCM Secure Vault",
                "Prompt Injection Firewall",
                "Zero-Trust Code Sandbox",
                "GDPR/KVKK Compliance Engine",
            ],
            "⚡ Autonomy": [
                "Bio-Digital Symbiosis (screen context awareness)",
                "Pre-emptive Email/Calendar Execution",
                "Cloud Instance Spawning (DigitalOcean)",
                "Autonomous Microservice Builder",
                "C++ Native Compilation (Evo Compiler)",
            ],
            "🎯 Infrastructure": [
                "Multi-Model LLM Router (Gemini/Claude/GPT/Groq)",
                "Plugin Marketplace (~/.elyan/plugins/)",
                "Global Crash Protection (@never_crash)",
                "Rate Limiter & Quota Management",
                "Self-Diagnostic Health Monitor",
            ],
        }

        for category, items in skill_categories.items():
            click.echo(f"\n  {category}")
            for item in items:
                click.echo(f"    • {item}")

        click.echo(f"\n{'─' * 50}")
        click.echo(f"  Total: {sum(len(v) for v in skill_categories.values())} skills across {len(skill_categories)} categories")
        click.echo()

    # ─── logs ──────────────────────────────────────────────────────
    @cli.command("logs")
    @click.option("--tail", default=20, help="Number of log lines to show")
    @click.option("--level", default="all", help="Filter by level (info, warning, error)")
    def logs(tail, level):
        """📜 Show recent Elyan log entries."""
        log_dir = Path.home() / ".elyan" / "logs"
        if not log_dir.exists():
            # Try project-local logs
            log_dir = project_root / "logs"

        if not log_dir.exists():
            click.echo("📜 No log directory found. Checking audit trail...")
            audit_dir = Path.home() / ".elyan" / "audit"
            if audit_dir.exists():
                log_files = sorted(audit_dir.glob("audit_*.jsonl"), reverse=True)
                if log_files:
                    lines = log_files[0].read_text(encoding="utf-8").strip().split("\n")
                    click.echo(f"\n📜 Last {min(tail, len(lines))} audit entries:")
                    for line in lines[-tail:]:
                        try:
                            entry = json.loads(line)
                            ts = time.strftime("%H:%M:%S", time.localtime(entry["ts"]))
                            click.echo(f"  [{ts}] {entry['action']} → {entry['target']} ({entry['result']})")
                        except:
                            click.echo(f"  {line}")
                    return
            click.echo("No logs found.")
            return

        log_files = sorted(log_dir.glob("*.log"), reverse=True)
        if not log_files:
            click.echo("📜 No log files found.")
            return

        latest_log = log_files[0]
        lines = latest_log.read_text(encoding="utf-8").strip().split("\n")

        if level != "all":
            lines = [l for l in lines if level.upper() in l.upper()]

        click.echo(f"\n📜 Last {min(tail, len(lines))} log entries ({latest_log.name}):")
        for line in lines[-tail:]:
            click.echo(f"  {line}")
        click.echo()

    # ─── vault ─────────────────────────────────────────────────────
    @cli.group()
    def vault():
        """🔐 Manage the encrypted secret vault"""
        pass

    @vault.command("list")
    def vault_list():
        """List stored secret keys."""
        from core.security.secure_vault import vault as sv
        sv.unlock()
        keys = sv.list_keys()
        if keys:
            click.echo(f"\n🔐 Vault Keys ({len(keys)}):")
            for k in keys:
                click.echo(f"  • {k}")
        else:
            click.echo("🔐 Vault is empty.")

    @vault.command("set")
    @click.argument("key")
    @click.argument("value")
    def vault_set(key, value):
        """Store a secret: elyan vault set API_KEY sk-xxx"""
        from core.security.secure_vault import vault as sv
        sv.unlock()
        sv.store_secret(key, value)
        click.echo(f"✅ Secret '{key}' stored.")

    @vault.command("get")
    @click.argument("key")
    def vault_get(key):
        """Retrieve a secret."""
        from core.security.secure_vault import vault as sv
        sv.unlock()
        val = sv.get_secret(key)
        if val:
            click.echo(f"🔑 {key} = {val}")
        else:
            click.echo(f"❌ Key '{key}' not found.")

    # ─── plugins ───────────────────────────────────────────────────
    @cli.command("plugins")
    def plugins_cmd():
        """🧩 List installed plugins."""
        from core.plugins.plugin_manager import plugins as pm
        pm.load_all()
        plugin_list = pm.list_plugins()
        if plugin_list:
            click.echo(f"\n🧩 Installed Plugins ({len(plugin_list)}):")
            for p in plugin_list:
                click.echo(f"  • {p['name']} v{p['version']} by {p['author']} ({len(p['tools'])} tools)")
        else:
            click.echo("🧩 No plugins installed. Add plugins to ~/.elyan/plugins/")

    # ─── helper ────────────────────────────────────────────────────
    def _kill_gateway(port):
        """Find and kill the process on the given port."""
        import subprocess
        try:
            result = subprocess.run(
                ["lsof", "-ti", f":{port}"], capture_output=True, text=True
            )
            if result.stdout.strip():
                pids = result.stdout.strip().split("\n")
                for pid in pids:
                    subprocess.run(["kill", "-9", pid.strip()], capture_output=True)
                click.echo(f"🛑 Killed {len(pids)} process(es) on port {port}")
            else:
                click.echo(f"ℹ️ No process found on port {port}")
        except Exception as e:
            click.echo(f"⚠️ Could not kill gateway: {e}")

    # Run the CLI
    cli(standalone_mode=False)


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="Elyan Smart Assistant")
    parser.add_argument("--cli", action="store_true", help="Start in Gateway/CLI mode")
    parser.add_argument("--onboard", action="store_true", help="Start onboarding wizard")
    parser.add_argument("--version", action="store_true", help="Show version and exit")

    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    if args.version:
        print(f"Elyan v{VERSION}")
        return 0

    # --onboard takes priority over --cli
    if args.onboard:
        from cli.onboard import start_onboarding
        return start_onboarding()

    if args.cli:
        return start_cli()
    else:
        return start_ui()


if __name__ == "__main__":
    sys.exit(main())
