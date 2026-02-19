"""main_window.py — backward-compat shim (Sprint J)"""

from ui.clean_main_app import CleanMainWindow as MainWindow  # noqa: F401


def check_pyqt6() -> bool:
    """Return True if PyQt6 is importable."""
    try:
        import PyQt6  # noqa: F401
        return True
    except ImportError:
        return False


__all__ = ["MainWindow", "check_pyqt6"]
