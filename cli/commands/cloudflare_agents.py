from __future__ import annotations

import asyncio
import json
from typing import Any

from tools.cloudflare_agents_tools import (
    cloudflare_agents_project,
    cloudflare_agents_scaffold,
    cloudflare_agents_status,
    cloudflare_agents_workflow,
)


def _print(payload: dict[str, Any], *, as_json: bool = False) -> int:
    if as_json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0 if bool(payload.get("success", False)) else 1
    status = str(payload.get("status") or "ok")
    if payload.get("success", False):
        print(f"Cloudflare Agents: {status}")
    else:
        print(f"Cloudflare Agents hata: {payload.get('error') or status}")
    project = payload.get("project") or {}
    if project:
        print(f"Project: {project.get('name') or '-'} ({project.get('root') or '-'})")
    bundle = payload.get("bundle") or payload.get("workflow") or {}
    if bundle:
        print(f"Bundle: {bundle.get('id') or bundle.get('workflow_id') or '-'}")
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
    name = str(getattr(args, "name", "") or "").strip()
    include_chat = bool(getattr(args, "include_chat", True))
    include_workflows = bool(getattr(args, "include_workflows", True))
    include_mcp = bool(getattr(args, "include_mcp", True))
    force = bool(getattr(args, "force", False))
    dry_run = bool(getattr(args, "dry_run", False))

    if action == "status":
        return _print(_run(cloudflare_agents_status(path=path)), as_json=json_mode)

    if action == "project":
        project = _run(cloudflare_agents_status(path=path))
        if project.get("success"):
            return _print(project, as_json=json_mode)
        return _print(
            _run(
                cloudflare_agents_project(
                    action="scaffold",
                    path=path,
                    name=name or text,
                    include_chat=include_chat or True,
                    include_workflows=include_workflows or True,
                    include_mcp=include_mcp or True,
                    force=force,
                    dry_run=dry_run,
                )
            ),
            as_json=json_mode,
        )

    if action in {"scaffold", "bundle", "workflow"}:
        if action in {"bundle", "workflow"}:
            return _print(
                _run(
                    cloudflare_agents_workflow(
                        action="starter",
                        path=path,
                        goal=name or text,
                        backend=backend,
                    )
                ),
                as_json=json_mode,
            )
        return _print(
            _run(
                cloudflare_agents_scaffold(
                    path=path,
                    name=name or text,
                    include_chat=include_chat or True,
                    include_workflows=include_workflows or True,
                    include_mcp=include_mcp or True,
                    force=force,
                    dry_run=dry_run,
                )
            ),
            as_json=json_mode,
        )

    return _print({"success": False, "status": "unsupported", "error": f"Unsupported Cloudflare Agents action: {action}"}, as_json=json_mode)
