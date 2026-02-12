#!/usr/bin/env python3
"""
Wiqo entrypoint.

Usage:
- python main.py         -> Desktop UI (tray/wizard)
- python main.py --cli   -> Telegram polling mode
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from config.settings import TELEGRAM_TOKEN
from config.settings_manager import SettingsPanel
from utils.logger import get_logger

logger = get_logger("main")
LAUNCHER_VERSION = "24.0.0"


def _resolve_telegram_token() -> str:
    """Resolve Telegram token from env/settings."""
    if TELEGRAM_TOKEN:
        return TELEGRAM_TOKEN
    try:
        return str(SettingsPanel().get("telegram_token", "") or "")
    except Exception:
        return ""


def run_with_ui() -> int:
    """Start desktop UI mode."""
    try:
        logger.info(f"Wiqo Launcher v{LAUNCHER_VERSION} starting from {__file__}")
        from ui.clean_main_app import main as clean_main
        return int(clean_main() or 0)
    except Exception as exc:
        logger.error(f"UI başlatma hatası: {exc}")
        return 1


def run_with_cli() -> int:
    """Start Telegram CLI mode."""
    token = _resolve_telegram_token()
    if not token:
        logger.error("Telegram token bulunamadı. .env veya settings.json üzerinden ayarlayın.")
        return 1

    try:
        from telegram.ext import ApplicationBuilder
        from core.agent import Agent
        from handlers.telegram_handler import setup_handlers
    except Exception as exc:
        logger.error(f"CLI bağımlılıkları yüklenemedi: {exc}")
        return 1

    agent = Agent()
    init_ok = asyncio.run(agent.initialize())
    if not init_ok:
        logger.error("Agent başlatılamadı.")
        return 1

    app = ApplicationBuilder().token(token).build()
    setup_handlers(app, agent)

    logger.info("Telegram CLI modu aktif. Durdurmak için Ctrl+C.")
    try:
        app.run_polling(drop_pending_updates=True)
    except KeyboardInterrupt:
        logger.info("CLI modu durduruldu.")
    except Exception as exc:
        logger.error(f"Telegram polling hatası: {exc}")
        return 1
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Wiqo launcher")
    parser.add_argument(
        "--cli",
        action="store_true",
        help="Telegram polling mode (UI açılmaz)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if args.cli:
        return run_with_cli()
    return run_with_ui()


if __name__ == "__main__":
    raise SystemExit(main())
