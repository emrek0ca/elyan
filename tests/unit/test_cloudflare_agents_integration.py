from __future__ import annotations

import asyncio

from core.capability_router import CapabilityRouter
from core.cloudflare_agents.project import detect_project_root, scaffold_project, summarize_project
from core.skills.builtin.cloudflare_agents_skill import CloudflareAgentsSkill
from core.skills.catalog import get_builtin_skill_catalog
from tools import AVAILABLE_TOOLS


def test_detect_cloudflare_agents_project_root(tmp_path):
    root = tmp_path / "cloudflare-agents"
    root.mkdir()
    (root / "wrangler.jsonc").write_text('{"name":"demo","main":"src/server.ts","compatibility_date":"2026-03-21"}\n', encoding="utf-8")
    (root / "src").mkdir()
    (root / "src" / "server.ts").write_text("export default {};\n", encoding="utf-8")

    assert detect_project_root(root / "src") == root


def test_scaffold_cloudflare_agents_project(tmp_path):
    tool = AVAILABLE_TOOLS.get("cloudflare_agents_scaffold")
    assert callable(tool)

    root = tmp_path / "starter"
    result = asyncio.run(tool(path=str(root), name="Demo Agent"))

    assert result["success"] is True
    assert (root / "wrangler.jsonc").exists()
    assert (root / "src" / "server.ts").exists()
    assert (root / "src" / "client.tsx").exists()
    assert "routeAgentRequest" in (root / "src" / "server.ts").read_text(encoding="utf-8")
    assert "useAgent" in (root / "src" / "client.tsx").read_text(encoding="utf-8")

    project = summarize_project(root)
    assert project["ready"] is True
    assert "react_sync" in project["features"]


def test_cloudflare_agents_skill_catalog_and_routing():
    catalog = get_builtin_skill_catalog()
    assert "cloudflare_agents" in catalog
    assert "cloudflare_agents_scaffold" in catalog["cloudflare_agents"]["required_tools"]

    plan = CapabilityRouter().route("Build a Cloudflare Agents app with routeAgentRequest and useAgentChat.")
    assert plan.domain == "cloudflare_agents"
    assert "cloudflare_agents_scaffold" in plan.preferred_tools

    skill = CloudflareAgentsSkill({})
    assert skill.name == "cloudflare_agents"
    assert {tool["name"] for tool in skill.get_tools()} == {
        "cloudflare_agents_status",
        "cloudflare_agents_project",
        "cloudflare_agents_scaffold",
        "cloudflare_agents_workflow",
    }
