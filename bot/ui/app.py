"""Desktop Application Controller - Main entry point for UI"""

import asyncio
import threading
import sys
import os
from typing import Any, Callable
from pathlib import Path

# Setup Qt environment before any Qt imports
def setup_qt_environment():
    """Setup Qt platform plugin path for macOS"""
    try:
        import PyQt6
        qt_plugins_path = Path(PyQt6.__path__[0]) / "Qt6" / "plugins"
        if qt_plugins_path.exists():
            os.environ['QT_QPA_PLATFORM_PLUGIN_PATH'] = str(qt_plugins_path)
    except Exception:
        pass

setup_qt_environment()
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.logger import get_logger
from ui.settings_panel import SettingsPanel
from ui.qr_generator import QRGenerator

logger = get_logger("ui.app")

# Global app instance for bot connection
_current_app_instance = None

def get_current_app():
    """Get the current running app instance"""
    return _current_app_instance


class DesktopApp:
    """Main desktop application controller"""

    def __init__(self, bot_username: str = None):
        global _current_app_instance
        self.settings = SettingsPanel()
        self.qr_generator = QRGenerator(bot_username)
        self._main_window = None
        self._menubar_app = None
        self._bot_thread = None
        self._running = False

        # Set as current app instance
        _current_app_instance = self

        # Try to get bot username from settings
        if not bot_username:
            bot_username = self.settings.get("bot_username", "")
        self.bot_username = bot_username

    def start_with_ui(self, run_bot_callback: Callable = None):
        """Start the application with desktop UI

        Args:
            run_bot_callback: Callback to start the Telegram bot in background
        """
        logger.info("Starting desktop application...")

        # Start bot in background thread if callback provided
        if run_bot_callback:
            self._bot_thread = threading.Thread(
                target=self._run_bot_thread,
                args=(run_bot_callback,),
                daemon=True
            )
            self._bot_thread.start()

        # Try to run with PyQt6 main window
        try:
            from .main_window import MainWindow, check_pyqt6

            if check_pyqt6():
                self._main_window = MainWindow(
                    settings=self.settings,
                    qr_generator=self.qr_generator,
                    bot_username=self.bot_username
                )
                self._running = True
                return self._main_window.run()
            else:
                logger.warning("PyQt6 not available, falling back to menubar only")
                return self._run_menubar_only()

        except ImportError as e:
            logger.warning(f"PyQt6 import error: {e}")
            return self._run_menubar_only()

    def start_menubar_only(self, run_bot_callback: Callable = None):
        """Start only the menubar application (lightweight mode)"""
        logger.info("Starting menubar-only mode...")

        if run_bot_callback:
            self._bot_thread = threading.Thread(
                target=self._run_bot_thread,
                args=(run_bot_callback,),
                daemon=True
            )
            self._bot_thread.start()

        return self._run_menubar_only()

    def _run_menubar_only(self):
        """Run the menubar application"""
        try:
            from .menubar_app import MenubarApp, check_rumps

            if check_rumps():
                self._menubar_app = MenubarApp(
                    settings=self.settings,
                    on_quit=self._on_quit
                )
                self._running = True
                self._menubar_app.run()
                return 0
            else:
                logger.error("rumps not available for menubar")
                return 1

        except ImportError as e:
            logger.error(f"rumps import error: {e}")
            return 1

    def _run_bot_thread(self, callback: Callable):
        """Run the bot in a background thread"""
        try:
            # Create new event loop for the thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(callback())
        except Exception as e:
            logger.error(f"Bot thread error: {e}")

    def _on_quit(self):
        """Handle application quit"""
        logger.info("Application quitting...")
        self._running = False

    def update_status(self, status: str):
        """Update the status in UI components"""
        if self._menubar_app:
            self._menubar_app.update_status(status)

    def show_notification(self, title: str, message: str):
        """Show a system notification"""
        try:
            import rumps
            rumps.notification(title=title, subtitle="", message=message)
        except ImportError:
            # Fallback to macOS notification
            import subprocess
            script = f'display notification "{message}" with title "{title}"'
            subprocess.run(["osascript", "-e", script], capture_output=True)

    def get_qr_image(self, output_path: str = None) -> dict[str, Any]:
        """Generate QR code for Telegram connection"""
        return self.qr_generator.generate_qr_image(output_path)

    def validate_connection_token(self, token: str) -> bool:
        """Validate a connection token from QR scan"""
        is_valid = self.qr_generator.is_token_valid(token)
        if is_valid:
            self.qr_generator.invalidate_token()
            self.update_status("connected")
        return is_valid

    def add_to_history(self, user_message: str, bot_response: str):
        """Add a message exchange to chat history"""
        if self._main_window and hasattr(self._main_window, 'add_to_history'):
            self._main_window.add_to_history(user_message, bot_response)

    @property
    def is_running(self) -> bool:
        return self._running


def run_desktop_app(bot_username: str = None, run_bot: Callable = None) -> int:
    """Convenience function to run the desktop app

    Args:
        bot_username: Telegram bot username (without @)
        run_bot: Async function to run the Telegram bot

    Returns:
        Exit code
    """
    app = DesktopApp(bot_username)
    return app.start_with_ui(run_bot)


def run_menubar_app(run_bot: Callable = None) -> int:
    """Convenience function to run menubar-only mode

    Args:
        run_bot: Async function to run the Telegram bot

    Returns:
        Exit code
    """
    app = DesktopApp()
    return app.start_menubar_only(run_bot)
