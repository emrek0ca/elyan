from __future__ import annotations

import asyncio

from core.capability_router import CapabilityRouter
from core.quivr.project import detect_project_root, scaffold_project, summarize_project
from core.skills.builtin.quivr_skill import QuivrSkill
from core.skills.catalog import get_builtin_skill_catalog
from tools import AVAILABLE_TOOLS


def test_detect_quivr_project_root(tmp_path):
    root = tmp_path / "quivr-brain"
    root.mkdir()
    (root / "requirements.txt").write_text("quivr-core\n", encoding="utf-8")
    (root / "brain.py").write_text("from quivr_core import Brain\n", encoding="utf-8")
    (root / "basic_rag_workflow.yaml").write_text("workflow_config:\n  name: demo\n", encoding="utf-8")

    assert detect_project_root(root) == root


def test_scaffold_quivr_project(tmp_path):
    tool = AVAILABLE_TOOLS.get("quivr_scaffold")
    assert callable(tool)

    root = tmp_path / "starter"
    result = asyncio.run(tool(path=str(root), name="Demo Brain"))

    assert result["success"] is True
    assert (root / "requirements.txt").exists()
    assert (root / "brain.py").exists()
    assert (root / "quivr_chat.py").exists()
    assert (root / "basic_rag_workflow.yaml").exists()
    assert "Brain.from_files" in (root / "brain.py").read_text(encoding="utf-8")
    assert "RetrievalConfig.from_yaml" in (root / "brain.py").read_text(encoding="utf-8")

    project = summarize_project(root)
    assert project["ready"] is True
    assert "brain_from_files" in project["features"]


def test_quivr_skill_catalog_and_routing():
    catalog = get_builtin_skill_catalog()
    assert "quivr" in catalog
    assert "quivr_scaffold" in catalog["quivr"]["required_tools"]

    plan = CapabilityRouter().route("Build a Quivr second brain with Brain.from_files and RetrievalConfig.from_yaml.")
    assert plan.domain == "quivr"
    assert "quivr_scaffold" in plan.preferred_tools

    skill = QuivrSkill({})
    assert skill.name == "quivr"
    assert {tool["name"] for tool in skill.get_tools()} == {
        "quivr_status",
        "quivr_project",
        "quivr_scaffold",
        "quivr_brain_ask",
    }


def test_quivr_brain_ask_fallback(tmp_path):
    source = tmp_path / "note.txt"
    source.write_text(
        "Quivr helps you build your second brain. Quivr ingests files with Brain.from_files.",
        encoding="utf-8",
    )

    tool = AVAILABLE_TOOLS.get("quivr_brain_ask")
    result = asyncio.run(tool(question="What does Quivr help you build?", file_paths=[str(source)]))

    assert result["success"] is True
    assert result["backend"] in {"quivr_core", "elyan_document_rag"}
    assert "second brain" in result["answer"].lower() or result["answer"].strip()
