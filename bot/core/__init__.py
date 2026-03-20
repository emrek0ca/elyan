"""Elyan Core Package."""

from core.dependencies.autoinstall_hook import activate as _activate_autoinstall_hook

_activate_autoinstall_hook()

# Keep imports otherwise empty to avoid circular dependencies during boot.
