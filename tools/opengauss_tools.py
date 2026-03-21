from __future__ import annotations

from pathlib import Path
from typing import Any

from core.opengauss.project import (
    build_opengauss_bundle,
    detect_project_root,
    query_project,
    resolve_project_root,
    scaffold_project,
    summarize_project,
)
from core.registry import tool


def _opengauss_root(path: str = ""):
    root = resolve_project_root(path) if path else None
    if root:
        return root
    return detect_project_root(path)


def _project_for(path: str) -> dict[str, Any]:
    root = _opengauss_root(path)
    if not root:
        return {}
    return summarize_project(root)


def _normalize_candidate(path: str) -> Path | None:
    raw = str(path or "").strip()
    if not raw:
        return None
    try:
        return Path(raw).expanduser().resolve()
    except Exception:
        return None


@tool("opengauss_status", "Inspect an OpenGauss project or database workspace.")
async def opengauss_status(path: str = "") -> dict[str, Any]:
    project = _project_for(path)
    if not project:
        return {
            "success": False,
            "status": "missing",
            "error": "No OpenGauss project found. Use opengauss_scaffold first.",
            "project": {},
        }
    return {
        "success": True,
        "status": "success",
        "project": project,
        "bundle": build_opengauss_bundle("starter", project=project),
    }


@tool("opengauss_project", "Inspect, prepare, scaffold, or query an OpenGauss workspace.")
async def opengauss_project(
    action: str = "status",
    path: str = "",
    name: str = "",
    image: str = "opengauss/opengauss-server:latest",
    port: int = 5432,
    database: str = "appdb",
    user: str = "root",
    password: str = "OpenGauss@123",
    include_samples: bool = True,
    force: bool = False,
    dry_run: bool = False,
    execute: bool = False,
    allow_mutation: bool = False,
    timeout: int = 30,
) -> dict[str, Any]:
    mode = str(action or "status").strip().lower() or "status"
    if mode in {"status", "inspect"}:
        return await opengauss_status(path=path)

    if mode in {"bundle", "workflow"}:
        project = _project_for(path)
        if not project:
            return {
                "success": False,
                "status": "missing",
                "error": "No OpenGauss project found.",
                "project": {},
            }
        return {
            "success": True,
            "status": "success",
            "project": project,
            "bundle": build_opengauss_bundle(mode, project=project, goal=name, backend="docker"),
        }

    if mode in {"query", "ask"}:
        return await opengauss_query(
            sql=name,
            path=path,
            database=database,
            user=user,
            port=port,
            dry_run=dry_run,
            execute=execute,
            allow_mutation=allow_mutation,
            timeout=timeout,
        )

    if mode in {"init", "create", "scaffold"}:
        root = _opengauss_root(path) or _normalize_candidate(path)
        if root is None:
            return {
                "success": False,
                "status": "missing",
                "error": "Project path required.",
                "project": {},
            }
        result = scaffold_project(
            root,
            name=name or root.name,
            image=image,
            port=port,
            database=database,
            user=user,
            password=password,
            include_samples=include_samples,
            force=force,
            dry_run=dry_run,
        )
        result["bundle"] = build_opengauss_bundle("starter", project=result.get("project") or {}, goal=name, backend="docker")
        return result

    return {
        "success": False,
        "status": "unsupported",
        "error": f"Unsupported OpenGauss action: {mode}",
    }


@tool("opengauss_scaffold", "Scaffold an OpenGauss database workspace.")
async def opengauss_scaffold(
    path: str = "",
    name: str = "",
    image: str = "opengauss/opengauss-server:latest",
    port: int = 5432,
    database: str = "appdb",
    user: str = "root",
    password: str = "OpenGauss@123",
    include_samples: bool = True,
    force: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    root = _opengauss_root(path) or _normalize_candidate(path)
    if root is None:
        return {
            "success": False,
            "status": "missing",
            "error": "Project path required.",
        }
    result = scaffold_project(
        root,
        name=name or root.name,
        image=image,
        port=port,
        database=database,
        user=user,
        password=password,
        include_samples=include_samples,
        force=force,
        dry_run=dry_run,
    )
    result["bundle"] = build_opengauss_bundle("starter", project=result.get("project") or {}, goal=name, backend="docker")
    return result


@tool("opengauss_query", "Prepare an OpenGauss SQL query plan or command.")
async def opengauss_query(
    sql: str,
    path: str = "",
    database: str = "appdb",
    user: str = "root",
    port: int = 5432,
    backend: str = "docker",
    dry_run: bool = False,
    execute: bool = False,
    allow_mutation: bool = False,
    timeout: int = 30,
) -> dict[str, Any]:
    return query_project(
        sql=sql,
        path=path,
        database=database,
        user=user,
        port=port,
        backend=backend,
        dry_run=dry_run,
        execute=execute,
        allow_mutation=allow_mutation,
        timeout=timeout,
    )


@tool("opengauss_workflow", "Build an OpenGauss database workflow bundle.")
async def opengauss_workflow(
    action: str = "starter",
    path: str = "",
    goal: str = "",
    target: str = "",
    backend: str = "docker",
) -> dict[str, Any]:
    project = _project_for(path)
    if not project:
        return {
            "success": False,
            "status": "missing",
            "error": "No OpenGauss project found.",
            "project": {},
        }
    bundle = build_opengauss_bundle(action, project=project, goal=goal, target=target, backend=backend)
    return {
        "success": True,
        "status": "success",
        "project": project,
        "workflow": bundle,
        "next_steps": [
            "Review the generated compose file and schema.",
            "Start the container with docker compose up -d.",
            "Use the query script for read-only checks before migrations.",
        ],
    }
