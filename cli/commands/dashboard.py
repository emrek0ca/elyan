from __future__ import annotations

from cli.commands.desktop import open_desktop


def open_dashboard(port: int | None = None, no_browser: bool = False, ops: bool = False):
    """Backward-compatible wrapper. Web dashboard removed; opens desktop app."""
    _ = (port, ops)
    if no_browser:
        return 0
    print("ℹ️  Web dashboard kaldırıldı. Elyan Desktop açılıyor...")
    return open_desktop(detached=True)
