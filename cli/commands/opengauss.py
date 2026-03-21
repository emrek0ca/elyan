from __future__ import annotations

import asyncio
import json
from typing import Any

from tools.opengauss_tools import opengauss_project, opengauss_query, opengauss_scaffold, opengauss_status, opengauss_workflow


def _print(payload: dict[str, Any], *, as_json: bool = False) -> int:
    if as_json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0 if bool(payload.get("success", False)) else 1
    status = str(payload.get("status") or "ok")
    if payload.get("success", False):
        print(f"OpenGauss: {status}")
    else:
        print(f"OpenGauss hata: {payload.get('error') or status}")
    project = payload.get("project") or {}
    if project:
        print(f"Project: {project.get('name') or '-'} ({project.get('root') or '-'})")
    bundle = payload.get("bundle") or payload.get("workflow") or {}
    if bundle:
        print(f"Bundle: {bundle.get('id') or bundle.get('workflow_id') or '-'}")
    command = str(payload.get("command") or "").strip()
    if command:
        print(command)
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
    backend = str(getattr(args, "backend", "docker") or "docker").strip() or "docker"
    name = str(getattr(args, "name", "") or "").strip()
    database = str(getattr(args, "database", "appdb") or "appdb").strip() or "appdb"
    user = str(getattr(args, "user", "root") or "root").strip() or "root"
    password = str(getattr(args, "password", "OpenGauss@123") or "OpenGauss@123").strip() or "OpenGauss@123"
    image = str(getattr(args, "image", "opengauss/opengauss-server:latest") or "opengauss/opengauss-server:latest").strip() or "opengauss/opengauss-server:latest"
    port = int(getattr(args, "port", 5432) or 5432)
    include_samples = bool(getattr(args, "include_samples", True))
    force = bool(getattr(args, "force", False))
    dry_run = bool(getattr(args, "dry_run", False))
    execute = bool(getattr(args, "execute", False))
    allow_mutation = bool(getattr(args, "allow_mutation", False))
    timeout = int(getattr(args, "timeout", 30) or 30)

    if action == "status":
        return _print(_run(opengauss_status(path=path)), as_json=json_mode)

    if action == "project":
        project = _run(opengauss_status(path=path))
        if project.get("success"):
            return _print(project, as_json=json_mode)
        return _print(
            _run(
                opengauss_project(
                    action="scaffold",
                    path=path,
                    name=name or text,
                    image=image,
                    port=port,
                    database=database,
                    user=user,
                    password=password,
                    include_samples=include_samples,
                    force=force,
                    dry_run=dry_run,
                )
            ),
            as_json=json_mode,
        )

    if action == "query":
        return _print(
            _run(
                opengauss_query(
                    sql=text or "SELECT 1;",
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
            ),
            as_json=json_mode,
        )

    if action in {"scaffold", "bundle", "workflow"}:
        if action in {"bundle", "workflow"}:
            return _print(
                _run(
                    opengauss_workflow(
                        action="starter",
                        path=path,
                        goal=name or text,
                        target=database,
                        backend=backend,
                    )
                ),
                as_json=json_mode,
            )
        return _print(
            _run(
                opengauss_scaffold(
                    path=path,
                    name=name or text,
                    image=image,
                    port=port,
                    database=database,
                    user=user,
                    password=password,
                    include_samples=include_samples,
                    force=force,
                    dry_run=dry_run,
                )
            ),
            as_json=json_mode,
        )

    return _print({"success": False, "status": "unsupported", "error": f"Unsupported OpenGauss action: {action}"}, as_json=json_mode)
