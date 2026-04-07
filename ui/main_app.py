"""Legacy desktop compatibility shim.

Canonical desktop entrypoint is apps/desktop via the React/Tauri shell.
"""

from ui.clean_main_app import CleanMainWindow as MainWindow, main  # noqa: F401

__all__ = ["MainWindow", "main"]
