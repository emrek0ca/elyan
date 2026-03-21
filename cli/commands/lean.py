from __future__ import annotations

import asyncio
import json
from typing import Any

from tools.lean_tools import lean_project, lean_swarm, lean_workflow, lean_status


def _print(payload: dict[str, Any], *, as_json: bool = False) -> int:
    if as_json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0 if bool(payload.get("success", False)) else 1
    status = str(payload.get("status") or "ok")
    if payload.get("success", False):
        print(f"Lean: {status}")
    else:
        print(f"Lean hata: {payload.get('error') or status}")
    project = payload.get("project") or payload.get("active_project") or {}
    if project:
        root = project.get("root") or "-"
        name = project.get("name") or "-"
        print(f"Project: {name} ({root})")
    workflow = payload.get("workflow") or {}
    if workflow:
        print(f"Workflow: {workflow.get('workflow_id') or '-'} [{workflow.get('status') or '-'}]")
    sessions = payload.get("sessions") or []
    if sessions:
        print(f"Sessions: {len(sessions)}")
    message = str(payload.get("message") or "").strip()
    if message:
        print(message)
    return 0 if bool(payload.get("success", False)) else 1


def _run(coro):
    return asyncio.run(coro)


def run(args) -> int:
    action = str(getattr(args, "action", "") or "status").strip().lower() or "status"
    path = str(getattr(args, "path", "") or "").strip()
    text = " ".join(str(item) for item in list(getattr(args, "text", []) or []) if str(item).strip()).strip()
    json_mode = bool(getattr(args, "json", False))
    backend = str(getattr(args, "backend", "auto") or "auto").strip() or "auto"
    dry_run = bool(getattr(args, "dry_run", False))
    verify = not bool(getattr(args, "no_verify", False))
    name = str(getattr(args, "name", "") or "").strip()
    target = str(getattr(args, "target", "") or "").strip()
    swarm_action = str(getattr(args, "swarm_action", "list") or "list").strip().lower() or "list"
    session_id = str(getattr(args, "session_id", "") or "").strip()

    if action == "status":
        return _print(_run(lean_status(path=path)), as_json=json_mode)

    if action == "project":
        project_action = str(getattr(args, "project_action", "") or "status").strip().lower() or "status"
        if project_action == "status":
            return _print(_run(lean_project(action="status", path=path, name=name, activate=True)), as_json=json_mode)
        if project_action in {"init", "create", "use", "clear", "list"}:
            return _print(
                _run(lean_project(action=project_action, path=path, name=name, activate=True, create_manifest=True)),
                as_json=json_mode,
            )
        return _print({"success": False, "status": "unsupported", "error": f"Unsupported project action: {project_action}"}, as_json=json_mode)

    if action == "swarm":
        return _print(_run(lean_swarm(action=swarm_action, session_id=session_id, path=path)), as_json=json_mode)

    if action in {"prove", "draft", "autoprove", "formalize", "autoformalize"}:
        goal = str(getattr(args, "goal", "") or "").strip() or text
        return _print(
            _run(
                lean_workflow(
                    action=action,
                    path=path,
                    goal=goal,
                    target=target,
                    backend=backend,
                    dry_run=dry_run,
                    verify=verify,
                )
            ),
            as_json=json_mode,
        )

    return _print({"success": False, "status": "unsupported", "error": f"Unsupported lean action: {action}"}, as_json=json_mode)
