"""main_app.py — backward-compat shim (Sprint J)"""

from ui.clean_main_app import CleanMainWindow as MainWindow, main  # noqa: F401

__all__ = ["MainWindow", "main"]
