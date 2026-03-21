from __future__ import annotations

import importlib

from core.lean.project import build_workflow_bundle, detect_project_root


def test_detect_lean_project_root(tmp_path):
    root = tmp_path / "lean-project"
    nested = root / "src" / "Theorem"
    nested.mkdir(parents=True)
    (root / "lakefile.lean").write_text("import Lake\n", encoding="utf-8")

    assert detect_project_root(nested) == root


def test_build_lean_workflow_bundle(tmp_path, monkeypatch):
    lean_project = importlib.import_module("core.lean.project")
    state_root = tmp_path / ".elyan" / "lean"
    monkeypatch.setattr(lean_project, "STATE_ROOT", state_root, raising=False)
    monkeypatch.setattr(lean_project, "REGISTRY_FILE", state_root / "projects.json", raising=False)
    monkeypatch.setattr(lean_project, "SESSIONS_FILE", state_root / "sessions.json", raising=False)

    root = tmp_path / "mathlib-project"
    root.mkdir()
    project = lean_project.register_project(root, name="Mathlib Project", create_manifest=True)
    bundle = build_workflow_bundle("prove", project=project, goal="prove theorem foo", target="Foo.lean")

    assert bundle["id"] == "lean_prove"
    assert "lean_workflow" in bundle["required_tools"]
    assert "lake build" in bundle["command"] or "lake env lean" in bundle["command"]
    assert bundle["project_root"] == str(root)
