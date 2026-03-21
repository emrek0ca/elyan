from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

from core.quivr.project import (
    ask_quivr_brain,
    build_quivr_bundle,
    detect_project_root,
    resolve_project_root,
    scaffold_project,
    summarize_project,
)
from core.registry import tool


def _quivr_root(path: str = ""):
    root = resolve_project_root(path) if path else None
    if root:
        return root
    return detect_project_root(path)


def _project_for(path: str) -> dict[str, Any]:
    root = _quivr_root(path)
    if not root:
        return {}
    return summarize_project(root)


def _normalize_paths(file_paths: Sequence[str] | None) -> list[str]:
    paths = []
    for item in list(file_paths or []):
        raw = str(item or "").strip()
        if not raw:
            continue
        try:
            paths.append(str(Path(raw).expanduser().resolve()))
        except Exception:
            continue
    return paths


@tool("quivr_status", "Inspect a Quivr second-brain project.")
async def quivr_status(path: str = "") -> dict[str, Any]:
    project = _project_for(path)
    if not project:
        return {
            "success": False,
            "status": "missing",
            "error": "No Quivr project found. Use quivr_scaffold first.",
            "project": {},
        }
    bundle = build_quivr_bundle("starter", project=project)
    return {
        "success": True,
        "status": "success",
        "project": project,
        "bundle": bundle,
        "message": f"Quivr project ready: {project.get('name') or 'quivr'}",
        "data": {
            "project": project,
            "bundle": bundle,
        },
    }


@tool("quivr_project", "Inspect, prepare, scaffold, or query a Quivr second-brain project.")
async def quivr_project(
    action: str = "status",
    path: str = "",
    name: str = "",
    file_paths: list[str] | None = None,
    question: str = "",
    retrieval_config_path: str = "",
    backend: str = "auto",
    include_samples: bool = True,
    force: bool = False,
    dry_run: bool = False,
    use_llm: bool = False,
) -> dict[str, Any]:
    mode = str(action or "status").strip().lower() or "status"
    if mode in {"status", "inspect"}:
        return await quivr_status(path=path)

    if mode in {"bundle", "workflow"}:
        project = _project_for(path)
        if not project:
            return {
                "success": False,
                "status": "missing",
                "error": "No Quivr project found.",
                "project": {},
            }
        bundle = build_quivr_bundle(mode, project=project, goal=name, backend=backend)
        return {
            "success": True,
            "status": "success",
            "project": project,
            "bundle": bundle,
            "message": f"Quivr bundle prepared: {project.get('name') or 'quivr'}",
            "data": {
                "project": project,
                "bundle": bundle,
            },
        }

    if mode in {"ask", "query", "brain"}:
        return await quivr_brain_ask(
            question=question or name,
            path=path,
            file_paths=file_paths,
            retrieval_config_path=retrieval_config_path,
            backend=backend,
            use_llm=use_llm,
        )

    if mode in {"init", "create", "scaffold"}:
        root = _quivr_root(path) or _normalize_candidate(path)
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
            include_samples=include_samples,
            force=force,
            dry_run=dry_run,
        )
        result["bundle"] = build_quivr_bundle("starter", project=result.get("project") or {}, goal=name, backend=backend)
        return result

    return {
        "success": False,
        "status": "unsupported",
        "error": f"Unsupported Quivr action: {mode}",
    }


def _normalize_candidate(path: str) -> Path | None:
    raw = str(path or "").strip()
    if not raw:
        return None
    try:
        return Path(raw).expanduser().resolve()
    except Exception:
        return None


@tool("quivr_scaffold", "Scaffold a Quivr second-brain app.")
async def quivr_scaffold(
    path: str = "",
    name: str = "",
    include_samples: bool = True,
    force: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    root = _quivr_root(path) or _normalize_candidate(path)
    if root is None:
        return {
            "success": False,
            "status": "missing",
            "error": "Project path required.",
        }
    result = scaffold_project(
        root,
        name=name or root.name,
        include_samples=include_samples,
        force=force,
        dry_run=dry_run,
    )
    result["bundle"] = build_quivr_bundle("starter", project=result.get("project") or {}, goal=name)
    return result


@tool("quivr_brain_ask", "Ask a question against a Quivr brain or Elyan fallback RAG.")
async def quivr_brain_ask(
    question: str,
    path: str = "",
    file_paths: list[str] | None = None,
    retrieval_config_path: str = "",
    backend: str = "auto",
    use_llm: bool = False,
) -> dict[str, Any]:
    source_paths = _normalize_paths(file_paths)
    result = await ask_quivr_brain(
        question=question,
        path=path,
        file_paths=source_paths,
        retrieval_config_path=retrieval_config_path,
        backend=backend,
        use_llm=use_llm,
    )
    return result
