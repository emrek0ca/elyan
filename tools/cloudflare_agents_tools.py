from __future__ import annotations

from pathlib import Path
from typing import Any

from core.cloudflare_agents.project import (
    build_cloudflare_agents_bundle,
    detect_project_root,
    resolve_project_root,
    scaffold_project,
    summarize_project,
)
from core.registry import tool


def _cloudflare_root(path: str = ""):
    root = resolve_project_root(path) if path else None
    if root:
        return root
    return detect_project_root(path)


def _project_for(path: str) -> dict[str, Any]:
    root = _cloudflare_root(path)
    if not root:
        return {}
    return summarize_project(root)


@tool("cloudflare_agents_status", "Inspect a Cloudflare Agents starter or existing worker app.")
async def cloudflare_agents_status(path: str = "") -> dict[str, Any]:
    project = _project_for(path)
    if not project:
        return {
            "success": False,
            "status": "missing",
            "error": "No Cloudflare Agents project found. Use cloudflare_agents_scaffold first.",
            "project": {},
        }
    return {
        "success": True,
        "status": "success",
        "project": project,
        "bundle": build_cloudflare_agents_bundle("starter", project=project),
    }


@tool("cloudflare_agents_project", "Inspect, prepare, or scaffold a Cloudflare Agents project.")
async def cloudflare_agents_project(
    action: str = "status",
    path: str = "",
    name: str = "",
    include_chat: bool = True,
    include_workflows: bool = True,
    include_mcp: bool = True,
    force: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    mode = str(action or "status").strip().lower() or "status"
    if mode in {"status", "inspect"}:
        return await cloudflare_agents_status(path=path)

    if mode in {"bundle", "workflow"}:
        project = _project_for(path)
        if not project:
            return {
                "success": False,
                "status": "missing",
                "error": "No Cloudflare Agents project found.",
                "project": {},
            }
        return {
            "success": True,
            "status": "success",
            "project": project,
            "bundle": build_cloudflare_agents_bundle(mode, project=project, goal=name),
        }

    if mode in {"init", "create", "scaffold"}:
        root = _cloudflare_root(path) or _normalize_candidate(path)
        if root is None:
            return {
                "success": False,
                "status": "missing",
                "error": "Project path required.",
                "project": {},
            }
        return await cloudflare_agents_scaffold(
            path=str(root),
            name=name or root.name,
            include_chat=include_chat,
            include_workflows=include_workflows,
            include_mcp=include_mcp,
            force=force,
            dry_run=dry_run,
        )

    return {
        "success": False,
        "status": "unsupported",
        "error": f"Unsupported Cloudflare Agents action: {mode}",
    }


def _normalize_candidate(path: str) -> Path | None:
    raw = str(path or "").strip()
    if not raw:
        return None
    try:
        return Path(raw).expanduser().resolve()
    except Exception:
        return None


@tool("cloudflare_agents_scaffold", "Scaffold a Cloudflare Agents starter app.")
async def cloudflare_agents_scaffold(
    path: str = "",
    name: str = "",
    include_chat: bool = True,
    include_workflows: bool = True,
    include_mcp: bool = True,
    force: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    root = _cloudflare_root(path) or _normalize_candidate(path)
    if root is None:
        return {
            "success": False,
            "status": "missing",
            "error": "Project path required.",
        }
    result = scaffold_project(
        root,
        name=name or root.name,
        include_chat=include_chat,
        include_workflows=include_workflows,
        include_mcp=include_mcp,
        force=force,
        dry_run=dry_run,
    )
    result["bundle"] = build_cloudflare_agents_bundle("starter", project=result.get("project") or {}, goal=name)
    return result


@tool("cloudflare_agents_workflow", "Build a Cloudflare Agents starter or deployment workflow bundle.")
async def cloudflare_agents_workflow(
    action: str = "starter",
    path: str = "",
    goal: str = "",
    target: str = "",
    backend: str = "auto",
) -> dict[str, Any]:
    project = _project_for(path)
    if not project:
        return {
            "success": False,
            "status": "missing",
            "error": "No Cloudflare Agents project found.",
            "project": {},
        }
    bundle = build_cloudflare_agents_bundle(action, project=project, goal=goal, target=target, backend=backend)
    return {
        "success": True,
        "status": "success",
        "project": project,
        "workflow": bundle,
        "next_steps": [
            "Review the generated worker and chat files.",
            "Install dependencies and run wrangler dev.",
            "Use the chat agent for persistent conversation and tool-driven interactions.",
        ],
    }
