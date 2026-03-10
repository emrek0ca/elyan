from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_inventory_module():
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "dead_code_inventory.py"
    spec = importlib.util.spec_from_file_location("dead_code_inventory", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_build_inventory_uses_focused_scope_and_excludes_legacy_bot(tmp_path: Path):
    mod = _load_inventory_module()

    (tmp_path / "core").mkdir(parents=True)
    (tmp_path / "bot").mkdir(parents=True)
    (tmp_path / "core" / "a.py").write_text("def alive():\n    return 1\n", encoding="utf-8")
    (tmp_path / "bot" / "legacy.py").write_text("def noisy():\n    return 2\n", encoding="utf-8")

    inv = mod.build_inventory(
        tmp_path,
        include_dirs=["core", "bot"],
        exclude_dirs={"bot"},
        include_tests=False,
    )

    assert inv["summary"]["python_files_scanned"] == 1
    assert inv["scope"]["include_dirs"] == ["core", "bot"]
    assert "bot" in inv["scope"]["exclude_dirs"]
    assert all(not row["path"].startswith("bot/") for row in inv["dead_code_candidates"])
    assert all(not row["path"].startswith("bot/") for row in inv["unused_imports"])


def test_build_inventory_marks_unused_import_and_quick_wins(tmp_path: Path):
    mod = _load_inventory_module()

    (tmp_path / "core").mkdir(parents=True)
    (tmp_path / "core" / "mod.py").write_text(
        "import os\n"
        "import json\n\n"
        "def used():\n"
        "    return json.dumps({'ok': True})\n\n"
        "def orphan():\n"
        "    return 42\n",
        encoding="utf-8",
    )

    inv = mod.build_inventory(tmp_path, include_dirs=["core"], exclude_dirs=set(), include_tests=False)
    unused_names = {row["name"] for row in inv["unused_imports"]}
    dead_names = {row["name"] for row in inv["dead_code_candidates"]}
    quick_dead = {row["name"] for row in inv["quick_wins"]["dead_code_candidates"]}

    assert "os" in unused_names
    assert "orphan" in dead_names
    assert "orphan" in quick_dead
