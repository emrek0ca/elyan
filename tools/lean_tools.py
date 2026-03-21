from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any

from elyan.core.security import get_security_layer
from core.lean.project import (
    build_workflow_bundle,
    detect_project_root,
    get_active_project,
    list_projects,
    list_workflow_sessions,
    record_workflow_session,
    register_project,
    resolve_project_root,
    set_active_project,
    summarize_project,
    update_workflow_session,
)
from core.registry import tool


def _lean_root(path: str = ""):
    root = resolve_project_root(path) if path else None
    if root:
        return root
    active = get_active_project()
    if active.get("root"):
        return resolve_project_root(active.get("root"))
    return detect_project_root()


def _sandbox_command(action: str, root: str, target: str = "") -> str:
    target_text = str(target or "").strip()
    action_text = str(action or "").strip().lower()
    if target_text:
        target_path = Path(target_text)
        if target_path.is_absolute():
            try:
                target_path = target_path.relative_to(Path(root))
            except Exception:
                target_path = Path(target_path.name)
        return f"lake env lean {shlex.quote(str(target_path))}"
    if action_text == "status":
        return "(lean --version || lake --version)"
    return "lake build"


def _lean_workflow_result(project: dict[str, Any], session: dict[str, Any], bundle: dict[str, Any], verification: dict[str, Any]) -> dict[str, Any]:
    success = bool(verification.get("success", True)) if verification else True
    status = str(verification.get("status") or session.get("status") or ("success" if success else "failed"))
    result = {
        "success": success,
        "status": status,
        "project": project,
        "workflow": session,
        "workflow_bundle": bundle,
        "verification": verification,
        "next_steps": [
            "Open the trace in Elyan dashboard.",
            "Inspect the project-scoped Lean proof bundle.",
            "If build failed, patch the theorem and rerun the workflow.",
        ],
    }
    if verification:
        result["message"] = str(verification.get("stdout") or verification.get("message") or verification.get("error") or "").strip()
    return result


@tool("lean_status", "Inspect the active Lean project and toolchain readiness.")
async def lean_status(path: str = "") -> dict[str, Any]:
    resolved_root = _lean_root(path)
    project = summarize_project(resolved_root or path) if (path or resolved_root) else {}
    if not project:
        return {
            "success": False,
            "status": "missing",
            "error": "No Lean project found. Use lean_project(action='init') first.",
            "project": {},
            "projects": list_projects(),
        }

    command = _sandbox_command("status", str(project.get("root") or ""))
    toolchain = await get_security_layer().execute_safe(
        "lean",
        {
            "type": "lean_status",
            "action": "lean_status",
            "description": "Check Lean toolchain readiness",
            "language": "shell",
            "command": command or "lean --version",
            "workspace_dir": str(project.get("root") or ""),
            "volumes": {str(project.get("root") or ""): "/workspace"} if project.get("root") else {},
            "needs_network": False,
            "read_only": True,
            "timeout": 30,
        },
        command or "lean --version",
        {"workspace_dir": str(project.get("root") or ""), "workspace": str(project.get("root") or "")},
    )
    sessions = list_workflow_sessions(project.get("root"))
    return {
        "success": bool(toolchain.get("success", False)),
        "status": "ready" if project.get("status") == "ready" else "scaffolded",
        "project": project,
        "projects": list_projects(),
        "sessions": sessions,
        "toolchain": toolchain,
        "command": command,
    }


