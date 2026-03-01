from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from .unified import memory
from .episodic import episodic_memory
from .context_optimizer import context_optimizer

Memory = None
MemoryManager = None

# Backward-compat: tests and legacy modules still import `Memory`/`MemoryManager`
# from `core.memory`. Since `core/memory/` is now a package, explicitly load
# classes from legacy `core/memory.py`.
try:
    _legacy_path = Path(__file__).resolve().parent.parent / "memory.py"
    if _legacy_path.exists():
        _spec = importlib.util.spec_from_file_location("core._memory_legacy", str(_legacy_path))
        if _spec and _spec.loader:
            _mod = importlib.util.module_from_spec(_spec)
            sys.modules.setdefault("core._memory_legacy", _mod)
            _spec.loader.exec_module(_mod)
            Memory = getattr(_mod, "Memory", None)
            MemoryManager = getattr(_mod, "MemoryManager", None)
except Exception:
    Memory = None
    MemoryManager = None


def get_memory():
    """Legacy shim for components expecting a get_memory() accessor."""
    return memory


__all__ = [
    "memory",
    "episodic_memory",
    "context_optimizer",
    "get_memory",
    "Memory",
    "MemoryManager",
]
