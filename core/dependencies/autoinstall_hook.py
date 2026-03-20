from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


_HOOK_MODULE_NAME = "elyan_repo_autoinstall_hook"
_HOOK_PATH = Path(__file__).resolve().parents[2] / "sitecustomize.py"


def activate() -> None:
    if _HOOK_MODULE_NAME in sys.modules:
        return
    if not _HOOK_PATH.exists():
        return
    spec = importlib.util.spec_from_file_location(_HOOK_MODULE_NAME, str(_HOOK_PATH))
    if spec is None or spec.loader is None:
        return
    module = importlib.util.module_from_spec(spec)
    sys.modules[_HOOK_MODULE_NAME] = module
    spec.loader.exec_module(module)


activate()