@tool("lean_project", "Register, inspect, activate, or clear a Lean project.")
async def lean_project(
    action: str = "status",
    path: str = "",
    name: str = "",
    create_manifest: bool = False,
    activate: bool = True,
) -> dict[str, Any]:
    mode = str(action or "status").strip().lower() or "status"
    if mode in {"clear"}:
        active = set_active_project(None)
        return {"success": True, "status": "cleared", "active_project": active, "projects": list_projects()}

    if mode in {"init", "create", "use"}:
        root = _lean_root(path) or resolve_project_root(path) or detect_project_root()
        if root is None:
            if not path:
                return {
                    "success": False,
                    "status": "missing",
                    "error": "Project path required.",
                    "projects": list_projects(),
                }
            candidate = Path(path).expanduser().resolve()
            if mode in {"init", "create"}:
                root = candidate
            else:
                root = resolve_project_root(candidate) or detect_project_root(candidate) or None
        if root is None:
            return {
                "success": False,
                "status": "missing",
                "error": "Could not resolve project root.",
                "projects": list_projects(),
            }
        project = register_project(root, name=name or "", source="cli", activate=activate, create_manifest=True)
        if mode == "use":
            set_active_project(project.get("root"))
        return {"success": True, "status": "ready", "project": project, "projects": list_projects()}

    root = _lean_root(path)
    if root is None:
        root = detect_project_root(path) or detect_project_root()
    if root is None:
        active = get_active_project()
        if active.get("root"):
            root = resolve_project_root(active.get("root"))
    if root is None:
        return {
            "success": False,
            "status": "missing",
            "error": "No Lean project found.",
            "projects": list_projects(),
        }

    if mode == "list":
        return {
            "success": True,
            "status": "ok",
            "projects": list_projects(),
            "active_project": get_active_project(),
        }

    project = summarize_project(root)
    if not project.get("registered"):
        project = register_project(root, name=name or "", source="cli", activate=activate, create_manifest=create_manifest)
    return {
        "success": True,
        "status": "ready" if project.get("status") == "ready" else "scaffolded",
        "project": project,
        "projects": list_projects(),
        "active_project": get_active_project(),
    }


@tool("lean_workflow", "Run Lean prove/draft/formalize workflows with project-scoped orchestration.")
async def lean_workflow(
    action: str = "prove",
    path: str = "",
    goal: str = "",
    target: str = "",
    backend: str = "auto",
    dry_run: bool = False,
    verify: bool = True,
) -> dict[str, Any]:
    mode = str(action or "prove").strip().lower() or "prove"
    resolved_root = _lean_root(path)
    project = summarize_project(resolved_root or path) if (path or resolved_root) else {}
    if not project:
        return {
            "success": False,
            "status": "missing",
            "error": "No Lean project found.",
            "projects": list_projects(),
        }

    bundle = build_workflow_bundle(mode, project=project, goal=goal, target=target, backend=backend)
    prompt = str(bundle.get("prompt") or "")
    command = _sandbox_command(mode, str(project.get("root") or ""), target=target)
    bundle["command"] = command
    session = record_workflow_session(
        mode,
        project_root=project["root"],
        project_name=str(project.get("name") or ""),
        prompt=prompt,
        goal=goal,
        target=target,
        backend=backend,
        command=command,
        status="planned" if dry_run or mode == "draft" else "running",
        notes=[f"workflow_profile={mode}", f"backend={backend}"],
    )

    verification: dict[str, Any] = {}
    if verify and not dry_run and mode in {"prove", "autoprove", "formalize", "autoformalize"}:
        verification = await get_security_layer().execute_safe(
            "lean",
            {
                "type": "lean_workflow",
                "action": mode,
                "description": f"Run Lean workflow: {mode}",
                "language": "shell",
                "command": command,
                "workspace_dir": project["root"],
                "volumes": {project["root"]: "/workspace"},
                "needs_network": False,
                "read_only": False,
                "timeout": 90,
            },
            command,
            {"workspace_dir": project["root"], "workspace": project["root"]},
        )
        session = update_workflow_session(
            session["workflow_id"],
            status="completed" if bool(verification.get("success", False)) else "failed",
            result=verification,
        ) or session
    else:
        session = update_workflow_session(session["workflow_id"], status=session.get("status", "planned"), result={}) or session

    result = _lean_workflow_result(project, session, bundle, verification)
    if not command:
        result["status"] = "planned"
    return result


@tool("lean_swarm", "Inspect or update Lean workflow sessions.")
async def lean_swarm(
    action: str = "list",
    session_id: str = "",
    path: str = "",
) -> dict[str, Any]:
    mode = str(action or "list").strip().lower() or "list"
    root = _lean_root(path)
    sessions = list_workflow_sessions(root)
    if mode == "list":
        return {
            "success": True,
            "status": "ok",
            "sessions": sessions,
            "active_project": get_active_project(),
        }
    if mode == "attach":
        target = str(session_id or "").strip()
        match = next((row for row in sessions if str(row.get("workflow_id") or "") == target), {})
        return {
            "success": bool(match),
            "status": "attached" if match else "missing",
            "session": match,
        }
    if mode == "cancel":
        target = str(session_id or "").strip()
        updated = update_workflow_session(target, status="cancelled")
        return {
            "success": bool(updated),
            "status": "cancelled" if updated else "missing",
            "session": updated,
        }
    return {
        "success": False,
        "status": "unsupported",
        "error": f"Unsupported swarm action: {mode}",
        "sessions": sessions,
    }
