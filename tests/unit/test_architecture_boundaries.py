from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path("/Users/emrekoca/Desktop/bot")
CORE_DIR = ROOT / "core"
FORBIDDEN_IMPORT_PREFIXES = ("ui", "apps", "plugins")
ALLOWLIST_MODULES = {
    "uiautomation",
}


def _iter_python_files(base: Path):
    for path in base.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        yield path


def _import_roots(path: Path) -> set[str]:
    roots: set[str] = set()
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def test_core_python_modules_do_not_import_ui_apps_or_plugins():
    violations: list[str] = []

    for path in _iter_python_files(CORE_DIR):
        roots = _import_roots(path)
        for root in roots:
            if root in ALLOWLIST_MODULES:
                continue
            if root in FORBIDDEN_IMPORT_PREFIXES:
                violations.append(f"{path.relative_to(ROOT)} imports forbidden root '{root}'")

    assert violations == []


def test_protocol_event_module_stays_free_of_ui_runtime_dependencies():
    roots = _import_roots(ROOT / "core/protocol/events.py")
    assert roots.isdisjoint({"ui", "apps", "plugins"})


def test_event_bus_module_stays_free_of_ui_runtime_dependencies():
    roots = _import_roots(ROOT / "core/event_system.py")
    assert roots.isdisjoint({"ui", "apps", "plugins"})
