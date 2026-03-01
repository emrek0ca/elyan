"""
Task engine package exports with legacy compatibility bridge.

This repository contains both:
- package: core/task_engine/
- legacy module: core/task_engine.py

Because Python resolves the package path first, code that imports
`core.task_engine` may no longer reach the legacy engine module.
We bridge that here by loading the legacy module lazily.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Optional

from ._state import TaskResult, TaskDefinition
from ._constants import _NON_TOOL_ACTIONS, _EXPLICIT_APPROVAL_ACTIONS
from tools import AVAILABLE_TOOLS

_legacy_module: Optional[ModuleType] = None


def _load_legacy_module() -> ModuleType:
    global _legacy_module
    if _legacy_module is not None:
        return _legacy_module

    legacy_path = Path(__file__).resolve().parent.parent / "task_engine.py"
    spec = importlib.util.spec_from_file_location("core._task_engine_legacy", legacy_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Legacy task engine module load failed: {legacy_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _legacy_module = module
    return module


def get_task_engine():
    module = _load_legacy_module()
    return module.get_task_engine()


def TaskEngine():
    module = _load_legacy_module()
    return module.TaskEngine()


__all__ = [
    "TaskResult",
    "TaskDefinition",
    "_NON_TOOL_ACTIONS",
    "_EXPLICIT_APPROVAL_ACTIONS",
    "AVAILABLE_TOOLS",
    "get_task_engine",
    "TaskEngine",
]
