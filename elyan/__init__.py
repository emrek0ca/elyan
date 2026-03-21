"""Canonical Elyan package scaffold."""

from core.version import APP_VERSION, __version__

__all__ = ["APP_VERSION", "__version__", "bootstrap_workspace", "ensure_runtime_dirs"]


def __getattr__(name: str):
    if name in {"bootstrap_workspace", "ensure_runtime_dirs"}:
        from . import bootstrap as _bootstrap

        return getattr(_bootstrap, name)
    raise AttributeError(name)
