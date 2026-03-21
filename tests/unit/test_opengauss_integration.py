from __future__ import annotations

import asyncio
from types import SimpleNamespace

from core.capability_router import CapabilityRouter
from core.opengauss.project import detect_project_root, query_project, scaffold_project, summarize_project
from core.skills.builtin.opengauss_skill import OpenGaussSkill
from core.skills.catalog import get_builtin_skill_catalog
from tools import AVAILABLE_TOOLS


def test_detect_opengauss_project_root(tmp_path):
    root = tmp_path / "opengauss-db"
    root.mkdir()
    (root / "docker-compose.yml").write_text(
        "services:\n  opengauss:\n    image: opengauss/opengauss-server:latest\n",
        encoding="utf-8",
    )
    (root / "schema").mkdir()
    (root / "schema" / "init.sql").write_text("SELECT 1;\n", encoding="utf-8")

    assert detect_project_root(root / "schema") == root


def test_scaffold_opengauss_project(tmp_path):
    tool = AVAILABLE_TOOLS.get("opengauss_scaffold")
    assert callable(tool)

    root = tmp_path / "starter"
    result = asyncio.run(tool(path=str(root), name="Demo DB"))

    assert result["success"] is True
    assert (root / "docker-compose.yml").exists()
    assert (root / ".env.example").exists()
    assert (root / "schema" / "init.sql").exists()
    assert (root / "scripts" / "query.sh").exists()
    assert "gsql" in (root / "scripts" / "query.sh").read_text(encoding="utf-8")

    project = summarize_project(root)
    assert project["ready"] is True
    assert "docker_compose" in project["features"]
    assert "schema_sql" in project["features"]


def test_opengauss_skill_catalog_and_routing():
    catalog = get_builtin_skill_catalog()
    assert "opengauss" in catalog
    assert "opengauss_query" in catalog["opengauss"]["required_tools"]

    plan = CapabilityRouter().route("OpenGauss database schema migration ve SQL query workflow kur.")
    assert plan.domain == "opengauss"
    assert plan.workflow_id == "opengauss_database_workflow"
    assert plan.primary_action == "opengauss_scaffold"

    skill = OpenGaussSkill({})
    assert skill.name == "opengauss"
    assert {tool["name"] for tool in skill.get_tools()} == {
        "opengauss_status",
        "opengauss_project",
        "opengauss_scaffold",
        "opengauss_query",
        "opengauss_workflow",
    }


def test_opengauss_query_plan(tmp_path):
    root = tmp_path / "demo"
    scaffold_project(root, name="Demo DB")

    tool = AVAILABLE_TOOLS.get("opengauss_query")
    result = asyncio.run(tool(sql="SELECT 1;", path=str(root)))

    assert result["success"] is True
    assert "scripts/query.sh" in result["command"]
    assert result["data"]["database"] == "appdb"


def test_opengauss_query_execute_runs_safe_sql(monkeypatch, tmp_path):
    root = tmp_path / "demo-exec"
    scaffold_project(root, name="Demo DB")

    calls = {}

    def fake_run(cmd, cwd=None, capture_output=None, text=None, timeout=None, check=None):
        calls["cmd"] = cmd
        calls["cwd"] = cwd
        calls["timeout"] = timeout
        return SimpleNamespace(returncode=0, stdout="ok\n", stderr="")

    monkeypatch.setattr("core.opengauss.project.subprocess.run", fake_run)

    result = query_project(sql="SELECT 1;", path=str(root), execute=True, timeout=7)

    assert result["success"] is True
    assert result["status"] == "success"
    assert result["execution"]["stdout"] == "ok\n"
    assert calls["cwd"] == str(root)
    assert calls["timeout"] == 7


def test_opengauss_query_execute_blocks_mutation(monkeypatch, tmp_path):
    root = tmp_path / "demo-block"
    scaffold_project(root, name="Demo DB")

    called = {"count": 0}

    def fake_run(*args, **kwargs):
        called["count"] += 1
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("core.opengauss.project.subprocess.run", fake_run)

    result = query_project(sql="DROP TABLE demo_events;", path=str(root), execute=True)

    assert result["success"] is False
    assert result["status"] == "blocked"
    assert result["destructive"] is True
    assert "allow_mutation=True" in result["error"]
    assert called["count"] == 0
