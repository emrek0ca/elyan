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
import socket
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
    """BUG-FUNC-009: Check if port is available before starting gateway."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
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
    # BUG-FUNC-009: Check port availability before starting
    if not check_port_available(GATEWAY_PORT):
        if find_existing_gateway(GATEWAY_PORT):
            logger.error(
                f"Port {GATEWAY_PORT} is already in use by another Elyan instance. "
                f"Run 'elyan gateway status' to check, or set ELYAN_PORT env var."
            )
        else:
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
